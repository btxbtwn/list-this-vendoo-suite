from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.config import PHOTOS_DIR, skills_dir
from vendoo_studio.database import SessionLocal, get_db
from vendoo_studio.providers.xiaomi_mimo import MiMoProvider
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.keychain import get_api_key
from vendoo_studio.services.listing_generate import (
    extract_listing_json,
    format_photo_analysis,
    latest_photo_analysis,
    persist_generated_listing,
    seller_item_details,
)

log = logging.getLogger("vendoo_studio.chat")

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
KEEPALIVE = ": keepalive\n\n"


class ChatMessage(BaseModel):
    text: str


def _sse_encode(text: str) -> str:
    return text.replace("\n", "\ndata: ")


def _sse_data(text: str) -> str:
    return f"data: {_sse_encode(text)}\n\n"


def _load_skill_rules() -> str:
    skill_md = skills_dir() / "list-this" / "SKILL.md"
    template_md = skills_dir() / "list-this" / "references" / "vendoo_listing_template.md"

    parts = []
    if skill_md.exists():
        parts.append(skill_md.read_text())
    if template_md.exists():
        parts.append(template_md.read_text())

    return "\n\n---\n\n".join(parts) if parts else ""


async def _iter_with_keepalives(source, timeout: float = 10.0):
    iterator = source.__aiter__()
    pending = None
    while True:
        if pending is None:
            pending = asyncio.ensure_future(iterator.__anext__())
        try:
            item = await asyncio.wait_for(asyncio.shield(pending), timeout=timeout)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError:
            yield None
            continue
        pending = None
        yield item


def _learned_fields_prompt(db: Session, conv_id: str) -> str:
    from vendoo_studio.services.registry import RegistryService

    category_path = None
    revisions = ListingRepo(db).get_revisions(conv_id)
    if revisions and isinstance(revisions[0].listing_json, dict):
        category_path = revisions[0].listing_json.get("category_path") or None
    text = RegistryService(db).generation_context(category_path)
    if not text:
        return ""
    return f"\n\n--- Learned fields ---\n\n{text}"


def _stamp_learned_fields(db: Session, listing: dict) -> dict:
    from vendoo_studio.services.registry import RegistryService

    if isinstance(listing, dict):
        RegistryService(db).merge_learned_fields(listing)
    return listing


async def _build_messages(conv_id: str, db: Session, user_message: str) -> list[dict]:
    repo = ConversationRepo(db)
    history = repo.get_messages(conv_id)
    photos = repo.get_photos(conv_id)

    skill_rules = _load_skill_rules()

    photo_analysis_text = ""
    if photos and len(history) <= 2:
        key = get_api_key()
        if key:
            paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
            provider = MiMoProvider(api_key=key)
            result = await provider.analyze_photos(paths, notes="", listing_rules=skill_rules[:8000])
            evidence = result.get("evidence", {}) or {}

            if evidence:
                analysis_note = format_photo_analysis(evidence).replace("Photo analysis:\n", "Photo analysis of the uploaded product images:\n", 1)
                repo.add_message(conv_id, "system", "Photo analysis complete:\n" + analysis_note)
                photo_analysis_text = "\n\n" + analysis_note
            else:
                photo_analysis_text = f"\n\nThe user uploaded {len(photos)} product photos. Use the list-this workflow to generate a listing based on contextual understanding."

    system_prompt = {
        "role": "system",
        "content": (
            "You are a product listing assistant. Your ONLY output is valid JSON. No explanations, no markdown, no code fences.\n\n"
            "You use the listing rules below to generate accurate, formula-compliant marketplace listings.\n\n"
            "When the user asks you to revise a listing, output ONLY a JSON Patch array:\n"
            '[{"op": "replace", "path": "/title", "value": "New Title"}, ...]\n\n'
            "When generating a complete listing from scratch, output ONLY the full listing JSON object.\n\n"
            "Key rules:\n"
            "- Never publish. Stop at saved drafts.\n"
            "- Be conservative with brand and size. Ask when uncertain instead of guessing.\n"
            "- General Vendoo category paths must use Vendoo taxonomy: women's shirts and T-shirts end at Women > Women's Clothing > Tops, never Shirts & Blouses.\n"
            "- Follow the title and description formulas EXACTLY from the rules below.\n"
            "- Always fill ALL eBay specifics when generating a complete listing.\n"
            "- Depop: exactly 3 style tags from the allowed values list.\n"
            + (f"\n{photo_analysis_text}\n\n" if photo_analysis_text else "") +
            f"\n--- Listing Rules ---\n\n{skill_rules}"
            if skill_rules
            else ""
        ) + _learned_fields_prompt(db, conv_id),
    }

    messages = [system_prompt]
    for msg in history[-20:]:
        role = msg.role
        if role == "model":
            role = "assistant"
        messages.append({"role": role, "content": msg.text})

    messages.append({"role": "user", "content": user_message})
    return messages


