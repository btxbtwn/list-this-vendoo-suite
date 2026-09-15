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
    "- Title order is Brand Size Vibe Item Color Fit (max 80 chars) when those fields exist.\n"
    "- Description must keep Size:/Condition:/Measurements: line structure when present.\n"
    "- Do not rewrite formula-compliant title/description into freeform marketing copy.\n"
    "- Do not add commentary outside the JSON fence."
)

FINALIZE_GAPS_PROMPT = (
    "Finish this Vendoo listing so it can be sent. Infer only from the supplied photo analysis, "
    "seller notes, and current listing JSON. Do not ask questions.\n\n"
    "Return ONE fenced ```json block with the full updated listing object.\n"
    "Fix every listed validation error you can support from evidence.\n"
    "TITLE and DESCRIPTION follow list-this skill formulas exactly:\n"
    "- Title order: Brand Size Vibe Item Color Fit (max 80 chars).\n"
    "- Physical description: vibe sentence, fit/fabric sentence, then Size:, Condition:, "
    "Measurements:, OFFERS WELCOME, and the 15% off line — with blank lines between blocks.\n"
    "Preserve the current title and description unless a listed validation error is for title or "
    "description. Never replace a formula-compliant title/description with freeform marketing copy.\n"
    "Use exact Depop/Etsy/eBay dropdown values. Keep category_path and marketplace_categories unchanged.\n\n"
    "{formulas}"
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


def _first_sentence(text: str, fallback: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if not cleaned:
        return fallback
    match = re.search(r"(.+?[.!?])(?:\s|$)", cleaned)
    sentence = (match.group(1) if match else cleaned).strip()
    if not sentence.endswith((".", "!", "?")):
        sentence += "."
    return sentence


def ensure_physical_description(listing: dict) -> bool:
    """Rewrite description into the Size/Condition/Measurements formula when markers are missing."""
    from vendoo_studio.models.validation import _description_follows_formula, _is_etsy_digital_listing

    if not isinstance(listing, dict):
        return False
    if _is_etsy_digital_listing(listing):
        return False
    desc = str(listing.get("description") or "").strip()
    if not desc or _description_follows_formula(desc):
        return False

    size = str(listing.get("size") or "").strip() or "See tag"
    condition = str(listing.get("condition") or "").strip() or "Pre-Owned - Good"
    meas = "See photos"
    meas_match = re.search(r"(?is)measurements?:\s*(.+?)(?:\n\n|\n[A-Z]|$)", desc)
    if meas_match:
        meas = re.sub(r"\s+", " ", meas_match.group(1)).strip().rstrip(".")
    else:
        bits = re.findall(
            r"(?i)(?:pit\s*to\s*pit|length|sleeve)\s*[:=]?\s*[\d.\/\"]+\s*(?:inches|in|\"|”)?",
            desc,
        )
        if bits:
            meas = "; ".join(re.sub(r"\s+", " ", bit).strip() for bit in bits)

    lower = desc.lower()
    # Prefer appending missing required blocks so existing vibe/fit prose stays intact.
    if "\n" in desc and len(desc) >= 40:
        additions: list[str] = []
        if "size:" not in lower:
            additions.append(f"Size: {size}")
        if "condition:" not in lower:
            additions.append(f"Condition: {condition}; Flaws: none noted. See photos for details.")
        if "measurements:" not in lower:
            additions.append(f"Measurements: {meas}")
        if "offers welcome" not in lower:
            additions.append("OFFERS WELCOME! Ships in 1-2 business days.")
        if "15% off bundles" not in lower:
            additions.append("15% off bundles of 2+ items.")
        if additions:
            listing["description"] = desc.rstrip() + "\n\n" + "\n\n".join(additions)
            return True

    title = str(listing.get("title") or "").strip()
    vibe = _first_sentence(desc, fallback=f"{title}." if title else "Resale-ready garment.")
    rest = re.split(r"(?<=[.!?])\s+", desc, maxsplit=1)
    fit = _first_sentence(
        rest[1] if len(rest) > 1 else "",
        fallback="See photos for fit, fabric, and details.",
    )
    if fit.casefold() == vibe.casefold():
        fit = "See photos for fit, fabric, and details."
    listing["description"] = (
        f"{vibe}\n\n"
        f"{fit}\n\n"
        f"Size: {size}\n\n"
        f"Condition: {condition}; Flaws: none noted. See photos for details.\n\n"
        f"Measurements: {meas}\n\n"
        "OFFERS WELCOME! Ships in 1-2 business days.\n\n"
        "15% off bundles of 2+ items."
    )
    return True


_SIZE_APPROX_PREFIX_RE = re.compile(
    r"^(?:approx(?:imately)?\.?|about|around|est\.?|estimated|~)\s*:?\s*",
    re.I,
)
_SIZE_SPECIFIC_KEYS = (
    "ebay_specifics",
    "poshmark_specifics",
    "mercari_specifics",
    "depop_specifics",
    "etsy_specifics",
)


def sanitize_size_value(raw: Any) -> str:
    """Strip estimate qualifiers so size is a marketplace dropdown value."""
    text = str(raw or "").strip()
    if not text:
        return ""
    cleaned = _SIZE_APPROX_PREFIX_RE.sub("", text).strip()
    return cleaned or text


def sanitize_listing_sizes(listing: dict) -> bool:
    """Normalize size fields to clean marketplace values (no 'approx 10')."""
    if not isinstance(listing, dict):
        return False
    changed = False
    size = sanitize_size_value(listing.get("size"))
    if size and size != str(listing.get("size") or "").strip():
        listing["size"] = size
        changed = True
    for key in ("size_us", "sizeUs"):
        if key not in listing:
            continue
        cleaned = sanitize_size_value(listing.get(key))
        if cleaned and cleaned != str(listing.get(key) or "").strip():
            listing[key] = cleaned
            changed = True
    for specifics_key in _SIZE_SPECIFIC_KEYS:
        block = listing.get(specifics_key)
        if not isinstance(block, dict) or "size" not in block:
            continue
        cleaned = sanitize_size_value(block.get("size"))
        if cleaned and cleaned != str(block.get("size") or "").strip():
            listing[specifics_key] = {**block, "size": cleaned}
            changed = True
    return changed


def propagate_general_size(listing: dict) -> bool:
    """Mirror general size into marketplace size slots Vendoo keeps in sync."""
    if not isinstance(listing, dict):
        return False
    size = sanitize_size_value(listing.get("size"))
    if not size:
        return False
    if str(listing.get("size") or "").strip() != size:
        listing["size"] = size
    changed = False
    for specifics_key in _SIZE_SPECIFIC_KEYS:
        block = listing.get(specifics_key)
        if not isinstance(block, dict):
            continue
        if specifics_key != "ebay_specifics" and "size" not in block:
            continue
        if str(block.get("size") or "").strip() == size:
            continue
        listing[specifics_key] = {**block, "size": size}
        changed = True
    return changed


def apply_send_readiness_fixes(listing: dict) -> bool:
    """Deterministic fixes so generated listings clear common Send blockers."""
    from vendoo_studio.models.validation import normalize_listing_dropdowns

    if not isinstance(listing, dict):
        return False
    changed = normalize_listing_dropdowns(listing)
    if sanitize_listing_sizes(listing):
        changed = True
    if ensure_physical_description(listing):
        changed = True
    if not str(listing.get("package_dimensions_in") or "").strip():
        listing["package_dimensions_in"] = "13x10x3"
        changed = True
    if "weight_lb" not in listing and "weight_oz" not in listing:
        listing["weight_lb"] = 0
        listing["weight_oz"] = 10
        changed = True
    return changed


def _validation_blockers(listing: dict) -> list[dict]:
    from vendoo_studio.models.validation import validate_listing
    from vendoo_studio.services.marketplaces import get_selected_marketplaces

    result = validate_listing(
        listing,
        require_photos=False,
        selected_marketplaces=get_selected_marketplaces(),
    )
    return list(result.errors or [])


async def fill_validation_gaps(provider, listing: dict, *, analysis: str = "", notes: str = "") -> dict | None:
    """One model pass to clear remaining Send validation errors."""
    if provider is None or not isinstance(listing, dict):
        return None
    blockers = _validation_blockers(listing)
    if not blockers:
        return None
    from vendoo_studio.services.skill_formulas import listing_formula_rules

    payload = {
        "validation_errors": blockers,
        "photo_analysis": (analysis or "")[:8000],
        "seller_notes": (notes or "")[:4000],
        "listing": listing,
    }
    messages = [
        {
            "role": "system",
            "content": FINALIZE_GAPS_PROMPT.format(formulas=listing_formula_rules()),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:MAX_REPAIR_CHARS]},
    ]
    try:
        text = await collect_provider_text(provider, messages)
    except Exception:
        log.exception("listing validation-gap fill failed")
        return None
    updated = extract_listing_json(text)
    if not isinstance(updated, dict):
        return None
    return _preserve_formula_copy(listing, updated, blockers)


def _preserve_formula_copy(original: dict, updated: dict, blockers: list[dict]) -> dict:
    """Keep formula-compliant title/description unless those fields were the blockers."""
    from vendoo_studio.models.validation import _description_follows_formula, _title_follows_formula

    fields = {str(err.get("field") or "") for err in blockers or []}
    out = dict(updated)
    brand = str(original.get("brand") or out.get("brand") or "").strip()
    size = str(original.get("size") or out.get("size") or "").strip()
    orig_title = str(original.get("title") or "").strip()
    new_title = str(out.get("title") or "").strip()
    if "title" not in fields and orig_title:
        if _title_follows_formula(orig_title, brand, size) or not new_title:
            out["title"] = orig_title
        elif brand and new_title and not _title_follows_formula(new_title, brand, size):
            out["title"] = orig_title
    orig_desc = str(original.get("description") or "").strip()
    new_desc = str(out.get("description") or "").strip()
    if "description" not in fields and orig_desc:
        if _description_follows_formula(orig_desc) or not new_desc:
            out["description"] = orig_desc
        elif new_desc and not _description_follows_formula(new_desc):
            out["description"] = orig_desc
    return out


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


def listing_save_summary(
    db, conv_id: str, listing: dict, *, waiting: bool = False, repaired: bool = False
) -> str:
    """Honest post-save status based on validation and discovered field gaps."""
    from vendoo_studio.models.validation import validate_listing
    from vendoo_studio.services.listing_field_gaps import remaining_discovered_gap_count
    from vendoo_studio.services.marketplaces import get_selected_marketplaces

    photos = len(ConversationRepo(db).get_photos(conv_id))
    validation = validate_listing(
        listing,
        photos,
        require_photos=False,
        selected_marketplaces=get_selected_marketplaces(),
    )
    missing = len(validation.errors)
    discovered = remaining_discovered_gap_count(db, listing)
    lead = "Listing repaired and saved" if repaired else "Listing saved"
    if waiting:
        if missing or discovered:
            parts = []
            if missing:
                parts.append(f"{missing} required field(s) still missing in Studio")
            if discovered:
                parts.append(f"{discovered} discovered field(s) still empty in Studio")
            return (
                f"{lead} with questions outstanding. "
                + " — ".join(parts)
                + ". Finish them in Fields before Send."
            )
        return f"{lead} with questions outstanding. Answer them in chat before Send."
    if missing or discovered:
        parts = []
        if missing:
            parts.append(f"{missing} required field(s) still missing in Studio")
        if discovered:
            parts.append(f"{discovered} discovered field(s) still empty in Studio")
        return (
            f"{lead}. "
            + " — ".join(parts)
            + ". Open Fields to review what still needs chat, then Send when ready."
        )
    if repaired:
        return (
            "Listing repaired. Required and discovered Studio fields are filled — values are applied on Vendoo "
            "automatically when Chrome is connected. Review Fields, then Send when the draft looks right."
        )
    return (
        "Listing saved. Required and discovered Studio fields are filled — values are applied on Vendoo "
        "automatically when Chrome is connected. Review Fields, then Send when the draft looks right."
    )


def _ready_note(*, repaired: bool, finalized: bool, blockers: list) -> str:
    blocker_text = "; ".join(
        str(err.get("message") or err.get("field") or "issue") for err in (blockers or [])[:6]
    )
    if blockers:
        lead = "Listing repaired after a readiness pass" if repaired else "Listing extracted after a readiness pass"
        return f"{lead}. Remaining send blockers: {blocker_text}. Still ready for review."
    if repaired and finalized:
        return "Listing repaired and required fields filled. Ready for review."
    if finalized:
        return "Listing extracted and required fields filled. Ready for review."
    if repaired:
        return "Listing repaired from malformed model output and ready for review."
    return "Listing extracted and ready for review."


def persist_generated_listing(
    db,
    conv_id: str,
    full_text: str,
    *,
    source: str = "model",
    parsed: dict | None = None,
    repaired: bool = False,
    provider_name: str = "xiaomi-mimo",
    model_name: str = "mimo-v2.5-pro",
    announce: bool = True,
) -> dict | None:
    repo = ConversationRepo(db)
    if full_text:
        repo.add_message(conv_id, "assistant", full_text, provider=provider_name, model=model_name)

    listing = parsed if isinstance(parsed, dict) else extract_listing_json(full_text)
    if not listing:
        log.warning("listing generation produced no JSON for %s", conv_id)
        return None

    RegistryService(db).merge_learned_fields(listing)
    apply_send_readiness_fixes(listing)
    revisions = ListingRepo(db).get_revisions(conv_id)
    if revisions:
        selected = revisions[0].listing_json
        if selected.get("marketplace_categories"):
            listing["category_path"] = selected["category_path"]
            listing["marketplace_categories"] = dict(selected["marketplace_categories"])
    ListingRepo(db).save_revision(conv_id, listing, source=source)

    if announce:
        repo.add_message(
            conv_id,
            "system",
            _ready_note(repaired=repaired, finalized=False, blockers=_validation_blockers(listing)),
            provider="system",
            model="",
        )
    return listing


async def persist_generated_listing_with_repair(
    db,
    conv_id: str,
    full_text: str,
    provider,
    *,
    source: str = "model",
    final_announce: bool = True,
) -> dict | None:
    """Persist listing JSON, repairing parse errors and clearing Send validation gaps."""
    provider_name = getattr(provider, "name", "xiaomi-mimo")
    model_name = getattr(provider, "listing_model", "mimo-v2.5-pro")
    parsed = extract_listing_json(full_text)
    repaired = False
    if not parsed:
        repaired_json = await repair_listing_json(provider, full_text)
        if repaired_json:
            log.info("repaired malformed listing JSON for %s", conv_id)
            parsed = repaired_json
            repaired = True

    listing = persist_generated_listing(
        db,
        conv_id,
        full_text,
        source=source,
        parsed=parsed,
        repaired=repaired,
        provider_name=provider_name,
        model_name=model_name,
        announce=False,
    )
    if not listing:
        return None

    conv = ConversationRepo(db).get(conv_id)
    analysis = latest_photo_analysis(ConversationRepo(db).get_messages(conv_id)) or ""
    notes = str(getattr(conv, "notes", "") or "")
    finalized = False
    if _validation_blockers(listing):
        updated = await fill_validation_gaps(provider, listing, analysis=analysis, notes=notes)
        if isinstance(updated, dict) and updated:
            if listing.get("category_path"):
                updated["category_path"] = listing["category_path"]
            if listing.get("marketplace_categories"):
                updated["marketplace_categories"] = dict(listing["marketplace_categories"])
            RegistryService(db).merge_learned_fields(updated)
            apply_send_readiness_fixes(updated)
            listing = updated
            ListingRepo(db).save_revision(conv_id, listing, source="generation_finalize")
            finalized = True

    if final_announce:
        ConversationRepo(db).add_message(
            conv_id,
            "system",
            _ready_note(repaired=repaired, finalized=finalized, blockers=_validation_blockers(listing)),
            provider="system",
            model="",
        )
    return listing
