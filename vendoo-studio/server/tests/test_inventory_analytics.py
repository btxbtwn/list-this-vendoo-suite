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
        "cost": None,
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
                _item(conversation_id="c2", cost=None, sold_price=20),
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

    def test_zero_cost_is_known_and_missing_price_is_not_asking_price(self):
        payload = summarize([
            _item(cost=0, fees=5),
            _item(conversation_id="missing", sold_price=None, cost=10),
            _item(conversation_id="free-sale", sold_price=0, cost=2),
        ], range_id="30d", now=NOW)
        self.assertEqual(payload["sales"]["count"], 3)
        self.assertEqual(payload["sales"]["revenue"], 36)
        self.assertEqual(payload["sales"]["revenue_known"], 2)
        self.assertEqual(payload["sales"]["average_price"], 18)
        self.assertEqual(payload["sales"]["profit_known"], 2)
        self.assertEqual(payload["sales"]["profit"], 29)
        self.assertIsNone(next(row for row in payload["recent"] if row["conversation_id"] == "missing")["price"])

    def test_comparison_boundaries_and_future_sales(self):
        for span, days in (("30d", 30), ("90d", 90)):
            start = NOW - timedelta(days=days)
            payload = summarize([
                _item(sold_at=start),
                _item(conversation_id="previous", sold_at=start - timedelta(days=days)),
                _item(conversation_id="too-old", sold_at=start - timedelta(days=days, seconds=1)),
                _item(conversation_id="future", sold_at=NOW + timedelta(seconds=1)),
                _item(conversation_id="undated", sold_at=None),
            ], range_id=span, now=NOW)
            self.assertEqual(payload["sales"]["count"], 1)
            self.assertEqual(payload["previous"]["sales"]["count"], 1)
            self.assertEqual(sum(row["count"] for row in payload["periods"]), 1)
        all_time = summarize([_item(sold_at=NOW + timedelta(days=1))], range_id="all", now=NOW)
        self.assertEqual(all_time["sales"]["count"], 0)
        self.assertIsNone(all_time["previous"])

    def test_twelve_month_comparison_has_equal_duration(self):
        payload = summarize([], range_id="12m", now=NOW)
        previous = payload["previous"]
        end = datetime.fromisoformat(previous["end"])
        start = datetime.fromisoformat(previous["start"])
        self.assertEqual(NOW - end, end - start)
        self.assertEqual(end, datetime(2025, 10, 1, tzinfo=UTC))

    def test_aging_drilldown_contains_only_bucket_members_oldest_first(self):
        payload = summarize([
            _item(conversation_id="old", status="active", listed_at=NOW - timedelta(days=100)),
            _item(conversation_id="older", status="active", listed_at=NOW - timedelta(days=120)),
            _item(conversation_id="undated", status="active", listed_at=None),
            _item(conversation_id="sold", status="sold", listed_at=NOW - timedelta(days=100)),
        ], range_id="30d", now=NOW)
        groups = {row["label"]: row for row in payload["aging"]}
        old = groups["Over 3 months"]
        self.assertEqual([row["conversation_id"] for row in old["listings"]], ["older", "old"])
        self.assertEqual(old["count"], len(old["listings"]))
        self.assertEqual(old["asking_value"], sum(row["price"] for row in old["listings"]))
        self.assertIsNone(groups["No list date"]["listings"][0]["days_listed"])

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

    def test_loader_preserves_zero_sale_cost_and_unknown_sale_price(self):
        notes = json.loads(self.sold.notes)
        notes["vendooSale"]["cost"] = 0
        notes["vendooSale"].pop("price")
        self.sold.notes = json.dumps(notes)
        self.db.commit()
        row = next(row for row in load_rows(self.db) if row.conversation_id == self.sold.id)
        self.assertEqual(row.cost, 0)
        self.assertIsNone(row.sold_price)

    def test_route_returns_the_workspace(self):
        client = TestClient(app)
        ok = client.get("/api/analytics?range=all")
        self.assertEqual(ok.status_code, 200, ok.text)
        body = ok.json()
        self.assertGreaterEqual(body["inventory"]["sold"], 1)
        self.assertIn(body["range"], ("all",))
        self.assertIn("fees_known", body["sales"])
        self.assertIn("revenue_known", body["sales"])
        self.assertIn("days_known", body["sales"])
        self.assertIsNone(body["previous"])
        month = client.get("/api/analytics?range=30d").json()
        self.assertIn("fees_known", month["previous"]["sales"])
        bad = client.get("/api/analytics?range=nope")
        self.assertEqual(bad.status_code, 400)


class StaleListingsTest(unittest.TestCase):
    def _stale(self, **overrides):
        fields = {"conversation_id": "old", "status": "active", "price": 30, "sold_price": None,
                  "sold_at": None, "listed_at": NOW - timedelta(days=70)}
        fields.update(overrides)
        return summarize([_item(**fields)], range_id="all", now=NOW)["stale"]

    def test_only_active_listings_past_sixty_days_oldest_first(self):
        payload = summarize([
            _item(conversation_id="young", status="active", listed_at=NOW - timedelta(days=59)),
            _item(conversation_id="old", status="active", listed_at=NOW - timedelta(days=61)),
            _item(conversation_id="older", status="active", listed_at=NOW - timedelta(days=200)),
            _item(conversation_id="undated", status="active", listed_at=None),
            _item(conversation_id="sold", listed_at=NOW - timedelta(days=200)),
        ], range_id="all", now=NOW)
        self.assertEqual([row["conversation_id"] for row in payload["stale"]], ["older", "old"])

    def test_cuts_as_deep_as_the_cost_after_fees_allows(self):
        # $8 cost needs $10 back after 20% fees: 40% off $30 is $18.
        row = self._stale(cost=8)[0]
        self.assertEqual(row["lowest_price"], 10)
        self.assertEqual(row["discount_percent"], 40)
        self.assertEqual(row["sale_price"], 18)
        # $15 cost needs $19: 40% off ($18) is too deep, 35% off ($19.50) is not.
        self.assertEqual(self._stale(cost=15)[0]["discount_percent"], 35)
        # $17 cost needs $22: only the everyday 25% off ($22.50) still covers it.
        self.assertEqual(self._stale(cost=17)[0]["discount_percent"], 25)
        # $18 cost needs $23: even 25% off is a loss, so no cut at all.
        held = self._stale(cost=18)[0]
        self.assertIsNone(held["discount_percent"])
        self.assertIsNone(held["sale_price"])

    def test_no_cost_means_no_floor_and_the_shallower_deep_cut(self):
        row = self._stale(cost=None)[0]
        self.assertIsNone(row["lowest_price"])
        self.assertEqual(row["discount_percent"], 35)
        self.assertEqual(row["sale_price"], 19.5)
