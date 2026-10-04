"""Seller facts rescued from a listing before Regenerate wipes it.

Regenerate throws away the listing and generates a new one from the photos and
Item Details. Anything the seller typed into Item Details survives that on its
own, but the facts that only ever lived on the listing — SKU, package size,
Poshmark original price, Vendoo's cost of goods, labels and internal notes on
an imported item, the asking price, and the measurements and flaws written into
the description — would be lost. Carrying them into Item Details first puts them
back in front of the generator as seller-provided facts.
"""

from __future__ import annotations

import re
from typing import Any

# A description block runs from its marker to a blank line or the next marker,
# which is how the skill's Flaws:/Measurements: formula lays them out. A line
# like ``Length: 27"`` is a measurement inside the block, not a new marker.
_BLOCK_TEMPLATE = (
    r"(?is)\b{marker}\s*:\s*(.+?)"
    r"(?=\n\s*\n|\n\s*[A-Za-z][A-Za-z /]{{1,20}}\s*:(?!\s*[\d.])|\Z)"
)
_NO_FLAWS_RE = re.compile(r"(?i)^(?:none|no known|no visible|no notable|nothing|n/?a)\b")
_DIGIT_RE = re.compile(r"\d")
# The formula's closing phrase, not part of the flaws themselves.
_SEE_PHOTOS_RE = re.compile(r"(?i)[\s.;,]*see (?:the )?photos(?: for (?:details|more))?[\s.]*$")

DEFAULT_PACKAGE_DIMENSIONS = "13x10x3"


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
    lines = [re.sub(r"\s+", " ", line).strip().rstrip(";") for line in match.group(1).splitlines()]
    return "; ".join(line for line in lines if line).strip().rstrip(".")


def set_description_block(description: Any, marker: str, line: str, *, before: str = "") -> str:
    """``description`` with its ``Marker: ...`` block replaced by ``line``.

    A missing block is added ahead of the ``before`` block when there is one,
    otherwise at the end, so Flaws: still reads above Measurements:.
    """
    text = str(description or "").strip()
    pattern = re.compile(_BLOCK_TEMPLATE.format(marker=marker))
    if pattern.search(text):
        return pattern.sub(lambda _match: line, text, count=1)
    anchor = re.search(_BLOCK_TEMPLATE.format(marker=before), text) if before else None
    if anchor:
        head = text[: anchor.start()].rstrip()
        return f"{head}\n\n{line}\n\n{text[anchor.start():]}" if head else f"{line}\n\n{text}"
    return f"{text}\n\n{line}" if text else line


def without_see_photos(flaws: Any) -> str:
    """Flaws text without the formula's trailing "See photos for details"."""
    return _SEE_PHOTOS_RE.sub("", str(flaws or "")).strip().rstrip(".")


def _measurements_from_description(description: Any) -> str:
    """Measurements worth keeping: "See photos" carries nothing to carry over."""
    block = description_block(description, "measurements?")
    return block if _DIGIT_RE.search(block) else ""


def says_no_flaws(text: str) -> bool:
    """True for filler such as "none noted" that a Flaws block carries when there are none."""
    return bool(_NO_FLAWS_RE.match(text.strip()))


def _flaws_from_description(description: Any) -> str:
    block = without_see_photos(description_block(description, "flaws?"))
    return "" if says_no_flaws(block) else block


def _money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{amount:.2f}" if amount > 0 else ""


def _poshmark_original(listing: dict) -> str:
    specifics = listing.get("poshmark_specifics")
    if not isinstance(specifics, dict):
        return ""
    try:
        amount = float(specifics.get("originalPrice"))
    except (TypeError, ValueError):
        return ""
    if amount <= 0:
        return ""
    return str(int(amount)) if amount == int(amount) else f"{amount:.2f}"


def carryover_updates(listing: dict | None, notes: dict) -> dict[str, str]:
    """Item Details updates that keep ``listing``'s seller facts alive.

    Fields the seller already filled in win: only empty ones are filled from the
    listing. Measurements and flaws read from the description are refreshed each
    time, so the newest description is the one carried forward.
    """
    if not isinstance(listing, dict):
        return {}
    updates: dict[str, str] = {}

    if not str(notes.get("sku") or "").strip():
        sku = str(listing.get("sku") or "").strip()
        if sku:
            updates["sku"] = sku

    if not str(notes.get("cog") or "").strip():
        cost = _money(listing.get("cost"))
        if cost:
            updates["cog"] = cost

    notes_pkg = str(notes.get("packageDimensions") or "").strip()
    if not notes_pkg or notes_pkg == DEFAULT_PACKAGE_DIMENSIONS:
        listing_pkg = str(listing.get("package_dimensions_in") or "").strip()
        if listing_pkg and listing_pkg != DEFAULT_PACKAGE_DIMENSIONS:
            updates["packageDimensions"] = listing_pkg

    notes_posh = str(notes.get("poshmarkOriginalPrice") or "").strip()
    if not notes_posh or notes_posh == "0":
        posh = _poshmark_original(listing)
        if posh:
            updates["poshmarkOriginalPrice"] = posh

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

    # The price the seller just confirmed, refreshed each time like the
    # description blocks below: a rewrite must not re-invent it.
    price = _money(listing.get("price"))
    if price:
        updates["askingPrice"] = price

    description = listing.get("description")
    measurements = _measurements_from_description(description)
    if measurements:
        updates["descriptionMeasurements"] = measurements
    flaws = _flaws_from_description(description)
    if flaws:
        updates["knownFlaws"] = flaws

    return updates
