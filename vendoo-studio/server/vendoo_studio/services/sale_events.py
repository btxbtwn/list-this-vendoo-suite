"""Recorded promotions that can label a sale in the inventory analytics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from vendoo_studio.models.sale_event import SaleEvent
from vendoo_studio.services.inventory_analytics import AnalyticsItem


@dataclass(frozen=True)
class EventWindow:
    name: str
    starts_on: date
    ends_on: date
    marketplaces: frozenset[str]
    timezone: str
    item_ids: frozenset[str]

    def covers(self, item: AnalyticsItem) -> bool:
        if item.status != "sold" or item.sold_at is None:
            return False
        if self.marketplaces and item.marketplace not in self.marketplaces:
            return False
        if self.item_ids and item.conversation_id not in self.item_ids:
            return False
        day = item.sold_at.astimezone(ZoneInfo(self.timezone)).date()
        return self.starts_on <= day <= self.ends_on


def windows(db) -> list[EventWindow]:
    return [EventWindow(
        name=event.title, starts_on=event.start_date, ends_on=event.end_date,
        marketplaces=frozenset() if event.marketplace == "all" else frozenset({event.marketplace}),
        timezone=event.timezone, item_ids=frozenset(item["id"] for item in event.items),
    ) for event in db.query(SaleEvent).filter(SaleEvent.status == "ran").order_by(SaleEvent.start_date.desc()).all()]
