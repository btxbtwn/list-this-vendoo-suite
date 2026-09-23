"""What Studio keeps from a Vendoo draft: where each marketplace stands.

The sidebar chips and the hover popup read one thing out of a draft — whether
the item is listed, not listed, sold or failed on each marketplace. Everything
else in a Vendoo item (description, photos, per-marketplace specifics) is read
live when a panel needs it, so keeping a copy only cost disk.
"""

from __future__ import annotations

EMPTY_STATUS = (None, "", {}, [])


def _listing_statuses(item: object) -> dict:
    if not isinstance(item, dict):
        return {}
    listings = item.get("listings")
    if not isinstance(listings, dict):
        return {}
    return {
        marketplace: {"status": listing["status"]}
        for marketplace, listing in listings.items()
        if isinstance(listing, dict) and listing.get("status") not in EMPTY_STATUS
    }


def slim_vendoo_draft_payload(
    *,
    item: dict | None = None,
    form: dict | None = None,
    statuses: dict | None = None,
) -> dict:
    """The status slices of a draft, in the shape the UI already reads."""
    payload: dict = {}
    listings = _listing_statuses(item)
    if listings:
        payload["item"] = {"listings": listings}
    form_statuses = form.get("statuses") if isinstance(form, dict) else None
    if isinstance(form_statuses, dict) and form_statuses:
        payload["form"] = {"statuses": form_statuses}
    if isinstance(statuses, dict) and statuses:
        payload["statuses"] = statuses
    return payload


def draft_has_status_signal(payload: object) -> bool:
    """True when a cached draft can say anything about a marketplace."""
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("item") or payload.get("form") or payload.get("statuses"))
