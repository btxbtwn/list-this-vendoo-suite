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
from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.comp_research import comps_search_available, research_sold_comps
from vendoo_studio.services.listing_generate import (
    extract_listing_json,
    format_photo_analysis,
    latest_photo_analysis,
    persist_generated_listing,
    seller_item_details,
)
from vendoo_studio.services.listing_patch import apply_json_patch, extract_json_patch
from vendoo_studio.services.listing_provider import get_listing_provider
from vendoo_studio.services.registry import MEN_TSHIRT_PATH, WOMEN_TOPS_PATH, align_listing_gender


def _require_provider():
    provider = get_listing_provider()
    if provider is None:
        raise HTTPException(
            400,
            "Sign in with ChatGPT in Settings, or add a MiMo API key.",
        )
    return provider


def _provider_meta(provider) -> tuple[str, str]:
    name = getattr(provider, "name", None)
    if name == "chatgpt":
        return "chatgpt", getattr(provider, "listing_model", "gpt-5.5")
    return "xiaomi-mimo", "mimo-v2.5-pro"


def _vision_meta(provider) -> tuple[str, str]:
    name = getattr(provider, "name", None)
    if name == "chatgpt":
        return "chatgpt", getattr(provider, "vision_model", "gpt-5.5")
    return "xiaomi-mimo", "mimo-v2.5"

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


def _sse_event(event: str, text: str) -> str:
    return f"event: {event}\n{_sse_data(text)}"


def _sse_for_stream_item(item) -> tuple[str | None, str]:
    kind, text = unpack_stream_item(item)
    if not text:
        return None, ""
    if kind == "thinking":
        return _sse_event("thinking", text), ""
    return _sse_data(text), text


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


def _current_listing_prompt(db: Session, conv_id: str) -> str:
    revisions = ListingRepo(db).get_revisions(conv_id)
    if not revisions or not isinstance(revisions[0].listing_json, dict):
        return ""
    listing = revisions[0].listing_json
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    return (
        "\n\n--- Current listing ---\n"
        f"department: {listing.get('department') or ''}\n"
        f"category_path: {listing.get('category_path') or ''}\n"
        f"ebay_specifics.department: {(ebay or {}).get('department') or ''}\n"
        "If the seller changes gender or category, replace department, category_path, "
        "and ebay_specifics.department together. Do not leave a women's category on a men's item.\n"
    )


def _sync_category_override(db: Session, conv_id: str, listing: dict) -> None:
    from vendoo_studio.services.vendoo_import import merge_notes, parse_notes

    category = str((listing or {}).get("category_path") or "").strip()
    if not category:
        return
    conv = ConversationRepo(db).get(conv_id)
    if not conv:
        return
    current = str(parse_notes(conv.notes).get("categoryOverride") or "").strip()
    if not current or current == category:
        return
    conv.notes = merge_notes(conv.notes, {"categoryOverride": category})
    db.commit()


