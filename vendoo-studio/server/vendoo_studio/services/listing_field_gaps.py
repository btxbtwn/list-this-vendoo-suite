"""Find and fill discovered marketplace fields still empty after generation."""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.models.catalog import CategorySchema
from vendoo_studio.services.category_fields import listing_category_ids, load_fields
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.fill_log import (
    MAX_PATCH_FIELDS,
    FillLogService,
    extract_missing_fields,
    field_lookup_key,
    listing_value_for_field,
    normalize_field_label,
    prompt_options,
    repair_missing_fields,
    summarize_missing_fields,
    write_values_into_listing,
)
from vendoo_studio.services.registry import (
    LEARNED_MARKETPLACES,
    ROOT_FIELD_LABELS,
    SELLER_SETTING_LABELS,
    RegistryService,
    is_account_managed_field,
    is_learned_listing_field,
)

log = logging.getLogger(__name__)

MAX_GAP_ROUNDS = 1
MAX_GAPS_PER_ROUND = 50

GAP_FILL_SYSTEM = (
    "You fill missing Vendoo listing fields from photo analysis and seller evidence. "
    "Return ONLY a fenced JSON block with this exact shape:\n"
    '{"missing_fields":[{"marketplace":"general","field":"SKU","value":"..."}]}\n\n'
    "Rules:\n"
    "- Fill ONLY the listed fields. Do not rewrite unrelated listing values.\n"
    "- Use marketplace ids and field names exactly as listed.\n"
    "- Use a real value from photo or seller evidence.\n"
    "- When allowed options are listed, copy one of them exactly, character for "
    "character. Those are the only values the field accepts.\n"
    "- When a field does not apply to the item, leave it out of your reply "
    "entirely. Do NOT answer \"Does Not Apply\" unless it appears in that "
    "field's allowed options — it is rejected everywhere else, and an omitted "
    "field is handled properly.\n"
    "- Fill every field that does pertain, on every marketplace.\n"
    "- Depop Parcel Size follows the packaged weight: under 4oz Extra extra "
    "small, under 8oz Extra small, under 12oz Small, under 1lb Medium, under "
    "2lb Large, otherwise Extra large.\n"
    "- Estimate packaged shipping weight and package dimensions from item type when asked.\n"
    "- Never invent brand, measurements, material, age, or origin without evidence.\n"
    "- Include every listed field that you can resolve; omit fields that need a seller question."
)


def collect_empty_discovered_fields(db: Session, listing: dict) -> list[dict[str, Any]]:
    """Discovered category/registry fields that are still empty in the listing JSON."""
    if not isinstance(listing, dict):
        return []

    category_path = str(listing.get("category_path") or "").strip()
    if not category_path:
        return []

    seen: set[tuple[str, str]] = set()
    gaps: list[dict[str, Any]] = []

    def consider(
        marketplace: str,
        field_label: str,
        *,
        options: list[str] | None = None,
        required: bool = False,
    ) -> None:
        marketplace = str(marketplace or "general").strip().lower()
        label = str(field_label or "").strip()
        if not label:
            return
        lookup = field_lookup_key(label)
        if lookup in SELLER_SETTING_LABELS:
            return
        if is_account_managed_field(marketplace, label):
            return
        if marketplace != "general":
            if lookup in ROOT_FIELD_LABELS:
                return
            if not is_learned_listing_field(marketplace, label):
                return
        elif lookup in {"photos", "images", "videos", "image"}:
            return

        key = (marketplace, normalize_field_label(label))
        if key in seen:
            return
        if listing_value_for_field(listing, marketplace, label):
            return
        seen.add(key)
        row: dict[str, Any] = {"marketplace": marketplace, "field": label}
        if options:
            row["options"] = options
        if required:
            row["required"] = True
        gaps.append(row)

    rows = db.query(CategorySchema).filter_by(general_path=category_path).all()
    for row in rows:
        marketplace = str(row.marketplace or "general").strip().lower()
        for field in row.fields or []:
            if not isinstance(field, dict):
                continue
            label = str(field.get("label") or field.get("key") or "").strip()
            if not label:
                continue
            raw_options = field.get("options")
            options = None
            if isinstance(raw_options, list):
                options = [
                    str(option.get("label") if isinstance(option, dict) else option).strip()
                    for option in raw_options
                    if str(option.get("label") if isinstance(option, dict) else option).strip()
                ]
            consider(
                marketplace,
                label,
                options=options,
                required=bool(field.get("required")),
            )

    # Vendoo's own per-category schema, where we have it: it names every field
    # the category renders, which of them it requires, and each coded option.
    # Unlike the scraped rows above it needs no browser and covers any leaf.
    for marketplace, category_id in listing_category_ids(listing).items():
        for spec in (load_fields(marketplace, category_id) or {}).values():
            consider(
                marketplace,
                spec.display or spec.key,
                options=sorted(spec.options.values()) or None,
                required=spec.required,
            )

    registry = RegistryService(db)
    for marketplace in LEARNED_MARKETPLACES:
        for entry in registry._repo.list_fields(marketplace, category_path):
            if not is_learned_listing_field(marketplace, entry.normalized_label):
                continue
            options = sorted(entry.known_options) if entry.known_options else None
            consider(marketplace, entry.normalized_label, options=options)

    gaps.sort(key=lambda item: (item["marketplace"], item["field"]))
    return gaps


