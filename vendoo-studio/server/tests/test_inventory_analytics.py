from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from vendoo_studio.database import SessionLocal
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.inventory_analytics import AnalyticsItem, load_rows, summarize

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def _item(**overrides) -> AnalyticsItem:
    fields = {
        "conversation_id": "c1",
        "title": "Nike Tee",
        "status": "sold",
        "price": 48,
        "cost": 0,
        "brand": "Nike",
        "category": "T-Shirts",
        "sold_price": 36,
        "sold_at": NOW - timedelta(days=1),
        "listed_at": NOW - timedelta(days=20),
        "marketplace": "depop",
        "days_listed": 19,
    }
    fields.update(overrides)
    return AnalyticsItem(**fields)


class SummarizeAnalyticsTest(unittest.TestCase):
    def test_sold_price_is_revenue_and_asking_price_is_inventory(self):
        payload = summarize(
            [
                _item(),
                _item(
                    conversation_id="live",
                    status="active",
                    price=50,
                    sold_price=0,
                    sold_at=None,
                    marketplace="ebay",
                ),
                _item(
                    conversation_id="draft",
                    status="draft",
                    price=100,
                    sold_price=0,
                    sold_at=None,
                ),
            ],
            range_id="30d",
            now=NOW,
        )
        self.assertEqual(payload["sales"]["count"], 1)
        self.assertEqual(payload["sales"]["revenue"], 36)
        self.assertEqual(payload["inventory"]["asking_value"], 50)
        self.assertEqual(payload["inventory"]["active"], 1)
        self.assertEqual(payload["inventory"]["draft"], 1)
        self.assertEqual(payload["inventory"]["sold"], 1)

    def test_profit_ignores_items_with_no_cost(self):
        payload = summarize(
            [
                _item(cost=10, sold_price=40),
                _item(conversation_id="c2", cost=0, sold_price=20),
                _item(conversation_id="c3", cost=25, sold_price=10),
            ],
            range_id="all",
            now=NOW,
        )
        self.assertEqual(payload["sales"]["profit_known"], 2)
        self.assertEqual(payload["sales"]["profit"], 15)

    def test_profit_nets_fees_and_shipping_like_vendoo(self):
        payload = summarize(
            [
                _item(conversation_id="a", sold_price=40, cost=10, fees=8.5, shipping_cost=7, shipping_credit=5),
                _item(conversation_id="b", sold_price=20, cost=5),
            ],
            range_id="all",
            now=NOW,
        )
        self.assertEqual(payload["sales"]["profit"], 34.5)
        self.assertEqual(payload["sales"]["fees_known"], 1)

    def test_a_sale_outside_the_window_drops_out(self):
        old = _item(sold_at=NOW - timedelta(days=40), days_listed=10)
        self.assertEqual(summarize([old], range_id="30d", now=NOW)["sales"]["count"], 0)
        kept = summarize([old], range_id="90d", now=NOW)
        self.assertEqual(kept["sales"]["count"], 1)
        self.assertEqual(kept["sales"]["median_days"], 10)

    def test_undated_sales_count_only_in_all_time(self):
        undated = _item(sold_at=None, sold_price=22, days_listed=None)
        month = summarize([undated, _item()], range_id="30d", now=NOW)
        everything = summarize([undated, _item()], range_id="all", now=NOW)
        self.assertEqual(month["sales"]["count"], 1)
        self.assertEqual(month["undated_sales"], 1)
        self.assertEqual(everything["sales"]["count"], 2)
        self.assertEqual(everything["sales"]["revenue"], 58)
        self.assertEqual(sum(period["count"] for period in everything["periods"]), 1)

    def test_dated_sales_land_in_the_chart(self):
        payload = summarize([_item(), _item(conversation_id="c2")], range_id="30d", now=NOW)
        self.assertEqual(len(payload["periods"]), 6)
        self.assertEqual(payload["periods"][-1]["count"], 2)
        self.assertEqual(sum(period["revenue"] for period in payload["periods"]), 72)

    def test_groups_brand_and_category_without_case(self):
        payload = summarize(
            [
                _item(brand="Nike", category="T-Shirts", sold_price=30, marketplace="depop"),
                _item(
                    conversation_id="c2",
                    brand="nike",
                    category="t-shirts",
                    sold_price=10,
                    marketplace="ebay",
                ),
            ],
            range_id="all",
            now=NOW,
        )
        self.assertEqual(payload["brands"], [{"id": "nike", "label": "Nike", "count": 2, "revenue": 40}])
        self.assertEqual(payload["categories"][0]["count"], 2)
        self.assertEqual(payload["categories"][0]["revenue"], 40)
        markets = {row["id"]: row["revenue"] for row in payload["marketplaces"]}
        self.assertEqual(markets, {"depop": 30, "ebay": 10})

    def test_aging_uses_how_long_active_listings_have_been_up(self):
        payload = summarize(
            [
                _item(
                    conversation_id="fresh",
                    status="active",
                    price=20,
                    sold_price=0,
                    sold_at=None,
                    listed_at=NOW - timedelta(days=3),
                ),
                _item(
                    conversation_id="stale",
                    status="active",
                    price=80,
                    sold_price=0,
                    sold_at=None,
                    listed_at=NOW - timedelta(days=100),
                ),
            ],
            range_id="all",
            now=NOW,
        )
        labels = {row["label"]: row for row in payload["aging"]}
        self.assertEqual(labels["Under 2 weeks"]["count"], 1)
        self.assertEqual(labels["Under 2 weeks"]["asking_value"], 20)
        self.assertEqual(labels["Over 3 months"]["asking_value"], 80)

    def test_twelve_month_totals_match_the_chart(self):
        inside = _item(sold_at=NOW - timedelta(days=300))
        outside = _item(conversation_id="old", sold_at=NOW - timedelta(days=400))
        payload = summarize([inside, outside], range_id="12m", now=NOW)
        self.assertEqual(payload["sales"]["count"], 1)
        self.assertEqual(len(payload["periods"]), 12)
        self.assertEqual(sum(period["count"] for period in payload["periods"]), 1)

    def test_unknown_range_is_rejected(self):
        from vendoo_studio.services.inventory_analytics import inventory_analytics

        with self.assertRaises(ValueError):
            inventory_analytics(None, range_id="week")


class LoadAnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        repo = ConversationRepo(self.db)
        self.sold = repo.create(title="Imported tee")
        self.busy = repo.create(title="Sending")
        ListingRepo(self.db).save_revision(
            self.sold.id,
            {
                "title": "Imported tee",
                "description": "Cotton.",
                "price": 48,
                "cost": 12,
                "brand": "Nike",
                "category_path": "Women > Tops > T-Shirts",
                "condition": "Pre-Owned - Good",
                "quantity": 1,
            },
            source="import",
        )
        self.sold.notes = json.dumps({
            "vendooStatus": "sold",
            "vendooSale": {
                "price": 36,
                "marketplace": "depop",
                "soldAt": "2026-09-01T00:00:00+00:00",
            },
            "vendooDates": {
                "listed": "2026-08-01T00:00:00+00:00",
                "sold": "2026-09-01T00:00:00+00:00",
            },
        })
        self.sold.status = "draft"
        self.busy.notes = json.dumps({"vendooStatus": "sold"})
        self.busy.status = "listing"
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_loader_prefers_the_sale_price_and_leaves_a_busy_send_alone(self):
        rows = {row.conversation_id: row for row in load_rows(self.db)}
        sold = rows[self.sold.id]
        self.assertEqual(sold.status, "sold")
        self.assertEqual(sold.sold_price, 36)
        self.assertEqual(sold.cost, 12)
        self.assertEqual(sold.brand, "Nike")
        self.assertEqual(sold.category, "T-Shirts")
        self.assertEqual(sold.marketplace, "depop")
        self.assertEqual(sold.days_listed, 31)
        self.assertEqual(rows[self.busy.id].status, "listing")

    def test_route_returns_the_workspace(self):
        client = TestClient(app)
        ok = client.get("/api/analytics?range=all")
        self.assertEqual(ok.status_code, 200, ok.text)
        body = ok.json()
        self.assertGreaterEqual(body["inventory"]["sold"], 1)
        self.assertIn(body["range"], ("all",))
        bad = client.get("/api/analytics?range=nope")
        self.assertEqual(bad.status_code, 400)