def _apply_listing_payload(db: Session, conv_id: str, full_text: str) -> None:
    parsed = extract_listing_json(full_text)
    if parsed:
        lr = ListingRepo(db)
        revisions = lr.get_revisions(conv_id)
        parent_id = revisions[0].id if revisions else None
        lr.save_revision(conv_id, _stamp_learned_fields(db, parsed), source="model_refinement", parent_revision_id=parent_id)
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            "Listing updated automatically from refinement.",
            provider="system",
            model="",
        )
        return

    try:
        import json as _json
        text = full_text.strip()
        if text.startswith("```"):
            import re as _re
            match = _re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
            if match:
                text = match.group(1).strip()
        parsed_ops = _json.loads(text)
    except Exception:
        return

    if not (isinstance(parsed_ops, list) and parsed_ops and all(isinstance(op, dict) and op.get("op") for op in parsed_ops)):
        return

    import copy

    lr = ListingRepo(db)
    revisions = lr.get_revisions(conv_id)
    if not revisions:
        return
    updated = copy.deepcopy(dict(revisions[0].listing_json))
    for op in parsed_ops:
        op_type = op.get("op")
        path = (op.get("path") or "").lstrip("/")
        value = op.get("value")
        if op_type == "replace" or op_type == "add":
            keys = path.split("/")
            target = updated
            for k in keys[:-1]:
                if k not in target:
                    target[k] = {}
                target = target[k]
            target[keys[-1]] = value
        elif op_type == "remove":
            keys = path.split("/")
            target = updated
            for k in keys[:-1]:
                target = target.get(k, {})
            if isinstance(target, dict) and keys[-1] in target:
                del target[keys[-1]]
    lr.save_revision(conv_id, _stamp_learned_fields(db, updated), source="model_refinement", parent_revision_id=revisions[0].id)
    ConversationRepo(db).add_message(
        conv_id,
        "system",
        "Listing updated automatically from refinement.",
        provider="system",
        model="",
    )


