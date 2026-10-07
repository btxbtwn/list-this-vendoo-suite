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

import asyncio
import logging
import time
from typing import Any

from vendoo_studio.services.fill_log import listing_value_for_field, write_values_into_listing
from vendoo_studio.services.vendoo_specifics import (
    FieldSpec, encode_scaled, encode_specific, is_not_applicable,
)

log = logging.getLogger("vendoo_studio.specifics_fill")

# Enough rounds to clear a big category without spinning if the model stalls.
MAX_ROUNDS = 6
# The whole fill, not each round. Send and Update Vendoo wait on this step, and
# a model that stalls — Cursor can sit silent for minutes a call — held the
# send on "Filling marketplace fields" with no end. Past it, the listing goes
# to Vendoo with what landed and the rest is reported as still empty.
FILL_DEADLINE_SEC = 120.0

__all__ = ["specifics_gaps", "fill_listing_specifics", "MAX_ROUNDS", "FILL_DEADLINE_SEC"]


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
            value = listing_value_for_field(listing, marketplace, label, include_not_applicable=True)
            if marketplace == "ebay" and spec.key == "Size":
                from vendoo_studio.models.ebay_fields import ebay_size_for_type

                value = ebay_size_for_type(value, listing_value_for_field(listing, "ebay", "Size Type"))
            if not spec.required and is_not_applicable(value):
                continue
            if spec.scales:
                _, stored, resolved = encode_scaled(spec, value)
            else:
                stored, resolved = encode_specific(spec, value)
            if resolved and stored not in (None, "", [], {}):
                continue
            row: dict[str, Any] = {"marketplace": marketplace, "field": label}
            if value and not is_not_applicable(value):
                row["rejected"] = value
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
    support from the evidence is reported rather than invented, and stop at
    ``FILL_DEADLINE_SEC`` so a stalled model cannot hold the send.
    """
    from vendoo_studio.services.fill_log import MAX_PATCH_FIELDS
    from vendoo_studio.services.listing_field_gaps import (
        MAX_GAPS_PER_ROUND,
        _request_missing_field_values,
    )

    current = dict(listing) if isinstance(listing, dict) else {}
    from vendoo_studio.models.ebay_fields import normalize_ebay_sizes

    normalize_ebay_sizes(current)
    if provider is None or not specifics:
        return current, specifics_gaps(current, specifics)

    filled = 0
    stalled: set[tuple[str, str]] = set()
    deadline = time.monotonic() + FILL_DEADLINE_SEC
    for _ in range(MAX_ROUNDS):
        gaps = [
            gap for gap in specifics_gaps(current, specifics)
            if (gap["marketplace"], gap["field"]) not in stalled
        ]
        if not gaps:
            break
        batch = gaps[:MAX_GAPS_PER_ROUND]
        request = asyncio.ensure_future(_request_missing_field_values(
            provider,
            listing=current,
            gaps=batch,
            evidence=evidence,
        ))
        # Not wait_for: that waits out the cancelled call's cleanup, and a
        # stalled provider's cleanup can itself block on its worker thread.
        done, _pending = await asyncio.wait({request}, timeout=max(deadline - time.monotonic(), 0))
        if not done:
            request.cancel()
            log.warning("category field fill stopped after %.0fs", FILL_DEADLINE_SEC)
            break
        patches = request.result()
        if not patches:
            stalled.update((gap["marketplace"], gap["field"]) for gap in batch)
            continue
        # Cap what lands, not just what was asked: a model that answers more
        # fields than it was given should not get to write them.
        updated = write_values_into_listing(current, patches[:MAX_PATCH_FIELDS])
        normalize_ebay_sizes(updated)
        if updated == current:
            # Move past this batch so unresolved fields do not hide later ones.
            stalled.update((gap["marketplace"], gap["field"]) for gap in batch)
            continue
        current = updated
        filled += len(patches[:MAX_PATCH_FIELDS])

    remaining = specifics_gaps(current, specifics)
    if filled or remaining:
        log.info("category fields: filled %s, %s still empty", filled, len(remaining))
    return current, remaining