def _save_listing_revision(db: Session, conv_id: str, listing: dict, *, operations: list[dict] | None = None) -> dict:
    updated = align_listing_gender(listing, operations)
    stamped = _stamp_learned_fields(db, updated)
    revisions = ListingRepo(db).get_revisions(conv_id)
    parent_id = revisions[0].id if revisions else None
    ListingRepo(db).save_revision(
        conv_id,
        stamped,
        source="model_refinement",
        parent_revision_id=parent_id,
    )
    _sync_category_override(db, conv_id, stamped)
    return stamped


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
    comps_text = ""
    if photos and len(history) <= 2:
        provider = get_listing_provider()
        if provider:
            paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
            result = await provider.analyze_photos(paths, notes="", listing_rules=skill_rules[:8000])
            evidence = result.get("evidence", {}) or {}

            if evidence:
                analysis_note = format_photo_analysis(evidence).replace("Photo analysis:\n", "Photo analysis of the uploaded product images:\n", 1)
                repo.add_message(conv_id, "system", "Photo analysis complete:\n" + analysis_note)
                photo_analysis_text = "\n\n" + analysis_note
            else:
                photo_analysis_text = f"\n\nThe user uploaded {len(photos)} product photos. Use the list-this workflow to generate a listing based on contextual understanding."
            comps_text = await research_sold_comps(photo_analysis_text, evidence)
            if comps_text:
                repo.add_message(conv_id, "system", comps_text, provider="brave", model="web-search")

    comps_block = f"\n\n--- Sold comps ---\n\n{comps_text}\n" if comps_text else ""

    system_prompt = {
        "role": "system",
        "content": (
            "You are a product listing assistant talking to a seller. Write in plain English.\n"
            "Never reply with JSON-only output, status objects, or a bare JSON Patch array.\n\n"
            "When the user asks you to change an existing listing:\n"
            "1. Write a short confirmation of what you changed (department, category, marketplace fields).\n"
            "2. Then include a JSON Patch array in a fenced json code block so the listing can be saved. "
            "The seller will not see that block.\n"
            'Example confirmation: "This is a men\'s T-shirt. I moved it to Men > Men\'s Clothing > Shirts > T-Shirts."\n'
            "Example patch:\n"
            "```json\n"
            '[{"op": "replace", "path": "/department", "value": "Men"},'
            f'{{"op": "replace", "path": "/category_path", "value": "{MEN_TSHIRT_PATH}"}},'
            '{"op": "replace", "path": "/ebay_specifics/department", "value": "Men"}]\n'
            "```\n\n"
            "When generating a complete listing from scratch, write one sentence that the listing is ready, "
            "then the full listing JSON in a fenced json code block.\n\n"
            "If you are not changing the listing, reply in plain English only. "
            "If asked whether the listing was updated, say yes or no in a sentence after checking the latest listing JSON in this conversation.\n\n"
            "Key rules:\n"
            "- Never publish. Stop at saved drafts.\n"
            "- Be conservative with brand and size. Ask when uncertain instead of guessing.\n"
            f"- General Vendoo category paths must use Vendoo taxonomy: women's shirts and T-shirts end at {WOMEN_TOPS_PATH}, never Shirts & Blouses. Men's T-shirts use {MEN_TSHIRT_PATH}.\n"
            "- Follow the title and description formulas EXACTLY from the rules below.\n"
            "- Always fill ALL eBay specifics when generating a complete listing.\n"
            "- Depop: exactly 3 style tags from the allowed values list.\n"
            + (f"\n{photo_analysis_text}\n\n" if photo_analysis_text else "") +
            comps_block +
            f"\n--- Listing Rules ---\n\n{skill_rules}"
            if skill_rules
            else ""
        ) + _current_listing_prompt(db, conv_id) + _learned_fields_prompt(db, conv_id),
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
    from vendoo_studio.services.fill_log import extract_missing_fields, write_values_into_listing

    missing_fields = extract_missing_fields(full_text)
    if missing_fields:
        lr = ListingRepo(db)
        revisions = lr.get_revisions(conv_id)
        if revisions:
            updated = write_values_into_listing(dict(revisions[0].listing_json), missing_fields)
            _save_listing_revision(db, conv_id, updated)
            ConversationRepo(db).add_message(
                conv_id,
                "system",
                "Filled leftover marketplace fields and saved them to the listing.",
                provider="system",
                model="",
            )
            return

    parsed_ops = extract_json_patch(full_text)
    if parsed_ops:
        lr = ListingRepo(db)
        revisions = lr.get_revisions(conv_id)
        if not revisions:
            return
        updated = apply_json_patch(dict(revisions[0].listing_json), parsed_ops)
        _save_listing_revision(db, conv_id, updated, operations=parsed_ops)
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            "Saved those changes to the listing.",
            provider="system",
            model="",
        )
        return

    parsed = extract_listing_json(full_text)
    if parsed:
        _save_listing_revision(db, conv_id, parsed)
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            "Listing generated. Review the fields on the right.",
            provider="system",
            model="",
        )


