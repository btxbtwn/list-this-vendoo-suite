from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services import box_scout
from vendoo_studio.services.comp_research import ModelSearch


def _raghouse(title: str, price: str, grams: int, *, available: bool = True, tags=(), vid=1):
    return {
        "title": title,
        "handle": title.lower().replace(" ", "-"),
        "product_type": "T-Shirts",
        "tags": ["09-20-2026", *tags],
        "variants": [
            {"id": vid, "available": available, "price": price, "grams": grams, "compare_at_price": None}
        ],
    }


def _tvf(title: str, variants, body="", vid=100):
    return {
        "title": title,
        "handle": title.lower().replace(" ", "-"),
        "product_type": "",
        "tags": [],
        "body_html": body,
        "variants": [
            {"id": vid + i, "title": name, "available": available, "price": price, "grams": grams}
            for i, (name, price, grams, available) in enumerate(variants)
        ],
    }


RAGHOUSE = [
    _raghouse("Cartoon T-Shirts 60 pcs", "60.00", 12701, vid=1),
    _raghouse("Recycle Cartoon T-Shirts 70 pcs", "30.00", 12701, vid=2),
    _raghouse("Cartoon Tees 50 pcs", "40.00", 9072, available=False, vid=3),
    _raghouse("Plain Blank Tees 80 pcs", "40.00", 12701, vid=4),
    _raghouse("Y2K Blouses 40 pcs", "45.00", 7258, tags=("VIP_Product",), vid=5),
    _raghouse("Tiny Lot 5 pcs", "10.00", 2000, vid=6),
]

TVF = [
    _tvf(
        "Wholesale Vintage Graphic T-Shirts (10 Pieces)",
        [("A Grade", "85.00", 2722, True), ("B Grade", "45.00", 2722, False)],
        body="<p>Estimated Resale Value: +$20ea</p>",
        vid=100,
    ),
    _tvf("Men's Flannel Shirts Bale", [("100LB", "400.00", 45359, True), ("50LB", "225.00", 23587, True)], vid=200),
    _tvf("Cartoon T-Shirts", [("S / 3 tees", "40.00", 454, True)], vid=300),
    _tvf("Sample Tee Stock", [("Default Title", "0.00", 907, True)], vid=400),
]

CATALOGS = {"raghouse": RAGHOUSE, "tvf": TVF}
ZONES = {"raghouse": 6, "tvf": 5}  # to 70115
# USPS charts by origin, trimmed to the destinations these tests use.
ZONE_CHARTS = {
    "850": {"701": 6, "100": 8, "850": 1, "967": 8},
    "330": {"701": 5, "100": 6, "850": 8, "967": 8},
}


