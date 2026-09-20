"""Seller facts rescued from a listing before Regenerate wipes it.

Regenerate throws away the listing and generates a new one from the photos and
Item Details. Anything the seller typed into Item Details survives that on its
own, but the facts that only ever lived on the listing — Vendoo's cost of goods,
labels and internal notes on an imported item, and the measurements and flaws
written into the description — would be lost. Carrying them into Item Details
first puts them back in front of the generator as seller-provided facts.
"""

from __future__ import annotations

import re
from typing import Any

# A description block runs from its marker to a blank line or the next marker,
# which is how the skill's Flaws:/Measurements: formula lays them out.
_BLOCK_TEMPLATE = r"(?is)\b{marker}\s*:\s*(.+?)(?=\n\s*\n|\n\s*[A-Za-z][A-Za-z /]{{1,20}}\s*:|\Z)"
_NO_FLAWS_RE = re.compile(r"(?i)^(?:none|no known|no visible|nothing)\b")
_DIGIT_RE = re.compile(r"\d")


def description_block(description: Any, marker: str) -> str:
    """The text of one ``Marker: ...`` block in a description, or "".

    ``marker`` is a regex, so one heading can cover both spellings (``flaws?``).
    """
    text = str(description or "")
    if not text.strip():
        return ""
    match = re.search(_BLOCK_TEMPLATE.format(marker=marker), text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip().rstrip(".")


def _measurements_from_description(description: Any) -> str:
    """Measurements worth keeping: "See photos" carries nothing to carry over."""
    block = description_block(description, "measurements?")
    return block if _DIGIT_RE.search(block) else ""


def _flaws_from_description(description: Any) -> str:
    block = description_block(description, "flaws?")
    return "" if _NO_FLAWS_RE.match(block) else block


def _money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{amount:.2f}" if amount > 0 else ""


def carryover_updates(listing: dict | None, notes: dict) -> dict[str, str]:
    """Item Details updates that keep ``listing``'s seller facts alive.

    Fields the seller already filled in win: only empty ones are filled from the
    listing. Measurements and flaws read from the description are refreshed each
    time, so the newest description is the one carried forward.
    """
    if not isinstance(listing, dict):
        return {}
    updates: dict[str, str] = {}

    if not str(notes.get("cog") or "").strip():
        cost = _money(listing.get("cost"))
        if cost:
            updates["cog"] = cost

    if not str(notes.get("vendooLabels") or "").strip():
        labels = listing.get("labels")
        if isinstance(labels, list):
            joined = ", ".join(str(label).strip() for label in labels if str(label).strip())
            if joined:
                updates["vendooLabels"] = joined

    if not str(notes.get("sellerNotes") or "").strip():
        internal = str(listing.get("internal_notes") or "").strip()
        if internal:
            updates["sellerNotes"] = internal

    description = listing.get("description")
    measurements = _measurements_from_description(description)
    if measurements:
        updates["descriptionMeasurements"] = measurements
    flaws = _flaws_from_description(description)
    if flaws:
        updates["knownFlaws"] = flaws

    return updates
