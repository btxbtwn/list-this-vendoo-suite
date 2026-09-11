from __future__ import annotations

import json
import logging
import re
from typing import Any

from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo

log = logging.getLogger("vendoo_studio.listing_generate")

PHOTO_ANALYSIS_PREFIXES = ("Photo analysis:", "Photo analysis of the uploaded product images:")


def latest_photo_analysis(messages: list[Any]) -> str | None:
    for msg in reversed(messages):
        text = (getattr(msg, "text", None) or "").strip()
        if getattr(msg, "role", None) == "system" and text.startswith(PHOTO_ANALYSIS_PREFIXES):
            return text
    return None


def format_photo_analysis(evidence: dict) -> str:
    parts = ["Photo analysis:\n"]
    for field_key in ("brand", "size", "color", "material", "style", "condition"):
        fd = evidence.get(field_key)
        if isinstance(fd, dict) and fd.get("value"):
            extra = f" (source: {fd.get('source', 'tag')})" if fd.get("source") else ""
            parts.append(f"- {field_key}: {fd['value']}{extra}")
    condition = evidence.get("condition")
    flaws = condition.get("visibleFlaws", []) if isinstance(condition, dict) else []
    if flaws:
        parts.append(f"- flaws: {', '.join(flaws)}")
    for measurement in evidence.get("measurements") or []:
        if isinstance(measurement, dict):
            parts.append(f"- {measurement.get('label', '')}: {measurement.get('value', '')}")
    uncertainties = evidence.get("uncertainties") or []
    if uncertainties:
        parts.append("- uncertainties: " + ", ".join(
            u.get("field", str(u)) if isinstance(u, dict) else str(u) for u in uncertainties
        ))
    return "\n".join(parts)


def extract_listing_json(text: str) -> dict | None:
    if not text or text.lstrip().lower().startswith("error:"):
        return None

    candidates: list[str] = []
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidates.append(match.group().strip())

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and (parsed.get("title") or parsed.get("description") or parsed.get("price") is not None):
            return parsed
    return None


def seller_item_details(notes: str | None) -> str:
    if not notes:
        return ""
    try:
        parsed = json.loads(notes)
    except json.JSONDecodeError:
        return f"Seller notes: {notes}"
    if not isinstance(parsed, dict):
        return f"Seller notes: {notes}"

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
    if not lines:
        return ""
    return "Known item details from the seller:\n" + "\n".join(lines)


def persist_generated_listing(db, conv_id: str, full_text: str, *, source: str = "model") -> dict | None:
    repo = ConversationRepo(db)
    if full_text:
        repo.add_message(conv_id, "assistant", full_text, provider="xiaomi-mimo", model="mimo-v2.5-pro")

    parsed = extract_listing_json(full_text)
    if not parsed:
        log.warning("listing generation produced no JSON for %s", conv_id)
        return None

    repo.add_message(conv_id, "system", "Listing extracted and ready for review.", provider="system", model="")
    ListingRepo(db).save_revision(conv_id, parsed, source=source)
    return parsed