def build_missing_fields_request(listing: dict, gaps: list[dict[str, Any]], evidence: str = "") -> str:
    title = str(listing.get("title") or "Untitled").strip() or "Untitled"
    context = " ".join([
        evidence or "",
        title,
        str(listing.get("description") or ""),
        str(listing.get("brand") or ""),
        str(listing.get("category_path") or ""),
    ])
    lines: list[str] = []
    for gap in gaps[:MAX_GAPS_PER_ROUND]:
        marketplace = gap["marketplace"]
        field = gap["field"]
        current = listing_value_for_field(listing, marketplace, field) or "(empty)"
        rejected = str(gap.get("rejected") or "").strip()
        status = (
            f"Vendoo rejected {rejected!r}; choose an allowed option"
            if rejected
            else "empty in listing JSON"
        )
        detail = (
            f"- Marketplace: {marketplace}\n"
            f"  Field: {field}\n"
            f"  Current value: {current}\n"
            f"  Status: {status}"
        )
        options, complete = prompt_options(gap.get("options"), context)
        if options:
            detail += f"\n  Allowed options: {'; '.join(options)}"
            if not complete:
                detail += "; … (closest matches shown)"
        lines.append(detail)

    return (
        f'These discovered fields are still empty in the listing JSON for "{title}". '
        "Generate values for ONLY these fields from the photos and current listing. "
        "Do not rewrite the rest of the listing.\n\n"
        "Reply with JSON in this exact shape:\n\n"
        '```json\n{"missing_fields":[{"marketplace":"general","field":"SKU","value":"..."}]}\n```\n\n'
        "Use the marketplace ids and field names exactly as listed.\n\n"
        f"Empty fields ({len(gaps[:MAX_GAPS_PER_ROUND])} shown):\n"
        + "\n".join(lines)
    )


async def _request_missing_field_values(
    provider,
    *,
    listing: dict,
    gaps: list[dict[str, Any]],
    evidence: str,
) -> list[dict] | None:
    from vendoo_studio.services.listing_generate import collect_provider_text, extract_listing_json

    request = build_missing_fields_request(listing, gaps, evidence)
    messages = [
        {"role": "system", "content": GAP_FILL_SYSTEM},
        {
            "role": "user",
            "content": (
                f"{request}\n\n--- Evidence ---\n{evidence}\n\n"
                f"--- Current listing ---\n{json.dumps(listing, ensure_ascii=False)}"
            ),
        },
    ]
    try:
        text = await collect_provider_text(provider, messages)
    except Exception:
        log.exception("discovered field gap fill request failed")
        return None

    patches = extract_missing_fields(text)
    if patches:
        return patches
    repaired = await repair_missing_fields(provider, text, request)
    if repaired:
        return repaired

    full_listing = extract_listing_json(text)
    if isinstance(full_listing, dict):
        merged = dict(listing)
        for key, value in full_listing.items():
            if key.endswith("_specifics") and isinstance(value, dict):
                current = dict(merged.get(key) or {})
                for sub_key, sub_value in value.items():
                    if sub_value not in (None, "", []):
                        current[sub_key] = sub_value
                merged[key] = current
            elif value not in (None, "", []):
                merged[key] = value
        round_patches: list[dict] = []
        for gap in gaps:
            value = listing_value_for_field(merged, gap["marketplace"], gap["field"])
            if value and not listing_value_for_field(listing, gap["marketplace"], gap["field"]):
                round_patches.append({
                    "marketplace": gap["marketplace"],
                    "field": gap["field"],
                    "value": value,
                })
        return round_patches or None
    return None


async def fill_listing_field_gaps(
    db: Session,
    conv_id: str,
    listing: dict,
    provider,
    *,
    evidence: str,
) -> dict:
    """Fill discovered empty fields with follow-up LLM rounds before Apply/Send."""
    if not isinstance(listing, dict) or provider is None:
        return listing

    repo = ConversationRepo(db)
    listing_repo = ListingRepo(db)
    fill_log = FillLogService(db)
    current = dict(listing)
    total_filled = 0

    for round_index in range(MAX_GAP_ROUNDS):
        RegistryService(db).merge_learned_fields(current)
        gaps = collect_empty_discovered_fields(db, current)
        if not gaps:
            break

        batch = gaps[:MAX_GAPS_PER_ROUND]
        patches = await _request_missing_field_values(
            provider,
            listing=current,
            gaps=batch,
            evidence=evidence,
        )
        if not patches:
            log.info(
                "discovered field gap fill stopped after round %s for %s (%s gaps remain)",
                round_index + 1,
                conv_id,
                len(gaps),
            )
            break

        updated = write_values_into_listing(current, patches[:MAX_PATCH_FIELDS])
        revisions = listing_repo.get_revisions(conv_id)
        listing_repo.save_revision(
            conv_id,
            updated,
            source="gap_fill",
            parent_revision_id=revisions[0].id if revisions else None,
        )
        fill_log.record_generated_values(conv_id, patches[:MAX_PATCH_FIELDS])
        repo.add_message(
            conv_id,
            "system",
            summarize_missing_fields(patches[:MAX_PATCH_FIELDS]),
            provider="system",
            model="",
        )
        current = updated
        total_filled += len(patches[:MAX_PATCH_FIELDS])

    if total_filled:
        log.info("filled %s discovered listing field(s) across gap rounds for %s", total_filled, conv_id)
    return current


def remaining_discovered_gap_count(db: Session, listing: dict) -> int:
    from copy import deepcopy

    probe = deepcopy(listing) if isinstance(listing, dict) else {}
    RegistryService(db).merge_learned_fields(probe)
    return len(collect_empty_discovered_fields(db, probe))
