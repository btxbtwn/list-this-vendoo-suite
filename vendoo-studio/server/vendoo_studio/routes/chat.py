from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vendoo_studio.database import get_db
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services.keychain import get_api_key
from vendoo_studio.providers.xiaomi_mimo import MiMoProvider

router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    text: str


SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "skills"


def _load_skill_rules() -> str:
    skill_md = SKILLS_DIR / "list-this" / "SKILL.md"
    template_md = SKILLS_DIR / "list-this" / "references" / "vendoo_listing_template.md"

    parts = []
    if skill_md.exists():
        parts.append(skill_md.read_text())
    if template_md.exists():
        parts.append(template_md.read_text())

    return "\n\n---\n\n".join(parts) if parts else ""


async def _build_messages(conv_id: str, db: Session, user_message: str) -> list[dict]:
    repo = ConversationRepo(db)
    history = repo.get_messages(conv_id)
    photos = repo.get_photos(conv_id)

    skill_rules = _load_skill_rules()

    photo_analysis_text = ""
    if photos and len(history) <= 2:
        from vendoo_studio.config import PHOTOS_DIR
        from vendoo_studio.services.keychain import get_api_key as _key
        from vendoo_studio.providers.xiaomi_mimo import MiMoProvider

        key = _key()
        if key:
            paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
            provider = MiMoProvider(api_key=key)
            result = await provider.analyze_photos(paths, notes="", listing_rules=skill_rules[:8000])
            evidence = result.get("evidence", {}) or {}

            if evidence:
                parts = ["Photo analysis of the uploaded product images:\n"]
                brand = evidence.get("brand") if isinstance(evidence.get("brand"), dict) else None
                size = evidence.get("size") if isinstance(evidence.get("size"), dict) else None
                color = evidence.get("color") if isinstance(evidence.get("color"), dict) else None
                material = evidence.get("material") if isinstance(evidence.get("material"), dict) else None
                style = evidence.get("style") if isinstance(evidence.get("style"), dict) else None
                condition = evidence.get("condition") if isinstance(evidence.get("condition"), dict) else None
                measurements = evidence.get("measurements") or []
                uncertainties = evidence.get("uncertainties") or []

                if brand:
                    val = brand.get("value", "")
                    parts.append(f"- Brand: {val}" if val else "- Brand: unclear from photos")
                if size:
                    src = size.get("source", "tag")
                    parts.append(f"- Size: {size.get('value', '')} (source: {src})")
                if color:
                    parts.append(f"- Color: {color.get('value', '')}")
                if material:
                    parts.append(f"- Material: {material.get('value', '')}")
                if style:
                    parts.append(f"- Style: {style.get('value', '')}")
                if condition:
                    parts.append(f"- Condition: {condition.get('value', '')}")
                    flaws = condition.get("visibleFlaws", [])
                    if flaws:
                        parts.append(f"- Visible flaws: {', '.join(flaws)}")
                if measurements:
                    for m in measurements:
                        if isinstance(m, dict):
                            parts.append(f"- {m.get('label', '')}: {m.get('value', '')}")
                if uncertainties:
                    parts.append("- Uncertainties: " + ", ".join(
                        u.get("field", u.get("issue", "")) if isinstance(u, dict) else str(u)
                        for u in uncertainties
                    ))

                analysis_note = "\n".join(parts)
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
        ),
    }

    messages = [system_prompt]
    for msg in history[-20:]:
        role = msg.role
        if role == "model":
            role = "assistant"
        messages.append({"role": role, "content": msg.text})

    messages.append({"role": "user", "content": user_message})
    return messages


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
        full_text = ""
        try:
            async for chunk in provider.chat(messages, stream=True):
                full_text += chunk
                yield f"data: {_sse_encode(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {_sse_encode(f'Error: {str(e)}')}\n\n"
            yield "data: [DONE]\n\n"

        if full_text and "error" not in full_text.lower()[:50]:
            repo.add_message(conv_id, "assistant", full_text, provider="xiaomi-mimo", model="mimo-v2.5-pro")

            import json as _json
            try:
                text = full_text.strip()
                if text.startswith("```"):
                    import re as _re
                    match = _re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
                    if match:
                        text = match.group(1).strip()
                parsed = _json.loads(text)

                if isinstance(parsed, list) and all(isinstance(op, dict) and op.get("op") for op in parsed):
                    from vendoo_studio.repositories.queries import ListingRepo
                    lr = ListingRepo(db)
                    revisions = lr.get_revisions(conv_id)
                    if revisions:
                        import copy
                        updated = copy.deepcopy(dict(revisions[0].listing_json))
                        for op in parsed:
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
                        lr.save_revision(conv_id, updated, source="model_refinement",
                                         parent_revision_id=revisions[0].id)
                        repo.add_message(conv_id, "system",
                                         "Listing updated automatically from refinement.",
                                         provider="system", model="")
                elif isinstance(parsed, dict) and parsed.get("title"):
                    from vendoo_studio.repositories.queries import ListingRepo
                    lr = ListingRepo(db)
                    revisions = lr.get_revisions(conv_id)
                    parent_id = revisions[0].id if revisions else None
                    lr.save_revision(conv_id, parsed, source="model_refinement",
                                     parent_revision_id=parent_id)
                    repo.add_message(conv_id, "system",
                                     "Listing updated automatically from refinement.",
                                     provider="system", model="")
            except Exception:
                pass

        repo.update_status(conv_id, "draft")

    return StreamingResponse(stream_response(), media_type="text/event-stream")


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

    from vendoo_studio.config import PHOTOS_DIR
    from pathlib import Path

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

    from vendoo_studio.config import PHOTOS_DIR

    paths = [str(Path(PHOTOS_DIR) / p.stored_filename) for p in photos]
    provider = MiMoProvider(api_key=key)

    analysis_text = ""
    try:
        result = await provider.analyze_photos(paths, notes=conv.notes or "", listing_rules=skill_rules[:8000])
        evidence = result.get("evidence", {}) or {}

        parts = ["Photo analysis:\n"]
        for field_key in ("brand", "size", "color", "material", "style", "condition"):
            fd = evidence.get(field_key)
            if isinstance(fd, dict) and fd.get("value"):
                extra = f" (source: {fd.get('source', 'tag')})" if fd.get("source") else ""
                parts.append(f"- {field_key}: {fd['value']}{extra}")
        flaws = evidence.get("condition", {}).get("visibleFlaws", []) if isinstance(evidence.get("condition"), dict) else []
        if flaws:
            parts.append(f"- flaws: {', '.join(flaws)}")
        measurements = evidence.get("measurements") or []
        for m in measurements:
            if isinstance(m, dict):
                parts.append(f"- {m.get('label', '')}: {m.get('value', '')}")
        uncertainties = evidence.get("uncertainties") or []
        if uncertainties:
            parts.append("- uncertainties: " + ", ".join(
                u.get("field", str(u)) if isinstance(u, dict) else str(u) for u in uncertainties
            ))
        analysis_text = "\n".join(parts)
    except Exception as e:
        analysis_text = f"Photo analysis unavailable ({e}). Use contextual knowledge."

    repo.add_message(conv_id, "system", analysis_text, provider="xiaomi-mimo", model="mimo-v2.5")

    import json as _json

    item_details = ""
    try:
        parsed = _json.loads(conv.notes or "{}")
        if isinstance(parsed, dict):
            lines = []
            if parsed.get("condition"):
                lines.append(f"- Condition: {parsed['condition']}")
            if parsed.get("cog"):
                lines.append(f"- Cost of goods: ${parsed['cog']}")
            if parsed.get("packageDimensions"):
                lines.append(f"- Package dimensions: {parsed['packageDimensions']}")
            pit_to_pit = (parsed.get("pitToPit") or "").strip()
            length_val = (parsed.get("length") or "").strip()
            if pit_to_pit or length_val:
                parts = []
                if pit_to_pit:
                    parts.append(f'Pit to pit: {pit_to_pit}"')
                if length_val:
                    parts.append(f'Length: {length_val}"')
                lines.append("- Measurements: " + "; ".join(parts))
            if lines:
                item_details = "Known item details from the seller:\n" + "\n".join(lines)
    except _json.JSONDecodeError:
        if conv.notes:
            item_details = f"Seller notes: {conv.notes}"

    system_content = (
        "You are a product listing generator. Generate a COMPLETE, ready-to-use Vendoo listing JSON "
        "from the photo analysis and listing rules below.\n\n"
        "Use Vendoo's General taxonomy for category_path. Women's shirts and T-shirts must use "
        '"Clothing, Shoes & Accessories > Women > Women\'s Clothing > Tops", not "Shirts & Blouses".\n\n'
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
        '  "size": "...",\n'
        '  "sizeType": "...",\n'
        '  "tags": [...],\n'
        '  "package_dimensions_in": "...",\n'
        '  "ebay_specifics": {...},\n'
        '  "depop_specifics": {...},\n'
        '  "etsy_specifics": {...},\n'
        '  "poshmark_specifics": {"originalPrice": 0},\n'
        '  "mercari_specifics": {"shippingLabel": "USPS Ground Advantage"}\n'
        "}\n"
        "```\n\n"
        f"{item_details}\n\n"
        f"{analysis_text}\n\n"
        f"--- Listing Rules ---\n\n{skill_rules}"
    )

    messages = [{"role": "system", "content": system_content}]
    messages.append({"role": "user", "content": "Generate a complete listing from these product photos."})

    async def stream_response():
        full_text = ""
        try:
            async for chunk in provider.chat(messages, stream=True):
                full_text += chunk
                yield f"data: {_sse_encode(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {_sse_encode(f'Error: {str(e)}')}\n\n"
            yield "data: [DONE]\n\n"

        if full_text and "error" not in full_text.lower()[:50]:
            repo.add_message(conv_id, "assistant", full_text, provider="xiaomi-mimo", model="mimo-v2.5-pro")

            import json as _json
            import re as _re
            match = _re.search(r'```json\s*([\s\S]*?)```', full_text)
            if match:
                try:
                    parsed = _json.loads(match.group(1))
                    repo.add_message(conv_id, "system", "Listing extracted and ready for review.", provider="system", model="")
                    from vendoo_studio.repositories.queries import ListingRepo
                    lr = ListingRepo(db)
                    lr.save_revision(conv_id, parsed, source="model")
                except Exception:
                    pass

        repo.update_status(conv_id, "draft")

    return StreamingResponse(stream_response(), media_type="text/event-stream")


def _sse_encode(text: str) -> str:
    return text.replace("\n", "\ndata: ")