class ScoutScriptTest(unittest.TestCase):
    def setUp(self):
        self.s = box_scout.scout()
        self.cfg = self.s.load_shipping()
        patcher = mock.patch.object(self.s, "store_today", return_value=date(2026, 9, 27))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _lots(self, **filters):
        return self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(**filters))[1]

    def test_parses_both_stores_into_lots(self):
        lots = {lot["title"]: lot for lot in self._lots()}
        # A 10-piece TVF pack, graded by its variant, with the seller's resale estimate.
        graphic = lots["Wholesale Vintage Graphic T-Shirts (10 Pieces) · A Grade"]
        self.assertEqual((graphic["pcs"], graphic["grade"], graphic["seller_resale"]), (10, "a", 20.0))
        # A bale sold by the pound: pieces estimated from the stated weight.
        bale = lots["Men's Flannel Shirts Bale · 50LB"]
        self.assertEqual((bale["pcs"], bale["pcs_estimated"], bale["lbs"]), (100, True, 51.0))
        # Sold-out variants, 3-tee size packs, free stock and small Raghouse lots are left out.
        self.assertNotIn("Wholesale Vintage Graphic T-Shirts (10 Pieces) · B Grade", lots)
        self.assertNotIn("Cartoon T-Shirts · S / 3 tees", lots)
        self.assertNotIn("Tiny Lot 5 pcs", lots)
        self.assertNotIn("Y2K Blouses 40 pcs", lots)  # VIP only unless asked for

    def test_shipping_uses_each_stores_zone_and_whole_pounds(self):
        lots = {lot["title"]: lot for lot in self._lots()}
        # Raghouse, zone 6: 12701 g bills as 29 lb, ($44.23 + $6.50) x 1.26 fuel.
        self.assertEqual(lots["Cartoon T-Shirts 60 pcs"]["ship_est"], 63.92)
        # TVF, zone 5: 2722 g bills as 7 lb, ($19.26 + $6.50) x 1.26.
        self.assertEqual(lots["Wholesale Vintage Graphic T-Shirts (10 Pieces) · A Grade"]["ship_est"], 32.46)

    def test_zone_for_a_destination(self):
        chart = ZONE_CHARTS["850"]
        self.assertEqual(self.s.zone_for(chart, "70115"), 6)
        self.assertEqual(self.s.zone_for(chart, "85043"), 2)  # local zone 1 bills as zone 2
        self.assertIsNone(self.s.zone_for(chart, "96815"))  # Hawaii: outside the rate table
        self.assertIsNone(self.s.zone_for(chart, "7011"))

    def test_buy_list_keeps_to_budget_one_lot_per_theme(self):
        resale = {"cartoon t-shirts": 15, "plain blank tees": 6, "men's flannel shirts": 12}
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(), resale)[1]
        plan = self.s.buy_list(rows, self.cfg, budget=150, min_roi=0.5)
        picked = [lot["title"] for cart in plan["carts"] for lot in cart["lots"]]
        self.assertEqual(picked, ["Recycle Cartoon T-Shirts 70 pcs"])  # the dearer cartoon lot shares its theme
        self.assertLessEqual(plan["total"], 150)
        self.assertEqual(plan["carts"][0]["cart_url"], "https://raghouse.com/cart/2:1")

    def test_free_shipping_once_a_store_order_clears_its_threshold(self):
        resale = {"men's flannel shirts": 12}
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(), resale)[1]
        cart = self.s.buy_list(rows, self.cfg, budget=1000, min_roi=0)["carts"][0]
        self.assertEqual(cart["store"], "tvf")
        self.assertTrue(cart["free_shipping"])
        lot = cart["lots"][0]
        self.assertEqual(lot["title"], "Men's Flannel Shirts Bale · 100LB")  # one bale per theme
        self.assertEqual((lot["ship_est"], lot["landed"]), (0, lot["price"]))


def _search(label: str, answers: list[str]) -> ModelSearch:
    calls = iter(answers)

    async def search(messages):
        return {"answer": next(calls), "sources": []}

    return ModelSearch(label, search)


class RefreshTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_file = Path(tmp.name) / "sourcing.json"
        s = box_scout.scout()
        self.fetch = mock.patch.object(s, "fetch_catalog", side_effect=lambda store: CATALOGS[store]).start()
        mock.patch.object(s, "store_today", return_value=date(2026, 9, 27)).start()
        self.charts = mock.patch.object(s, "fetch_zone_chart", side_effect=ZONE_CHARTS.__getitem__).start()
        mock.patch.object(box_scout, "state_path", return_value=self.state_file).start()
        mock.patch.dict(box_scout._catalogs, clear=True).start()
        self.addCleanup(mock.patch.stopall)

    def _models(self, search=None):
        return mock.patch("vendoo_studio.services.comp_research.model_search", return_value=search)

    def test_researches_trends_and_prices_then_builds_the_buy_list(self):
        prices = json.dumps({"prices": [
            {"theme": "cartoon t-shirts", "per_piece": 15, "evidence": ["https://www.ebay.com/itm/1"]},
            {"theme": "not asked for", "per_piece": 99},
        ]})
        model = _search("ChatGPT", ['```json\n{"terms": ["Cartoon", "y2k"]}\n```', prices, "{}"])
        with self._models(model):
            snapshot = box_scout.refresh()
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["trend"]["terms"], ["cartoon", "y2k"])
        self.assertEqual(set(state["resale"]), {"cartoon t-shirts"})
        self.assertEqual(state["resale"]["cartoon t-shirts"]["source"], "ChatGPT")
        lots = snapshot["buy_list"]["carts"][0]["lots"]
        self.assertEqual(lots[0]["title"], "Recycle Cartoon T-Shirts 70 pcs")
        self.assertEqual(lots[0]["evidence"], ["https://www.ebay.com/itm/1"])
        self.assertTrue(snapshot["research"])

    def test_cached_research_is_not_repeated(self):
        prices = json.dumps({"prices": [{"theme": "cartoon t-shirts", "per_piece": 15}]})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}', prices, "{}"])):
            box_scout.refresh()
        trends = mock.AsyncMock(return_value=([], None))
        research = mock.AsyncMock(return_value=({}, None))
        with self._models(_search("ChatGPT", [])), \
                mock.patch.object(box_scout, "_research_trends", trends), \
                mock.patch.object(box_scout, "_research_prices", research):
            box_scout.refresh()
        trends.assert_not_called()  # a week has not passed
        asked = [theme for call in research.call_args_list for theme in call.args[0]]
        self.assertTrue(asked)
        self.assertNotIn("cartoon t-shirts", asked)  # priced a moment ago

    def test_without_models_it_still_ranks_boxes(self):
        with self._models():
            snapshot = box_scout.refresh()
        self.assertFalse(snapshot["research"])
        self.assertEqual(snapshot["buy_list"]["carts"], [])
        self.assertGreater(len(snapshot["lots"]), 0)

    def test_another_zip_reprices_shipping_from_the_last_crawl(self):
        with self._models():
            box_scout.refresh()
            box_scout.set_prefs(zip="10001")
            snapshot = box_scout.refresh(recrawl=False)
        self.assertEqual(self.fetch.call_count, 2)  # one crawl per store, reused for the new ZIP
        self.assertEqual(self.charts.call_count, 2)  # zone charts are kept too
        self.assertEqual(snapshot["destination_zip"], "10001")
        self.assertEqual({k: v["zone"] for k, v in snapshot["stores"].items()}, {"raghouse": 8, "tvf": 6})
        cartoon = next(lot for lot in snapshot["lots"] if lot["title"] == "Cartoon T-Shirts 60 pcs")
        self.assertEqual(cartoon["ship_est"], 83.3)  # 29 lb, zone 8: ($59.61 + $6.50) x 1.26
        self.assertEqual(box_scout.read_state()["prefs"]["recent_zips"], ["10001", "70115"])

    def test_a_zip_outside_the_rate_table_is_refused(self):
        with self.assertRaisesRegex(ValueError, "48 contiguous states"):
            box_scout.set_prefs(zip="96815")
        self.assertEqual(box_scout.read_state()["prefs"]["recent_zips"], ["70115"])

    def test_a_store_that_fails_is_reported_and_the_other_still_counts(self):
        def fetch(store):
            if store == "raghouse":
                raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
            return CATALOGS[store]

        self.fetch.side_effect = fetch
        with self._models():
            snapshot = box_scout.refresh()
        self.assertIn("Raghouse did not return its catalog", snapshot["stores"]["raghouse"]["error"])
        self.assertIsNone(snapshot["stores"]["tvf"]["error"])
        self.assertEqual({lot["store"] for lot in snapshot["lots"]}, {"tvf"})


class SourcingRouteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mock.patch.object(box_scout, "state_path", return_value=Path(tmp.name) / "sourcing.json").start()
        mock.patch.object(box_scout, "research_available", return_value=False).start()
        self.background = mock.patch.object(box_scout, "refresh_in_background").start()
        self.addCleanup(mock.patch.stopall)
        self.client = TestClient(app)

    def test_first_visit_starts_a_refresh(self):
        body = self.client.get("/api/sourcing").json()
        self.assertIsNone(body["snapshot"])
        self.assertEqual(body["prefs"]["budget"], 300.0)
        self.assertEqual(body["prefs"]["zip"], "70115")
        self.background.assert_called_once()

    def test_saving_the_budget_rebuilds_the_list(self):
        body = self.client.put("/api/sourcing/prefs", json={"budget": 500, "raghouse_vip": True}).json()
        self.assertEqual(body["prefs"]["budget"], 500)
        self.assertTrue(body["prefs"]["raghouse_vip"])
        self.background.assert_called_once()
        self.background.assert_called_once_with(recrawl=False)
        self.assertEqual(self.client.put("/api/sourcing/prefs", json={"budget": 0}).status_code, 422)
        self.assertEqual(self.client.put("/api/sourcing/prefs", json={"zip": "7011"}).status_code, 422)
        hawaii = self.client.put("/api/sourcing/prefs", json={"zip": "96815"})
        self.assertEqual(hawaii.status_code, 422)
        self.assertIn("48 contiguous states", hawaii.json()["detail"])

    def test_saved_snapshot_is_served(self):
        with mock.patch.object(box_scout.scout(), "fetch_catalog", side_effect=lambda store: CATALOGS[store]), \
                mock.patch.object(box_scout.scout(), "fetch_zone_chart", side_effect=ZONE_CHARTS.__getitem__), \
                mock.patch.dict(box_scout._catalogs, clear=True), \
                mock.patch("vendoo_studio.services.comp_research.model_search", return_value=None):
            box_scout.refresh()
        body = self.client.get("/api/sourcing").json()
        self.assertEqual(body["snapshot"]["destination_zip"], "70115")
        self.assertEqual(set(body["snapshot"]["stores"]), {"raghouse", "tvf"})