@router.post("/api/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: ChatMessage, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    key = get_api_key()
    if not key:
        raise HTTPException(400, "No API key configured. Add your MiMo key in Settings first.")

    repo.update_status(conv_id, "in_progress")
    repo.add_message(conv_id, "user", body.text)

    messages = await _build_messages(conv_id, db, body.text)
    provider = MiMoProvider(api_key=key)

    async def stream_response():
        stream_db = SessionLocal()
        full_text = ""
        try:
            async for item in _iter_with_keepalives(provider.chat(messages, stream=True)):
                if item is None:
                    yield KEEPALIVE
                    continue
                full_text += item
                yield _sse_data(item)
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.exception("chat stream failed for %s", conv_id)
            yield _sse_data(f"Error: {e}")
            yield "data: [DONE]\n\n"

        stream_repo = ConversationRepo(stream_db)
        try:
            if full_text and not full_text.lstrip().lower().startswith("error:"):
                stream_repo.add_message(conv_id, "assistant", full_text, provider="xiaomi-mimo", model="mimo-v2.5-pro")
                _apply_listing_payload(stream_db, conv_id, full_text)
            stream_repo.update_status(conv_id, "draft")
        except Exception:
            log.exception("failed to persist chat result for %s", conv_id)
            try:
                stream_repo.update_status(conv_id, "draft")
            except Exception:
                log.exception("failed to reset status after chat persist error for %s", conv_id)
        finally:
            stream_db.close()

    return StreamingResponse(stream_response(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/api/conversations/{conv_id}/analyze-photos")
async def analyze_photos(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    key = get_api_key()
    if not key:
        raise HTTPException(400, "No API key configured")

    photos = repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "No photos to analyze")

    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]

    provider = MiMoProvider(api_key=key)
    result = await provider.analyze_photos(paths, notes=conv.notes or "")

    repo.add_message(
        conv_id,
        "system",
        f"Photo analysis complete. Found: {len(photos)} photos analyzed.",
        provider="xiaomi-mimo",
        model="mimo-v2.5",
    )

    return result


@router.post("/api/conversations/{conv_id}/generate")
async def generate_listing(conv_id: str, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    key = get_api_key()
    if not key:
        raise HTTPException(400, "No API key configured")

    photos = repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "No photos to generate from. Upload product photos first.")

    repo.update_status(conv_id, "in_progress")
    skill_rules = _load_skill_rules()
    notes = conv.notes or ""
    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
    provider = MiMoProvider(api_key=key)

    async def stream_response():
        yield KEEPALIVE
        stream_db = SessionLocal()
        stream_repo = ConversationRepo(stream_db)
        full_text = ""
        try:
            existing = latest_photo_analysis(stream_repo.get_messages(conv_id))
            if existing:
                analysis_text = existing
            else:
                analysis_task = asyncio.create_task(
                    provider.analyze_photos(paths, notes=notes, listing_rules=skill_rules[:8000])
                )
                while not analysis_task.done():
                    yield KEEPALIVE
                    try:
                        await asyncio.wait_for(asyncio.shield(analysis_task), timeout=10)
                    except asyncio.TimeoutError:
                        continue
                try:
                    result = analysis_task.result()
                    evidence = result.get("evidence", {}) or {}
                    if result.get("error") and not evidence:
                        analysis_text = f"Photo analysis unavailable ({result['error']}). Use contextual knowledge."
                    else:
                        analysis_text = format_photo_analysis(evidence)
                except Exception as e:
                    analysis_text = f"Photo analysis unavailable ({e}). Use contextual knowledge."
                stream_repo.add_message(conv_id, "system", analysis_text, provider="xiaomi-mimo", model="mimo-v2.5")

            item_details = seller_item_details(notes)
            messages = _listing_messages(skill_rules, item_details, analysis_text, stream_db, conv_id)

            async for item in _iter_with_keepalives(provider.chat(messages, stream=True)):
                if item is None:
                    yield KEEPALIVE
                    continue
                full_text += item
                yield _sse_data(item)

            if not full_text.strip() or full_text.lstrip().lower().startswith("error:"):
                raise RuntimeError(full_text.strip() or "Listing generation returned no text")
            persist_generated_listing(stream_db, conv_id, full_text)
            stream_repo.update_status(conv_id, "draft")
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            log.warning("listing generation cancelled for %s; saving any completed text", conv_id)
            if full_text.strip() and not full_text.lstrip().lower().startswith("error:"):
                try:
                    persist_generated_listing(stream_db, conv_id, full_text)
                except Exception:
                    log.exception("failed to persist cancelled listing for %s", conv_id)
            try:
                stream_repo.update_status(conv_id, "draft")
            except Exception:
                log.exception("failed to reset status after cancelled listing for %s", conv_id)
            raise
        except Exception as e:
            log.warning("listing generation failed for %s: %s", conv_id, e)
            try:
                yield _sse_data(f"Error: {e}")
                yield "data: [DONE]\n\n"
                stream_repo.update_status(conv_id, "draft")
            except Exception:
                log.exception("failed to report listing generation error for %s", conv_id)
        finally:
            stream_db.close()

    return StreamingResponse(stream_response(), media_type="text/event-stream", headers=SSE_HEADERS)


def _listing_messages(skill_rules: str, item_details: str, analysis_text: str, db: Session, conv_id: str) -> list[dict]:
    system_content = (
        "You are a product listing generator. Generate a COMPLETE, ready-to-use Vendoo listing JSON "
        "from the photo analysis and listing rules below.\n\n"
        "Use Vendoo's General taxonomy for category_path. Women's shirts and T-shirts must use "
        '"Clothing, Shoes & Accessories > Women > Women\'s Clothing > Tops", not "Shirts & Blouses".\n\n'
        "Always include sku (BRAND-SIZE slug, e.g. DISNEY-PARKS-M), primaryColor, and secondaryColor "
        "when a second color is visible. Use Vendoo general condition values such as "
        '"Pre-Owned - Good". Keep tags to 5 or fewer. Depop needs source and age. '
        "Mercari shippingLabel must be USPS Ground Advantage.\n\n"
        "If seller-provided measurements (Pit to pit, Length) are given, use them exactly as-is in the description.\n"
        "Do not modify, estimate, or replace seller-provided measurements.\n\n"
        "Output the full listing JSON inside a fenced code block:\n\n"
        "```json\n"
        "{\n"
        '  "title": "...",\n'
        '  "description": "...",\n'
        '  "price": ...,\n'
        '  "cost": ...,\n'
        '  "quantity": 1,\n'
        '  "brand": "...",\n'
        '  "condition": "...",\n'
        '  "primaryColor": "...",\n'
        '  "secondaryColor": "...",\n'
        '  "sku": "...",\n'
        '  "size": "...",\n'
        '  "sizeType": "...",\n'
        '  "tags": [...],\n'
        '  "package_dimensions_in": "...",\n'
        '  "ebay_specifics": {...},\n'
        '  "depop_specifics": {"source": "Preloved", "age": "Modern"},\n'
        '  "etsy_specifics": {...},\n'
        '  "poshmark_specifics": {"originalPrice": 0},\n'
        '  "mercari_specifics": {"shippingLabel": "USPS Ground Advantage"}\n'
        "}\n"
        "```\n\n"
        f"{item_details}\n\n"
        f"{analysis_text}\n\n"
        f"--- Listing Rules ---\n\n{skill_rules}"
        f"{_learned_fields_prompt(db, conv_id)}"
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "Generate a complete listing from these product photos."},
    ]
