"""Answer every field a category renders before the item is created.

``fetch_listing_specifics`` already knows, for each marketplace leaf, exactly
which fields Vendoo's form would show and which values each one accepts. This
turns that into work for the model: every field the listing has not answered is
put to it with its allowed values, in rounds, until nothing is left to ask.

The request is built by ``listing_field_gaps`` — the same prompt the Apply/Send
filler uses — so a field asked here reads identically to one asked there. What
differs is the source: these gaps come from Vendoo's own schema rather than a
scraped sample, so they cover every marketplace we hold a schema for, not just
the five with learned forms.
"""
from __future__ import annotations

import logging
from typing import Any

from vendoo_studio.services.fill_log import listing_value_for_field, write_values_into_listing
from vendoo_studio.services.vendoo_specifics import FieldSpec

log = logging.getLogger("vendoo_studio.specifics_fill")

# Enough rounds to clear a big category without spinning if the model stalls.
MAX_ROUNDS = 6

__all__ = ["specifics_gaps", "fill_listing_specifics", "MAX_ROUNDS"]


def specifics_gaps(
    listing: dict[str, Any],
    specifics: dict[str, dict[str, FieldSpec]],
) -> list[dict[str, Any]]:
    """Every schema field this listing has not answered yet.

    Ordered required-first so that when a round is truncated it is the fields
    Vendoo insists on that make the cut.
    """
    if not isinstance(listing, dict):
        return []
    gaps: list[dict[str, Any]] = []
    for marketplace, fields in sorted((specifics or {}).items()):
        for spec in fields.values():
            label = spec.display or spec.key
            if not label:
                continue
            if listing_value_for_field(listing, marketplace, label):
                continue
            row: dict[str, Any] = {"marketplace": marketplace, "field": label}
            if spec.options:
                row["options"] = sorted(spec.options.values())
            if spec.required:
                row["required"] = True
            gaps.append(row)
    gaps.sort(key=lambda row: (not row.get("required"), row["marketplace"], row["field"]))
    return gaps


async def fill_listing_specifics(
    listing: dict[str, Any],
    specifics: dict[str, dict[str, FieldSpec]],
    provider,
    *,
    evidence: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fill every empty category field. Returns ``(listing, still_empty)``.

    Rounds stop early when the model returns nothing, so a field it cannot
    support from the evidence is reported rather than invented.
    """
    from vendoo_studio.services.listing_field_gaps import (
        MAX_GAPS_PER_ROUND,
        _request_missing_field_values,
    )

    current = dict(listing) if isinstance(listing, dict) else {}
    if provider is None or not specifics:
        return current, specifics_gaps(current, specifics)

    filled = 0
    for _ in range(MAX_ROUNDS):
        gaps = specifics_gaps(current, specifics)
        if not gaps:
            break
        patches = await _request_missing_field_values(
            provider,
            listing=current,
            gaps=gaps[:MAX_GAPS_PER_ROUND],
            evidence=evidence,
        )
        if not patches:
            break
        updated = write_values_into_listing(current, patches)
        if updated == current:
            # Nothing landed — asking the same question again would not help.
            break
        current = updated
        filled += len(patches)

    remaining = specifics_gaps(current, specifics)
    if filled or remaining:
        log.info("category fields: filled %s, %s still empty", filled, len(remaining))
    return current, remaining
