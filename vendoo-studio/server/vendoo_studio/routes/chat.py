from __future__ import annotations

import asyncio
import functools
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR
from vendoo_studio.database import SessionLocal, get_db
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.chat_listing import persist_chat_result
from vendoo_studio.services.chat_prompts import build_chat_messages
from vendoo_studio.services.listing_generate import (
    PHOTO_ANALYSIS_RETRY_MESSAGE,
    PhotoAnalysisError,
    require_photo_analysis,
    seller_item_details,
)
from vendoo_studio.services.listing_generation import run_listing_generation
from vendoo_studio.services.listing_provider import get_listing_provider
from vendoo_studio.services.streaming import (
    KEEPALIVE,
    SSE_HEADERS,
    active_generation,
    iter_with_keepalives,
    sse_data,
    sse_event,
    sse_for_stream_item,
    start_generation,
    stop_generation,
    stream_generation,
    wait_task_keepalives,
)


def _require_provider():
    provider = get_listing_provider()
    if provider is None:
        raise HTTPException(
            400,
            "Sign in with ChatGPT in Settings, or add a MiMo API key.",
        )
    return provider


def _provider_meta(provider) -> tuple[str, str]:
    return (
        getattr(provider, "name", "xiaomi-mimo"),
        getattr(provider, "listing_model", "mimo-v2.5-pro"),
    )


def _vision_meta(provider) -> tuple[str, str]:
    return (
        getattr(provider, "name", "xiaomi-mimo"),
        getattr(provider, "vision_model", "mimo-v2.5"),
    )


log = logging.getLogger("vendoo_studio.chat")

router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    text: str


@router.post("/api/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: ChatMessage, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    repo.add_message(conv_id, "user", body.text)
    provider = get_listing_provider()
    if provider is None:
        repo.add_message(
            conv_id,
            "system",
            "Sign in with ChatGPT in Settings, or add a MiMo API key, then retry this prompt.",
            provider="system",
            model="",
        )
        repo.update_status(conv_id, "draft")
        raise HTTPException(
            400,
            "Sign in with ChatGPT in Settings, or add a MiMo API key.",
        )
    provider_name, provider_model = _provider_meta(provider)

    revisions = ListingRepo(db).get_revisions(conv_id)
    if repo.get_photos(conv_id) and (not revisions or revisions[0].source == "category_analysis"
                                   or not (revisions[0].listing_json or {}).get("title")):
        # Seller answers during category discovery resume the same generation
        # pipeline; chat must not bypass the schema prerequisite.
        return await generate_listing(conv_id, db)

    repo.update_status(conv_id, "in_progress")

    try:
        messages = await build_chat_messages(conv_id, db, body.text)
    except PhotoAnalysisError as exc:
        repo.update_status(conv_id, "draft")
        raise HTTPException(502, str(exc)) from exc

    async def stream_response():
        stream_db = SessionLocal()
        full_text = ""
        stream_error = ""
        try:
            async for item in iter_with_keepalives(provider.chat(messages, stream=True)):
                if item is None:
                    yield KEEPALIVE
                    continue
                payload, content = sse_for_stream_item(item)
                if content:
                    full_text += content
                if payload:
                    yield payload
            if not full_text.strip():
                stream_error = "The listing assistant returned an empty response. Retry this prompt."
                yield sse_event("error", stream_error)

            # Persist before [DONE] so Forms/Fields refetch the updated listing JSON.
            yield sse_event("status", "Saving listing…")
            persist_task = asyncio.create_task(
                persist_chat_result(
                    stream_db,
                    conv_id,
                    full_text,
                    provider,
                    provider_name=provider_name,
                    provider_model=provider_model,
                    stream_error=stream_error,
                    user_message=body.text,
                )
            )
            async for _ in wait_task_keepalives(persist_task, timeout=2.0):
                yield KEEPALIVE
            try:
                _operations, saved = persist_task.result()
            except Exception:
                log.exception("failed to persist chat result for %s", conv_id)
                try:
                    ConversationRepo(stream_db).update_status(conv_id, "draft")
                except Exception:
                    log.exception("failed to reset status after chat persist error for %s", conv_id)
                saved = False
            if saved:
                yield sse_event("listing_updated", "1")
            yield "data: [DONE]\n\n"
        except Exception as e:
            message = str(e).strip() or type(e).__name__
            log.exception("chat stream failed for %s: %s", conv_id, message)
            stream_error = message
            yield sse_data(f"Error: {message}")
            try:
                ConversationRepo(stream_db).update_status(conv_id, "draft")
            except Exception:
                log.exception("failed to reset status after chat stream error for %s", conv_id)
            yield "data: [DONE]\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(stream_response(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/api/conversations/{conv_id}/analyze-photos")
async def analyze_photos(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    provider = _require_provider()
    vision_name, vision_model = _vision_meta(provider)

    photos = repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "No photos to analyze")

    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]

    try:
        result = await provider.analyze_photos(paths, notes=conv.notes or "")
    except Exception as exc:
        raise HTTPException(502, PHOTO_ANALYSIS_RETRY_MESSAGE) from exc
    try:
        require_photo_analysis(result)
    except PhotoAnalysisError as exc:
        raise HTTPException(502, str(exc)) from exc

    repo.add_message(
        conv_id,
        "system",
        f"Photo analysis complete. Found: {len(photos)} photos analyzed.",
        provider=vision_name,
        model=vision_model,
    )

    return result


@router.post("/api/conversations/{conv_id}/generate")
async def generate_listing(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    provider = _require_provider()
    vision_name, vision_model = _vision_meta(provider)

    existing = active_generation(conv_id)
    if existing is not None:
        return stream_generation(existing)

    photos = repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "No photos to generate from. Upload product photos first.")

    repo.update_status(conv_id, "in_progress")
    notes = conv.notes or ""
    item_details = seller_item_details(notes)
    seller_answers = "\n".join(message.text for message in repo.get_messages(conv_id) if message.role == "user")
    if seller_answers:
        item_details += "\nSeller answers:\n" + seller_answers
    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
    photo_count = len(photos)
    # Release the request-scoped session before background work opens its own.
    db.close()

    run = start_generation(conv_id, functools.partial(
        run_listing_generation,
        conv_id=conv_id,
        provider=provider,
        vision_name=vision_name,
        vision_model=vision_model,
        notes=notes,
        item_details=item_details,
        seller_answers=seller_answers,
        paths=paths,
        photo_count=photo_count,
    ))
    await asyncio.sleep(0)
    return stream_generation(run)


@router.post("/api/conversations/{conv_id}/generate/cancel")
async def cancel_generate_listing(conv_id: str):
    stop_generation(conv_id)
    db = SessionLocal()
    try:
        ConversationRepo(db).update_status(conv_id, "draft")
    finally:
        db.close()
    return {"ok": True}


@router.post("/api/conversations/{conv_id}/messages/cancel")
async def cancel_chat_message(conv_id: str):
    db = SessionLocal()
    try:
        ConversationRepo(db).update_status(conv_id, "draft")
    finally:
        db.close()
    return {"ok": True}
