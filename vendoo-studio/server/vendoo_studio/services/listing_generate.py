from __future__ import annotations

import json
import logging
import re
from typing import Any

from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.registry import RegistryService

log = logging.getLogger("vendoo_studio.listing_generate")

PHOTO_ANALYSIS_PREFIXES = ("Photo analysis:", "Photo analysis of the uploaded product images:")
_FIELD_LINE_RE = re.compile(r"^-\s*\w[\w\s]*:", re.M)


def _evidence_value(field: Any) -> str | None:
    if isinstance(field, dict):
        raw = field.get("value")
    else:
        raw = field
    text = str(raw or "").strip()
    return text or None


def normalize_evidence(payload: Any) -> dict:
    """Unwrap common vision JSON shapes into a flat evidence dict."""
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("evidence")
    if isinstance(nested, dict) and any(
        key in nested for key in ("brand", "size", "color", "material", "style", "category", "condition")
    ):
        return nested
    return payload


def photo_analysis_usable(text: str | None) -> bool:
    """True when analysis has at least one real field line (not just the header)."""
    stripped = (text or "").strip()
    if not stripped.startswith(PHOTO_ANALYSIS_PREFIXES):
        return False
    return bool(_FIELD_LINE_RE.search(stripped))


def latest_photo_analysis(messages: list[Any]) -> str | None:
    for msg in reversed(messages):
        text = (getattr(msg, "text", None) or "").strip()
        if getattr(msg, "role", None) == "system" and photo_analysis_usable(text):
            return text
    return None


def format_photo_analysis(evidence: dict) -> str:
    evidence = normalize_evidence(evidence)
    parts = ["Photo analysis:"]
    for field_key in ("brand", "size", "color", "material", "style", "category", "condition"):
        fd = evidence.get(field_key)
        value = _evidence_value(fd)
        if not value:
            continue
        extra = ""
        if isinstance(fd, dict) and fd.get("source"):
            extra = f" (source: {fd.get('source')})"
        parts.append(f"- {field_key}: {value}{extra}")
    condition = evidence.get("condition")
    flaws = condition.get("visibleFlaws", []) if isinstance(condition, dict) else []
    if flaws:
        parts.append(f"- flaws: {', '.join(str(f) for f in flaws if f)}")
    for measurement in evidence.get("measurements") or []:
        if isinstance(measurement, dict):
            label = str(measurement.get("label") or "").strip()
            value = str(measurement.get("value") or "").strip()
            if label and value:
                parts.append(f"- {label}: {value}")
    uncertainties = evidence.get("uncertainties") or []
    if uncertainties:
        parts.append("- uncertainties: " + ", ".join(
            u.get("field", str(u)) if isinstance(u, dict) else str(u) for u in uncertainties
        ))
    return "\n".join(parts)


def analysis_with_photo_count(photo_count: int, analysis_text: str | None = None) -> str:
    """Ensure listing prompts always acknowledge uploaded photos."""
    count = max(0, int(photo_count or 0))
    header = (
        f"The seller already uploaded {count} product photo(s). "
        "Do not ask them to attach, upload, or resend photos.\n"
    )
    text = (analysis_text or "").strip()
    if photo_analysis_usable(text):
        return header + "\n" + text
    if text.startswith(PHOTO_ANALYSIS_PREFIXES) or text.lower().startswith("photo analysis unavailable"):
        return (
            header
            + "\n"
            + text
            + "\n- note: structured vision fields were thin or unavailable; "
            "still generate a complete listing from seller details and these photos."
        )
    if count:
        return (
            header
            + "\nPhoto analysis:\n"
            + "- note: photos are present but structured vision fields were unavailable.\n"
            + "- instruction: generate a complete listing anyway; never ask for photos."
        )
    return text


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
    category = str(parsed.get("categoryOverride") or "").strip()
    if category:
        lines.append(f"- Category: {category}")
    labels = str(parsed.get("vendooLabels") or "").strip()
    if labels:
        lines.append(f"- Labels: {labels}")
    if parsed.get("cog"):
        lines.append(f"- Cost of goods: ${parsed['cog']}")
    if parsed.get("packageDimensions"):
        lines.append(f"- Package dimensions: {parsed['packageDimensions']}")
    pit_to_pit = (parsed.get("pitToPit") or "").strip()
    length_val = (parsed.get("length") or "").strip()
    sleeve_val = (parsed.get("sleeve") or "").strip()
    if pit_to_pit or length_val or sleeve_val:
        parts = []
        if pit_to_pit:
            parts.append(f'Pit to pit: {pit_to_pit}"')
        if length_val:
            parts.append(f'Length: {length_val}"')
        if sleeve_val:
            parts.append(f'Sleeve: {sleeve_val}"')
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
    if isinstance(parsed, dict):
        RegistryService(db).merge_learned_fields(parsed)
    ListingRepo(db).save_revision(conv_id, parsed, source=source)
    return parsed