@router.post("/api/conversations/{conv_id}/messages")
async def send_message(conv_id: str, body: ChatMessage, db: Session = Depends(get_db)):
    repo = ConversationRepo(db)
    conv = repo.get(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    provider = _require_provider()
    provider_name, provider_model = _provider_meta(provider)

    repo.update_status(conv_id, "in_progress")
    repo.add_message(conv_id, "user", body.text)

    messages = await _build_messages(conv_id, db, body.text)

    async def stream_response():
        stream_db = SessionLocal()
        full_text = ""
        try:
            async for item in _iter_with_keepalives(provider.chat(messages, stream=True)):
                if item is None:
                    yield KEEPALIVE
                    continue
                payload, content = _sse_for_stream_item(item)
                if content:
                    full_text += content
                if payload:
                    yield payload
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.exception("chat stream failed for %s", conv_id)
            yield _sse_data(f"Error: {e}")
            yield "data: [DONE]\n\n"

        stream_repo = ConversationRepo(stream_db)
        try:
            if full_text and not full_text.lstrip().lower().startswith("error:"):
                stream_repo.add_message(conv_id, "assistant", full_text, provider=provider_name, model=provider_model)
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

    provider = _require_provider()
    vision_name, vision_model = _vision_meta(provider)

    photos = repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "No photos to analyze")

    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]

    result = await provider.analyze_photos(paths, notes=conv.notes or "")

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

    photos = repo.get_photos(conv_id)
    if not photos:
        raise HTTPException(400, "No photos to generate from. Upload product photos first.")

    repo.update_status(conv_id, "in_progress")
    skill_rules = _load_skill_rules()
    notes = conv.notes or ""
    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]

    async def stream_response():
        yield _sse_event("status", "Analyzing photos…")
        yield KEEPALIVE
        stream_db = SessionLocal()
        stream_repo = ConversationRepo(stream_db)
        full_text = ""
        try:
            evidence: dict = {}
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
                stream_repo.add_message(conv_id, "system", analysis_text, provider=vision_name, model=vision_model)

            comps_text = ""
            if comps_search_available():
                yield _sse_event("status", "Looking up sold comps…")
                comps_task = asyncio.create_task(research_sold_comps(analysis_text, evidence))
                while not comps_task.done():
                    yield KEEPALIVE
                    try:
                        await asyncio.wait_for(asyncio.shield(comps_task), timeout=10)
                    except asyncio.TimeoutError:
                        continue
                comps_text = comps_task.result()
                if comps_text:
                    source = "chatgpt" if "Source: ChatGPT" in comps_text else "brave"
                    stream_repo.add_message(conv_id, "system", comps_text, provider=source, model="web-search")

            item_details = seller_item_details(notes)
            messages = _listing_messages(skill_rules, item_details, analysis_text, stream_db, conv_id, comps_text)
            yield _sse_event("status", "thinking")

            async for item in _iter_with_keepalives(provider.chat(messages, stream=True)):
                if item is None:
                    yield KEEPALIVE
                    continue
                payload, content = _sse_for_stream_item(item)
                if content:
                    full_text += content
                if payload:
                    yield payload

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


def _listing_messages(
    skill_rules: str,
    item_details: str,
    analysis_text: str,
    db: Session,
    conv_id: str,
    comps_text: str = "",
) -> list[dict]:
    comps_block = f"\n\n--- Sold comps ---\n\n{comps_text}" if comps_text else ""
    system_content = (
        "You are a product listing generator. Generate a COMPLETE, ready-to-use Vendoo listing JSON "
        "from the photo analysis and listing rules below.\n\n"
        "Use Vendoo's General taxonomy for category_path. Women's shirts and T-shirts must use "
        f'"{WOMEN_TOPS_PATH}", not "Shirts & Blouses". Men\'s T-shirts must use "{MEN_TSHIRT_PATH}".\n\n'
        "Always include sku (BRAND-SIZE slug, e.g. DISNEY-PARKS-M), primaryColor, and secondaryColor "
        "when a second color is visible. Use Vendoo general condition values such as "
        '"Pre-Owned - Good". Keep tags to 5 or fewer. Depop needs source and age. '
        "Mercari shippingLabel must be USPS Ground Advantage.\n\n"
        "If seller-provided measurements (Pit to pit, Length, Sleeve) are given, use them exactly as-is in the description.\n"
        "Do not modify, estimate, or replace seller-provided measurements.\n"
        "Price from the sold comps block when it is present: market price × 1.35, whole dollars. "
        "If comps are missing or thin, use a conservative baseline and flag uncertainty.\n\n"
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
        f"{analysis_text}"
        f"{comps_block}\n\n"
        f"--- Listing Rules ---\n\n{skill_rules}"
        f"{_learned_fields_prompt(db, conv_id)}"
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "Generate a complete listing from these product photos."},
    ]
