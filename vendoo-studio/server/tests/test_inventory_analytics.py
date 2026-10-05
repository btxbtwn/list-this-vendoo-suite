from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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
    def test_missing_sales_data_includes_undated_and_old_sales_in_every_range(self):
        items = [
            _item(conversation_id="undated", title="A jacket", sold_at=None, sold_price=None,
                  cost=None, fees=None, marketplace="unknown"),
            _item(conversation_id="old", title="B boots", sold_at=NOW - timedelta(days=500),
                  cost=None, fees=0),
            _item(conversation_id="free", title="C tee", sold_price=0, cost=0, fees=0),
            _item(conversation_id="active", status="active", sold_price=None, sold_at=None),
        ]
        for range_id in ("7d", "30d", "all"):
            with self.subTest(range_id=range_id):
                rows = summarize(items, range_id=range_id, now=NOW)["incomplete_sales"]
                self.assertEqual(rows, [
                    {"conversation_id": "undated", "title": "A jacket",
                     "missing": ["sale date", "sale price", "cost", "fees", "marketplace"]},
                    {"conversation_id": "old", "title": "B boots", "missing": ["cost"]},
                ])

    def test_seven_days_has_daily_buckets_and_previous_week_comparison(self):
        start = NOW - timedelta(days=7)
        items = [
            _item(conversation_id=str(day), sold_at=start + timedelta(days=day))
            for day in range(8)
        ] + [
            _item(sold_at=start - timedelta(seconds=1), sold_price=20),
            _item(sold_at=NOW - timedelta(days=14), sold_price=10),
            _item(sold_at=NOW - timedelta(days=14, seconds=1)),
            _item(sold_at=NOW + timedelta(seconds=1)),
            _item(sold_at=None),
        ]
        payload = summarize(items, range_id="7d", now=NOW)
        self.assertEqual(payload["sales"]["count"], 8)
        self.assertEqual([row["count"] for row in payload["periods"]], [1] * 6 + [2])
        self.assertEqual([row["label"] for row in payload["periods"]], [f"9/{day}" for day in range(20, 27)])
        self.assertEqual(payload["previous"]["sales"]["count"], 2)
        self.assertEqual(payload["previous"]["sales"]["revenue"], 30)
        self.assertEqual(payload["previous"]["start"], (NOW - timedelta(days=14)).isoformat())
        self.assertEqual(payload["undated_sales"], 1)

    def test_sell_through_uses_period_sales_and_current_active_inventory(self):
        items = [
            _item(),
            _item(sold_at=NOW - timedelta(days=10)),
            _item(sold_at=None),
            _item(status="active", sold_at=None),
            _item(status="active", sold_at=None),
            _item(status="draft"),
            _item(status="failed"),
            _item(status="listing"),
        ]
        self.assertEqual(summarize(items, range_id="7d", now=NOW)["sell_through_rate"], 33.3)
        self.assertEqual(summarize(items, range_id="all", now=NOW)["sell_through_rate"], 60)

    def test_sell_through_handles_empty_unsold_and_sold_out_inventory(self):
        self.assertIsNone(summarize([], range_id="7d", now=NOW)["sell_through_rate"])
        self.assertIsNone(summarize([_item(status="draft")], range_id="7d", now=NOW)["sell_through_rate"])
        self.assertEqual(summarize([_item(status="active")], range_id="7d", now=NOW)["sell_through_rate"], 0)
        self.assertEqual(summarize([_item()], range_id="7d", now=NOW)["sell_through_rate"], 100)

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

    def test_comparison_uses_an_equal_window_without_overlapping_boundaries(self):
        start = NOW - timedelta(days=30)
        payload = summarize([
            _item(sold_at=start, sold_price=40),
            _item(sold_at=start - timedelta(seconds=1), sold_price=20),
            _item(sold_at=NOW - timedelta(days=60), sold_price=10),
            _item(sold_at=NOW - timedelta(days=60, seconds=1), sold_price=100),
            _item(sold_at=NOW + timedelta(seconds=1), sold_price=100),
            _item(sold_at=None, sold_price=100),
            _item(status="active", sold_at=start - timedelta(days=1)),
        ], range_id="30d", now=NOW)
        self.assertEqual(payload["sales"]["count"], 1)
        self.assertEqual(payload["sales"]["revenue"], 40)
        self.assertEqual(sum(row["revenue"] for row in payload["periods"]), 40)
        self.assertEqual(payload["previous"]["start"], (NOW - timedelta(days=60)).isoformat())
        self.assertEqual(payload["previous"]["end"], start.isoformat())
        self.assertEqual(payload["previous"]["sales"]["count"], 2)
        self.assertEqual(payload["previous"]["sales"]["revenue"], 30)

    def test_comparison_respects_every_selected_range(self):
        for range_id, start in [
            ("90d", NOW - timedelta(days=90)),
            ("12m", datetime(2025, 10, 1, tzinfo=UTC)),
        ]:
            with self.subTest(range_id=range_id):
                previous_start = start - (NOW - start)
                payload = summarize([
                    _item(sold_at=start),
                    _item(sold_at=previous_start),
                    _item(sold_at=previous_start - timedelta(seconds=1)),
                ], range_id=range_id, now=NOW)
                self.assertEqual(payload["sales"]["count"], 1)
                self.assertEqual(payload["previous"]["sales"]["count"], 1)

    def test_all_time_has_no_comparison_and_excludes_future_sales(self):
        payload = summarize([
            _item(sold_at=None),
            _item(sold_at=NOW + timedelta(days=1)),
        ], range_id="all", now=NOW)
        self.assertIsNone(payload["previous"])
        self.assertEqual(payload["sales"]["count"], 1)

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
        self.assertEqual(len(payload["brands"]), 1)
        self.assertEqual(payload["brands"][0]["id"], "nike")
        self.assertEqual(payload["brands"][0]["revenue"], 40)
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

    def test_profit_margin_and_chart_use_only_sales_with_recorded_cost(self):
        payload = summarize([
            _item(cost=10, sold_price=40, fees=5),
            _item(conversation_id="loss", cost=30, sold_price=10, fees=0),
            _item(conversation_id="unknown", cost=None, sold_price=100),
        ], range_id="30d", now=NOW)
        self.assertEqual(payload["sales"]["profit"], 5)
        self.assertEqual(payload["sales"]["margin"], 10)
        self.assertEqual(payload["periods"][-1]["profit"], 5)
        self.assertEqual(payload["periods"][-1]["profit_known"], 2)
        self.assertIsNone(payload["periods"][0]["profit"])
        self.assertEqual(payload["brands"][0]["profit"], 5)
        self.assertEqual(payload["recent"][0]["profit"], 25)

    def test_explicit_zero_cost_is_known(self):
        payload = summarize([_item(cost=0, fees=0)], range_id="all", now=NOW)
        self.assertEqual(payload["sales"]["profit"], 36)
        self.assertEqual(payload["sales"]["margin"], 100)
        self.assertEqual(payload["sales"]["profit_known"], 1)

    def test_inventory_and_oldest_listings_are_independent_of_sales_range(self):
        items = [
            _item(conversation_id="fresh", status="active", price=20, cost=5, listed_at=NOW - timedelta(days=10)),
            _item(conversation_id="old", status="active", price=80, cost=None, listed_at=NOW - timedelta(days=90)),
            _item(conversation_id="older", status="active", price=50, cost=10, listed_at=NOW - timedelta(days=100)),
            _item(conversation_id="undated", status="active", price=10, listed_at=None),
            _item(conversation_id="draft", status="draft", listed_at=NOW - timedelta(days=200)),
            _item(conversation_id="sold", status="sold", listed_at=NOW - timedelta(days=200)),
        ]
        payload = summarize(items, range_id="30d", now=NOW)
        self.assertEqual(payload["inventory"]["cost_value"], 15)
        self.assertEqual(payload["inventory"]["cost_known"], 2)
        self.assertEqual(payload["inventory"]["stale_count"], 2)
        self.assertEqual(payload["inventory"]["stale_value"], 130)
        self.assertEqual(payload["inventory"]["undated_count"], 1)
        self.assertEqual([row["conversation_id"] for row in payload["oldest"]], ["older", "old"])
        self.assertEqual(payload["oldest"][0]["days_listed"], 100)
        all_time = summarize(items, range_id="all", now=NOW)
        self.assertEqual(payload["inventory"], all_time["inventory"])
        self.assertEqual(payload["oldest"], all_time["oldest"])

    def test_rankings_include_groups_outside_the_top_six_by_revenue(self):
        items = [_item(brand=f"Brand {index}", sold_price=100-index, cost=index*10) for index in range(8)]
        payload = summarize(items, range_id="all", now=NOW)
        self.assertEqual(len(payload["brands"]), 8)

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
                "fees": 4,
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

    def test_loader_keeps_an_explicit_zero_sale_cost(self):
        notes = json.loads(self.sold.notes)
        notes["vendooSale"]["cost"] = 0
        self.sold.notes = json.dumps(notes)
        self.db.commit()
        item = next(row for row in load_rows(self.db) if row.conversation_id == self.sold.id)
        self.assertEqual(item.cost, 0)
        self.assertTrue(item.has_cost)
        self.assertEqual(item.profit, 32)

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
        self.assertIn("last_updated_at", body)
        self.assertIn("incomplete_sales", body)
        self.assertIsNone(body["previous"])
        month = client.get("/api/analytics?range=30d").json()
        self.assertIn("fees_known", month["previous"]["sales"])
        week = client.get("/api/analytics?range=7d")
        self.assertEqual(week.status_code, 200, week.text)
        self.assertEqual(week.json()["range"], "7d")
        self.assertEqual(len(week.json()["periods"]), 7)
        self.assertIn("sell_through_rate", week.json())
        bad = client.get("/api/analytics?range=nope")
        self.assertEqual(bad.status_code, 400)

    def test_recalculating_analytics_uses_the_saved_sync_time(self):
        client = TestClient(app)
        with patch("vendoo_studio.services.user_settings.vendoo_inventory_synced_at", return_value="2026-10-05T12:30:00Z"):
            for range_id in ("7d", "all"):
                body = client.get(f"/api/analytics?range={range_id}").json()
                self.assertEqual(body["last_updated_at"], "2026-10-05T12:30:00Z")
        with patch("vendoo_studio.services.user_settings.vendoo_inventory_synced_at", return_value=None):
            self.assertIsNone(client.get("/api/analytics").json()["last_updated_at"])


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
