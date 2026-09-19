"""Pending "Vendoo was saved — pull?" offers for the Studio UI.

The Chrome extension notices a seller save on web.vendoo.co and tells Studio
once. Studio records an offer keyed by conversation; the UI polls and asks
before pulling. No Vendoo API traffic until the seller confirms.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(frozen=True)
class PullOffer:
    conversation_id: str
    item_id: str
    conflict: bool
    offered_at: str


_lock = Lock()
_offers: dict[str, PullOffer] = {}


def offer_pull(*, conversation_id: str, item_id: str, conflict: bool) -> PullOffer:
    """Record or refresh a pull offer for a bound listing."""
    offer = PullOffer(
        conversation_id=conversation_id,
        item_id=item_id,
        conflict=bool(conflict),
        offered_at=datetime.now(UTC).isoformat(),
    )
    with _lock:
        _offers[conversation_id] = offer
    return offer


def list_offers() -> list[PullOffer]:
    with _lock:
        return list(_offers.values())


def get_offer(conversation_id: str) -> PullOffer | None:
    with _lock:
        return _offers.get(conversation_id)


def clear_offer(conversation_id: str) -> bool:
    with _lock:
        return _offers.pop(conversation_id, None) is not None


def clear_all() -> None:
    with _lock:
        _offers.clear()
