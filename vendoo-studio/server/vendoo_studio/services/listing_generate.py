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
PHOTO_ANALYSIS_RETRY_MESSAGE = "Photo analysis failed. Retry to analyze the photos again."
_FIELD_LINE_RE = re.compile(r"^-\s*\w[\w\s]*:", re.M)


class PhotoAnalysisError(RuntimeError):
    pass


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


def require_photo_analysis(result: Any) -> tuple[dict, str]:
    """Return usable photo evidence or stop the listing flow for a retry."""
    if not isinstance(result, dict) or result.get("error"):
        raise PhotoAnalysisError(PHOTO_ANALYSIS_RETRY_MESSAGE)
    evidence = normalize_evidence(result.get("evidence", {}) or {})
    analysis_text = format_photo_analysis(evidence)
    if not photo_analysis_usable(analysis_text):
        raise PhotoAnalysisError(PHOTO_ANALYSIS_RETRY_MESSAGE)
    return evidence, analysis_text


def analysis_with_photo_count(photo_count: int, analysis_text: str | None = None) -> str:
    """Attach verified photo evidence to a listing prompt."""
    count = max(0, int(photo_count or 0))
    text = (analysis_text or "").strip()
    if not count:
        return text
    if not photo_analysis_usable(text):
        raise PhotoAnalysisError(PHOTO_ANALYSIS_RETRY_MESSAGE)
    header = (
        f"The seller already uploaded {count} product photo(s). "
        "Do not ask them to attach, upload, or resend photos.\n"
    )
    return header + "\n" + text


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


def looks_like_listing_attempt(text: str) -> bool:
    """True when assistant text looks like it tried to emit listing JSON."""
    if not text or text.lstrip().lower().startswith("error:"):
        return False
    if extract_listing_json(text):
        return True
    lowered = text.lower()
    if "```" in text and "{" in text:
        return True
    return "{" in text and ('"title"' in lowered or '"description"' in lowered or '"price"' in lowered)


REPAIR_LISTING_PROMPT = (
    "The previous assistant reply tried to produce a Vendoo listing JSON object but it was "
    "malformed or incomplete. Repair it into ONE valid JSON object only.\n\n"
    "Rules:\n"
    "- Output a single fenced ```json block with the listing object.\n"
    "- Keep every usable field from the broken output; fix syntax only.\n"
    "- Include title, description, and price when possible.\n"
    "- Do not add commentary outside the JSON fence."
)

MAX_REPAIR_CHARS = 14000


async def collect_provider_text(provider, messages: list[dict]) -> str:
    from vendoo_studio.providers.xiaomi_mimo import unpack_stream_item

    parts: list[str] = []
    async for item in provider.chat(messages, stream=False):
        kind, text = unpack_stream_item(item)
        if kind == "content" and text:
            parts.append(text)
    return "".join(parts)


async def repair_listing_json(provider, raw_text: str) -> dict | None:
    """Ask the listing provider to repair malformed listing JSON. Returns parsed dict or None."""
    parsed = extract_listing_json(raw_text)
    if parsed:
        return parsed
    if provider is None or not looks_like_listing_attempt(raw_text):
        return None

    clipped = (raw_text or "").strip()
    if len(clipped) > MAX_REPAIR_CHARS:
        clipped = clipped[:MAX_REPAIR_CHARS]
    messages = [
        {"role": "system", "content": REPAIR_LISTING_PROMPT},
        {"role": "user", "content": clipped},
    ]
    try:
        repaired = await collect_provider_text(provider, messages)
    except Exception:
        log.exception("listing JSON repair request failed")
        return None
    return extract_listing_json(repaired)


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


def persist_generated_listing(
    db,
    conv_id: str,
    full_text: str,
    *,
    source: str = "model",
    parsed: dict | None = None,
    repaired: bool = False,
) -> dict | None:
    repo = ConversationRepo(db)
    if full_text:
        repo.add_message(conv_id, "assistant", full_text, provider="xiaomi-mimo", model="mimo-v2.5-pro")

    listing = parsed if isinstance(parsed, dict) else extract_listing_json(full_text)
    if not listing:
        log.warning("listing generation produced no JSON for %s", conv_id)
        return None

    note = (
        "Listing repaired from malformed model output and ready for review."
        if repaired
        else "Listing extracted and ready for review."
    )
    repo.add_message(conv_id, "system", note, provider="system", model="")
    RegistryService(db).merge_learned_fields(listing)
    ListingRepo(db).save_revision(conv_id, listing, source=source)
    return listing


async def persist_generated_listing_with_repair(
    db,
    conv_id: str,
    full_text: str,
    provider,
    *,
    source: str = "model",
) -> dict | None:
    """Persist listing JSON, repairing with the provider when the first parse fails."""
    parsed = extract_listing_json(full_text)
    if parsed:
        return persist_generated_listing(db, conv_id, full_text, source=source, parsed=parsed)

    repaired = await repair_listing_json(provider, full_text)
    if repaired:
        log.info("repaired malformed listing JSON for %s", conv_id)
        return persist_generated_listing(
            db,
            conv_id,
            full_text,
            source=source,
            parsed=repaired,
            repaired=True,
        )
    return persist_generated_listing(db, conv_id, full_text, source=source)
