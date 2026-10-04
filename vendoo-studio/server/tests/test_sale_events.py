from __future__ import annotations

import json
import unittest
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from vendoo_studio.database import SessionLocal
from vendoo_studio.main import app
from vendoo_studio.models.sale_event import SaleEvent
from vendoo_studio.repositories.queries import ConversationRepo
from vendoo_studio.services.inventory_analytics import AnalyticsItem, summarize
from vendoo_studio.services.sale_events import event_row, window

START = date(2026, 9, 10)
END = date(2026, 9, 16)


def _sale(sold: date, *, marketplace: str = "depop", price: float = 20, cid: str | None = None) -> AnalyticsItem:
    return AnalyticsItem(
        conversation_id=cid or uuid.uuid4().hex,
        title="Tee",
        status="sold",
        price=price,
        cost=None,
        brand="",
        category="",
        sold_price=price,
        sold_at=datetime(sold.year, sold.month, sold.day, 12, tzinfo=UTC),
        listed_at=None,
        marketplace=marketplace,
        days_listed=None,
    )


def _event(**overrides) -> SaleEvent:
    fields = {"id": "e1", "name": "Depop sitewide sale", "starts_on": START, "ends_on": END,
              "marketplaces": ["depop", "ebay"], "discount_percent": 25}
    fields.update(overrides)
    return SaleEvent(**fields)


class EventRowTest(unittest.TestCase):
    def test_counts_sales_on_its_marketplaces_and_days_only(self):
        items = [
            _sale(START, cid="first-day"),
            _sale(END, marketplace="ebay", cid="last-day"),
            _sale(START, marketplace="poshmark"),
            _sale(START - timedelta(days=1)),
            _sale(END + timedelta(days=1)),
        ]
        row = event_row(_event(), items, today=date(2026, 10, 4))
        self.assertEqual(row["status"], "ended")
        self.assertEqual({sale["conversation_id"] for sale in row["sales"]}, {"first-day", "last-day"})
        self.assertEqual(row["revenue"], 40)
        self.assertEqual(row["per_week"], 2.0)

    def test_compares_against_four_weeks_before_and_two_after(self):
        before = [_sale(START - timedelta(days=offset)) for offset in (1, 8, 15, 28)]
        outside = _sale(START - timedelta(days=29))
        after = [_sale(END + timedelta(days=offset)) for offset in (1, 14)]
        row = event_row(_event(), [*before, outside, *after], today=date(2026, 10, 4))
        self.assertEqual(row["before_per_week"], 1.0)
        self.assertEqual(row["after_per_week"], 1.0)
        self.assertEqual(row["after_days"], 14)

    def test_a_running_event_rates_only_the_days_so_far(self):
        row = event_row(_event(), [_sale(START), _sale(START + timedelta(days=1))], today=START + timedelta(days=1))
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["per_week"], 7.0)
        self.assertIsNone(row["after_per_week"])

    def test_upcoming_event_has_no_rate_yet(self):
        row = event_row(_event(), [], today=START - timedelta(days=3))
        self.assertEqual(row["status"], "upcoming")
        self.assertIsNone(row["per_week"])

    def test_no_marketplaces_means_every_marketplace(self):
        span = window(_event(marketplaces=[]))
        self.assertTrue(span.covers(_sale(START, marketplace="poshmark")))

    def test_recent_sales_carry_the_event_they_fell_in(self):
        payload = summarize(
            [_sale(START, cid="in"), _sale(START, marketplace="mercari", cid="out")],
            range_id="all",
            now=datetime(2026, 10, 4, tzinfo=UTC),
            events=[window(_event())],
        )
        tags = {row["conversation_id"]: row["event"] for row in payload["recent"]}
        self.assertEqual(tags, {"in": "Depop sitewide sale", "out": None})


class SaleEventRoutesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_create_report_and_delete(self):
        name = f"Etsy Cyber Week {uuid.uuid4().hex[:6]}"
        ConversationRepo(self.db).create(title="Event sale", notes=json.dumps({
            "vendooStatus": "sold",
            "vendooSale": {"price": 24, "marketplace": "etsy"},
            "vendooDates": {"sold": "2026-11-28T18:00:00+00:00"},
        }))
        created = self.client.post("/api/sale-events", json={
            "name": name, "starts_on": "2026-11-27", "ends_on": "2026-12-01",
            "marketplaces": ["etsy"], "discount_percent": 25,
        })
        self.assertEqual(created.status_code, 200)
        event = next(row for row in created.json()["events"] if row["name"] == name)
        self.assertGreaterEqual(event["sold"], 1)
        self.assertEqual(event["marketplaces"], ["etsy"])

        backwards = self.client.post("/api/sale-events", json={
            "name": name, "starts_on": "2026-12-01", "ends_on": "2026-11-27",
        })
        self.assertEqual(backwards.status_code, 400)

        gone = self.client.delete(f"/api/sale-events/{event['id']}").json()
        self.assertNotIn(event["id"], [row["id"] for row in gone["events"]])
        self.assertEqual(self.client.delete(f"/api/sale-events/{event['id']}").status_code, 404)
