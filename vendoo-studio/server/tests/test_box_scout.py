from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services import box_scout
from vendoo_studio.services.inventory_analytics import AnalyticsItem
from vendoo_studio.services.sourcing_seasonality import historical_windows, selling_window
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
    _raghouse("Cartoon T-Shirts 65 pcs", "95.00", 12701, vid=7),
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

def _papercrane(title: str, price: float, pcs: int, *, grade="b", weight_oz=320, state="Texas", seller="ed2k",
                exact_ship=True, category="Tops", status="active", lid="aaaa0001", posted="2026-09-20T03:29:15+00:00"):
    return {
        "id": f"{lid}-0000-0000-0000-000000000000", "slug": f"{title.lower().replace(' ', '-')}-{lid}",
        "title": title, "price": f"$${price}", "priceCents": round(price * 100), "moq": f"{pcs} units", "moqCount": pcs,
        "category": category, "department": "unisex", "state": state, "seller": seller, "sellerType": "reseller",
        "bundleType": "wholesale", "isBale": False, "status": status, "accuracy": "exact", "conditionGrade": grade,
        "sizeRange": "S–XL", "weightOz": weight_oz, "boxL": 18, "boxW": 14, "boxH": 12, "boxCount": 1,
        "shippingCents": 0, "shipTotalCents": 0, "shipBuyerPct": 100, "shipExact": exact_ship, "savesCount": 0,
        "postedAt": posted, "editedAt": None, "img": "", "images": [], "videos": [], "videoUrl": None,
    }


PAPERCRANE = [
    _papercrane("Cartoon tees 30pc", 240, 30, grade="b", weight_oz=240, state="Texas", lid="aaaa0001"),
    _papercrane("Vintage graphic tees 20pc", 200, 20, grade="a", weight_oz=160, state="Michigan", lid="aaaa0002",
                exact_ship=False),
    _papercrane("As-is cartoon tees 40pc", 100, 40, grade="c", lid="aaaa0003"),
    _papercrane("Mixed hat lot", 80, 30, grade="b", category="Accessories", lid="aaaa0004"),
    _papercrane("Cartoon tees from the sellers page", 150, 15, grade=None, weight_oz=None, state="Texas", lid="aaaa0005",
                posted=None),
]

CATALOGS = {"raghouse": RAGHOUSE, "tvf": TVF, "papercrane": PAPERCRANE}
ZONES = {"raghouse": 6, "tvf": 5, "papercrane": {"Texas": 4, "Michigan": 6}}  # to 70115
# USPS charts by origin, trimmed to the destinations these tests use.
ZONE_CHARTS = {
    "850": {"701": 6, "100": 8, "850": 1, "967": 8},
    "330": {"701": 5, "100": 6, "850": 8, "967": 8},
    "752": {"701": 4, "100": 7, "850": 5, "967": 8},
    "482": {"701": 6, "100": 5, "850": 7, "967": 8},
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
        self.assertNotIn("Recycle Cartoon T-Shirts 70 pcs", lots)  # Recycle lots need TLC
        self.assertNotIn("Y2K Blouses 40 pcs", lots)  # VIP only unless asked for

    def test_shipping_uses_each_stores_zone_and_whole_pounds(self):
        lots = {lot["title"]: lot for lot in self._lots()}
        # Raghouse ships FedEx. Zone 6, 12701 g bills as 29 lb.
        # ($44.68 + $6.45 residential) x 1.29 fuel x 0.5147, order #83897.
        self.assertEqual(lots["Cartoon T-Shirts 60 pcs"]["ship_est"], 33.95)
        # TVF, zone 5: 2722 g bills as 7 lb, ($19.26 + $6.50) x 1.26.
        self.assertEqual(lots["Wholesale Vintage Graphic T-Shirts (10 Pieces) · A Grade"]["ship_est"], 32.46)

    def test_raghouse_shipping_matches_the_light_jackets_checkout(self):
        # Order #83897: Light Jackets Unsorted 26 pcs, 13154 g, $49 box, $33.95 shipping to 70115.
        grams = 13154
        est = self.s.ship_estimate(grams / 453.59237, self.cfg, "raghouse", 6)
        self.assertEqual(est, 33.95)
        self.assertEqual(round(49 + est), 83)

    def test_zone_for_a_destination(self):
        chart = ZONE_CHARTS["850"]
        self.assertEqual(self.s.zone_for(chart, "70115"), 6)
        self.assertEqual(self.s.zone_for(chart, "85043"), 2)  # local zone 1 bills as zone 2
        self.assertIsNone(self.s.zone_for(chart, "96815"))  # Hawaii: outside the rate table
        self.assertIsNone(self.s.zone_for(chart, "7011"))

    def test_buy_list_keeps_to_budget_one_lot_per_theme(self):
        resale = {"cartoon t-shirts": 15, "blank t-shirts": 6, "flannel shirts": 12}
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(cost_per_piece=0), resale)[1]
        plan = self.s.buy_list(rows, self.cfg, budget=200, min_roi=0.5, cost_per_piece=0)
        picked = [lot["title"] for cart in plan["carts"] for lot in cart["lots"]]
        # The $95 cartoon lot shares a theme with the cheaper one, so it stays off the list.
        self.assertEqual(picked, ["Cartoon T-Shirts 60 pcs", "Plain Blank Tees 80 pcs"])
        self.assertEqual(plan["exclusions"]["raghouse:7"], "same_theme")
        self.assertLessEqual(plan["total"], 200)
        self.assertEqual(plan["carts"][0]["cart_url"], "https://raghouse.com/cart/1:1,4:1")

    def test_window_matches_prioritize_qualifying_boxes_without_changing_profit(self):
        catalogs = {"raghouse": [_raghouse("Flannel Shirts 60 pcs", "60", 12701, vid=10),
                                 _raghouse("Cartoon T-Shirts 60 pcs", "60", 12701, vid=11)]}
        resale = {"flannel shirts": 20, "cartoon t-shirts": 30}
        ordinary = self.s.score_lots(catalogs, self.cfg, ZONES, self.s.Filters(), resale)[1]
        seasonal = self.s.score_lots(catalogs, self.cfg, ZONES, self.s.Filters(trend=("flannel",)), resale)[1]
        self.assertEqual({r["theme"]: r["expected_profit"] for r in ordinary},
                         {r["theme"]: r["expected_profit"] for r in seasonal})
        def picked(rows, min_roi=1):
            plan = self.s.buy_list(rows, self.cfg, budget=100, min_roi=min_roi)
            return [r["theme"] for c in plan["carts"] for r in c["lots"]]
        self.assertEqual(picked(ordinary), ["cartoon t-shirts"])
        self.assertEqual(picked(seasonal), ["flannel shirts"])
        flannel = next(r for r in seasonal if r["theme"] == "flannel shirts")
        self.assertEqual(picked(seasonal, flannel["roi"] + 0.1), ["cartoon t-shirts"])
        flannel["resale_low"] = 1
        self.assertEqual(picked(seasonal), ["cartoon t-shirts"])
        flannel["resale_per_pc"] = None
        flannel["roi"] = None
        self.assertEqual(picked(seasonal), ["cartoon t-shirts"])

    def test_free_shipping_once_a_store_order_clears_its_threshold(self):
        resale = {"flannel shirts": 12}
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(cost_per_piece=0), resale)[1]
        cart = self.s.buy_list(rows, self.cfg, budget=1000, min_roi=0, cost_per_piece=0)["carts"][0]
        self.assertEqual(cart["store"], "tvf")
        self.assertTrue(cart["free_shipping"])
        lot = cart["lots"][0]
        self.assertEqual(lot["title"], "Men's Flannel Shirts Bale · 100LB")  # one bale per theme
        self.assertEqual((lot["ship_est"], lot["landed"]), (0, lot["price"]))

    def test_a_store_factor_scales_only_that_stores_resale_prices(self):
        resale = {"cartoon t-shirts": 15, "flannel shirts": 12}
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(), resale, {"raghouse": 0.5})[1]
        cartoon = next(r for r in rows if r["theme"] == "cartoon t-shirts")
        flannel = next(r for r in rows if r["theme"] == "flannel shirts")
        self.assertEqual((cartoon["resale_per_pc"], cartoon["resale_factor"]), (7.5, 0.5))
        self.assertEqual((flannel["resale_per_pc"], flannel["resale_factor"]), (12, 1.0))

    def test_past_overperformance_cannot_raise_current_researched_prices(self):
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(),
                                 {"cartoon t-shirts": 15}, {"raghouse": 1.5})[1]
        cartoon = next(r for r in rows if r["theme"] == "cartoon t-shirts")
        self.assertEqual((cartoon["resale_per_pc"], cartoon["resale_factor"]), (15, 1.0))

    def test_research_allowance_is_shared_between_stores(self):
        rows = [{"store": "raghouse", "theme": f"rag-{i}", "demand": 2, "trend_hits": []}
                for i in range(30)]
        rows += [{"store": "tvf", "theme": f"tvf-{i}", "demand": 1, "trend_hits": []}
                 for i in range(30)]
        themes = self.s.research_themes(rows, limit=24)
        self.assertEqual(sum(t.startswith("tvf-") for t in themes), 12)
        self.assertEqual(sum(t.startswith("rag-") for t in themes), 12)

    def test_free_shipping_is_applied_before_budget_and_roi_checks(self):
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(cost_per_piece=0), {"flannel shirts": 20})[1]
        plan = self.s.buy_list(rows, self.cfg, budget=225, cost_per_piece=0)
        self.assertEqual(plan["total"], 225)
        self.assertTrue(plan["carts"][0]["free_shipping"])
        self.assertIn("50LB", plan["carts"][0]["lots"][0]["title"])

    def test_crossing_free_shipping_threshold_reprices_the_whole_cart(self):
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(cost_per_piece=0), {"vintage graphic t-shirts": 100})[1]
        base = next(r for r in rows if r["store"] == "tvf" and r["roi"] is not None)
        rows = [self.s.price_lot({**base, "theme": f"theme-{i}", "variant_id": 100 + i, "price": 110}, 45, 100)
                for i in range(2)]
        plan = self.s.buy_list(rows, self.cfg, budget=220)
        self.assertEqual(plan["total"], 220)
        self.assertEqual(len(plan["carts"][0]["lots"]), 2)
        self.assertEqual(plan["carts"][0]["shipping"], 0)
        self.assertEqual(rows[0]["ship_est"], 45)  # source rows stay unchanged


    def test_wholesale_demand_cannot_inflate_resale_sales(self):
        base = next(r for r in self._lots() if r["store"] == "raghouse")
        slow = self.s.price_lot({**base, "demand": 0.1}, 30, 30)
        popular = self.s.price_lot({**base, "demand": 10, "trend_hits": ["cartoon"]}, 30, 30)
        self.assertEqual(slow["sell_through"], 0.5)
        self.assertEqual(slow["expected_profit"], popular["expected_profit"])

    def test_operating_allowance_and_break_even_include_unsold_pieces(self):
        row = {"price": 60, "pcs": 20, "usable_pcs": 10, "demand": 50, "resale_low": 15}
        priced = self.s.price_lot(row, 20, 20, sell_through=0.6, fees=0.25, cost_per_piece=2)
        self.assertEqual(priced["operating_cost"], 20)
        self.assertEqual(priced["expected_revenue"], 90)
        self.assertEqual(priced["expected_profit"], -10)
        self.assertEqual(priced["break_even_pcs"], 7)
        # Half the 6 planned sales at the $15 low: 3 x ($15 x 0.75 - $2) - $80 landed.
        self.assertEqual(priced["downside_profit"], -52.25)

    def test_lower_sales_test_charges_operating_costs_on_the_pieces_that_sell(self):
        # A $66 box of 40 usable jackets at $30 (low $18) with a 500% return must not fail
        # the test only because prep is charged on pieces the scenario never lists.
        row = {"price": 36, "pcs": 45, "usable_pcs": 40.5, "demand": 1, "resale_low": 18}
        priced = self.s.price_lot(row, 30, 30)
        self.assertGreater(priced["roi"], 4)
        self.assertGreater(priced["downside_profit"], 0)

    def test_themes_are_resale_categories(self):
        for title, expected in (
            ("Abbie Recycle Tees & Tops 87 pcs", "tops"),
            ("Dirty White Graphic + Vintage + Concert Tees 57 pcs", "vintage band t-shirts"),
            ("Aerie Abercrombie Hollister American Eagle Aeropostale Sweatshirts & Joggers 23 pcs", "brand name pants"),
            ("Crop Blouses 49 pcs", "blouses"),
            ("Popcorn Tops + Denim Mini Skirts 18 pcs", "denim mini skirts"),
            ("Wholesale Champion Sweatshirts (10 Pieces) · Modern Mix", "sports brand sweatshirts"),
            ("Wholesale Levis Cutoff Shorts (10 Pieces) · 33\" & Down", "levis denim shorts"),
            ("Mens Short Sleeve Check Shirts 42 pcs", "shirts"),
            ("Josh x Ciara Y2K Variety Mix 36 pcs", "y2k mixed clothing"),
            ("Women's J. Crew Mix", "premium brand mixed clothing"),
        ):
            with self.subTest(title=title):
                self.assertEqual(self.s.theme(title), expected)

    def test_papercrane_lots_carry_their_seller_state_grade_and_shipping_terms(self):
        lots = {lot["title"]: lot for lot in self._lots()}
        tees = lots["Cartoon tees 30pc"]
        self.assertEqual((tees["grade"], tees["origin"], tees["seller"], tees["lbs"], tees["listed"]),
                         ("standard", "Texas", "ed2k", 15.0, "2026-09-20"))
        self.assertEqual(tees["url"], "https://www.papercranewholesale.com/shop/cartoon-tees-30pc-aaaa0001")
        # UPS zone 4 from Texas, 15 lb, plus card processing at 2.9% + $0.30 on the lot price.
        self.assertGreater(tees["ship_est"], 0)
        self.assertEqual(tees["checkout_fee"], 7.26)
        self.assertEqual(tees["landed"], round(240 + tees["ship_est"] + 7.26, 2))
        # Shipping in the price: nothing added for it, the Cream grade yields 95%.
        vintage = lots["Vintage graphic tees 20pc"]
        self.assertEqual((vintage["grade"], vintage["free_shipping"], vintage["ship_est"], vintage["usable_pcs"]),
                         ("a", True, 0.0, 19.0))
        # A sellers-page card has no grade or weight: ungraded, weight estimated from the pieces.
        card = lots["Cartoon tees from the sellers page"]
        self.assertEqual((card["grade"], card["lbs_estimated"], card["listed"]), ("good", True, None))
        # Mixed/As-Is lots and accessories are never lots.
        self.assertNotIn("As-is cartoon tees 40pc", lots)
        self.assertNotIn("Mixed hat lot", lots)

    def test_papercrane_feed_is_parsed_from_the_home_and_sellers_pages(self):
        home = "0:" + json.dumps({"listings": [PAPERCRANE[0], PAPERCRANE[1]]}) + "\n1:" + json.dumps(["$", "div", {"l": PAPERCRANE[0]}])
        sellers = "0:" + json.dumps([{"username": "ed2k", "lots": [
            {k: v for k, v in PAPERCRANE[4].items() if k not in ("weightOz", "conditionGrade", "postedAt")},
            {k: v for k, v in PAPERCRANE[0].items() if k not in ("weightOz", "conditionGrade")}]}])
        with mock.patch.object(self.s, "_rsc", side_effect=lambda path: home if path == "/" else sellers), \
                mock.patch.object(self.s.time, "sleep"):
            products = self.s.fetch_papercrane()
        self.assertEqual([p["id"][:8] for p in products], ["aaaa0001", "aaaa0002", "aaaa0005"])
        self.assertEqual(products[0]["weightOz"], 240)  # the home page's full lot wins over the card

    def test_a_marketplace_ships_from_each_sellers_state(self):
        cfg = self.s.load_shipping()
        self.assertEqual(self.s.origin_zip3s("papercrane", PAPERCRANE, cfg), {"Michigan": "482", "Texas": "752"})
        self.assertEqual(self.s.origin_zip3s("tvf", TVF, cfg), {"": "330"})
        self.assertEqual(self.s.lot_zone(ZONES, "papercrane", {"origin": "Texas"}), 4)
        self.assertIsNone(self.s.lot_zone(ZONES, "papercrane", {"origin": "Alaska"}))
        self.assertEqual(self.s.lot_zone(ZONES, "tvf", {}), 5)

    def test_a_marketplace_cart_link_opens_the_first_lot(self):
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(cost_per_piece=0),
                                 {"cartoon t-shirts": 60, "vintage graphic t-shirts": 60})[1]
        plan = self.s.buy_list([r for r in rows if r["store"] == "papercrane"], self.cfg, budget=1000, cost_per_piece=0)
        cart = plan["carts"][0]
        self.assertFalse(cart["cart_fills"])
        self.assertEqual(cart["cart_url"], cart["lots"][0]["url"])
        shopify = self.s.buy_list([r for r in rows if r["store"] == "raghouse"], self.cfg, budget=1000, cost_per_piece=0)
        self.assertTrue(shopify["carts"][0]["cart_fills"])

    def test_tvf_lower_grades_are_never_lots(self):
        catalogs = {"tvf": [_tvf("Cartoon T-Shirts (70 Pieces)", [
            ("A Grade", "90.00", 12701, True), ("A/B Grade", "60.00", 12701, True), ("B Grade", "30.00", 12701, True),
            ("B/C Grade", "20.00", 12701, True), ("C Grade", "10.00", 12701, True)], vid=500)]}
        rows = self.s.score_lots(catalogs, self.cfg, ZONES, self.s.Filters(), {"cartoon t-shirts": 40})[1]
        self.assertEqual([r["title"] for r in rows], ["Cartoon T-Shirts (70 Pieces) · A Grade"])

    def test_tvf_brand_mix_pieces_are_estimated_from_shipping_weight(self):
        catalogs = {"tvf": [_tvf("Women's J. Crew Mix", [("Default Title", "200.00", 9072, True)], vid=600)]}
        lot = self.s.score_lots(catalogs, self.cfg, ZONES, self.s.Filters())[1][0]
        # 20 lb less 1 lb packaging at 1.6 mixed pieces per pound.
        self.assertEqual((lot["pcs"], lot["pcs_estimated"], lot["lbs"]), (30, True, 20.0))

    def test_high_roi_with_a_losing_lower_sales_scenario_does_not_qualify(self):
        rows = self.s.score_lots(CATALOGS, self.cfg, ZONES, self.s.Filters(),
                                 {"cartoon t-shirts": 40}, resale_low={"cartoon t-shirts": 3})[1]
        good = next(r for r in rows if r["grade"] == "good" and r["theme"] == "cartoon t-shirts")
        self.assertGreater(good["roi"], 1)
        plan = self.s.buy_list([good], self.cfg, budget=1000)
        self.assertEqual(plan["carts"], [])
        self.assertEqual(plan["exclusions"]["raghouse:1"], "downside")

    def test_two_boxes_can_qualify_together_when_neither_passes_alone(self):
        base = next(r for r in self._lots() if r["store"] == "tvf" and r["grade"] == "a")
        rows = [self.s.price_lot({**base, "theme": f"bundle-{i}", "variant_id": 700 + i,
                                  "price": 110, "resale_low": 70}, 45, 70) for i in range(2)]
        before = [dict(r) for r in rows]
        self.assertEqual(self.s.buy_list(rows[:1], self.cfg, budget=220)["carts"], [])
        plan = self.s.buy_list(rows, self.cfg, budget=220)
        self.assertEqual(plan["total"], 220)
        self.assertEqual(len(plan["carts"][0]["lots"]), 2)
        self.assertTrue(plan["carts"][0]["free_shipping"])
        self.assertTrue(all(p["downside_profit"] >= 0 for p in plan["carts"][0]["lots"]))
        self.assertEqual(rows, before)

    def test_free_shipping_pair_still_cannot_exceed_budget(self):
        base = next(r for r in self._lots() if r["store"] == "tvf" and r["grade"] == "a")
        rows = [self.s.price_lot({**base, "theme": f"bundle-{i}", "variant_id": 800 + i,
                                  "price": 110, "resale_low": 70}, 45, 70) for i in range(2)]
        self.assertEqual(self.s.buy_list(rows, self.cfg, budget=219.99)["carts"], [])

    def test_budget_rejection_accounts_for_selected_carts_free_shipping(self):
        base = next(r for r in self._lots() if r["store"] == "tvf" and r["grade"] == "a")
        rows = [self.s.price_lot({**base, "theme": f"theme-{i}", "variant_id": 900 + i,
                                  "price": 110, "resale_low": 100}, 45, 100) for i in range(3)]
        plan = self.s.buy_list(rows, self.cfg, budget=300)
        self.assertEqual(plan["total"], 220)
        self.assertEqual(plan["exclusions"]["tvf:902"], "budget")


def _search(label: str, answers: list[str]) -> ModelSearch:
    calls = iter(answers)

    async def search(messages):
        return {"answer": next(calls), "sources": []}

    return ModelSearch(label, search)


def _price_evidence(theme: str, per_piece: float, vid: int = 1) -> dict:
    return {
        "theme": theme,
        "comps": [{
            "url": f"https://www.ebay.com/itm/{vid + index}",
            "title": f"{theme} used clothing",
            "currency": "USD",
            "sold_at": (box_scout._now().date() - timedelta(days=index + 1)).isoformat(),
            "snippet": f"Sold for US ${per_piece:.2f} on {(box_scout._now().date() - timedelta(days=index + 1)).isoformat()}",
        } for index in range(3)],
    }


def _planning_context(prefs, now):
    window = selling_window(prefs, now.date())
    return {"window": window, "seller_history": {
        "periods": historical_windows(window, now.date()), "dated_recorded_sales": 0,
        "matching_window_sales": 0, "excluded_incomplete_or_invalid": 0,
        "minimum_group_sales": 5, "groups": [], "coverage": "imported recorded sales; inventory exposure unknown",
    }}


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
        mock.patch.object(box_scout, "planning_context", side_effect=_planning_context).start()
        mock.patch.object(box_scout, "_calibration", return_value={}).start()
        mock.patch.object(box_scout, "_shipping_calibration", return_value={}).start()
        mock.patch.object(box_scout, "_own_sales", return_value=[]).start()
        mock.patch.object(box_scout, "_announce_new_picks").start()
        mock.patch.dict(box_scout._catalogs, clear=True).start()
        self.addCleanup(mock.patch.stopall)

    def _models(self, search=None):
        return mock.patch("vendoo_studio.services.comp_research.model_search", return_value=search)

    def test_researches_trends_and_prices_then_builds_the_buy_list(self):
        prices = json.dumps({"prices": [
            _price_evidence("cartoon t-shirts", 30),
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
        self.assertEqual(lots[0]["title"], "Cartoon T-Shirts 60 pcs")
        self.assertEqual(lots[0]["comps_count"], 3)
        self.assertNotIn("comps", lots[0])  # examples are served on request, not kept per lot
        self.assertTrue(snapshot["research"])
        shown = box_scout.evidence("cartoon t-shirts")
        self.assertEqual([c["url"] for c in shown["comps"]], [f"https://www.ebay.com/itm/{i}" for i in range(1, 4)])
        self.assertEqual((shown["per_piece"], shown["source"]), (30, "ChatGPT"))
        self.assertIsNone(box_scout.evidence("hawaiian shirts"))

    def test_both_store_choices_use_the_same_budget_and_keep_evidence(self):
        prices = json.dumps({"prices": [
            _price_evidence("cartoon t-shirts", 30),
            _price_evidence("vintage graphic t-shirts", 100, vid=100),
        ]})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}', prices, "{}"])):
            snapshot = box_scout.refresh()
        self.assertEqual(set(snapshot["store_buy_lists"]), {"raghouse", "tvf", "papercrane"})
        for store, plan in snapshot["store_buy_lists"].items():
            self.assertEqual(plan["budget"], 300)
            self.assertLessEqual(plan["total"], 300)
            self.assertTrue(plan["carts"])
            self.assertEqual({c["store"] for c in plan["carts"]}, {store})
            self.assertTrue(plan["carts"][0]["lots"][0]["comps_count"])

    def test_old_snapshot_cache_is_rebuilt_without_losing_preferences(self):
        self.state_file.write_text(json.dumps({"prefs": {"budget": 180}, "snapshot": {"updated_at": "old"}}))
        state = box_scout.read_state()
        self.assertIsNone(state["snapshot"])
        self.assertEqual(state["prefs"]["budget"], 180)
        self.assertTrue(box_scout.refresh_is_due())

    def test_a_snapshot_from_another_build_is_dropped_before_the_page_reads_it(self):
        # 0.1.219 served a snapshot whose lots lacked a field the page's model requires,
        # and the whole Sourcing request failed with a 500 until the next refresh.
        with self._models():
            box_scout.refresh()
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["snapshot"]["format"], box_scout.SNAPSHOT_FORMAT)
        for lot in state["snapshot"]["lots"]:
            del lot["comps_count"]
        state["snapshot"]["format"] = box_scout.SNAPSHOT_FORMAT - 1
        self.state_file.write_text(json.dumps(state))
        from vendoo_studio.routes.sourcing import _response

        with mock.patch.object(box_scout, "research_available", return_value=False):
            self.assertIsNone(_response().snapshot)
        self.assertTrue(box_scout.refresh_is_due())

    def test_cached_research_is_not_repeated(self):
        prices = json.dumps({"prices": [_price_evidence("cartoon t-shirts", 30)]})
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

    def test_selling_window_change_researches_new_themes_but_reuses_recent_prices(self):
        prices = json.dumps({"prices": [_price_evidence("cartoon t-shirts", 30)]})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}', prices, "{}"])):
            box_scout.refresh()
        box_scout.set_prefs(ready_in_weeks=8, selling_window_weeks=6)
        self.assertTrue(box_scout.refresh_is_due())
        trends = mock.AsyncMock(return_value=(["flannel"], "ChatGPT"))
        prices = mock.AsyncMock(return_value=({}, None))
        with self._models(_search("ChatGPT", [])), \
                mock.patch.object(box_scout, "_research_trends", trends), \
                mock.patch.object(box_scout, "_research_prices", prices):
            snapshot = box_scout.refresh(recrawl=False)
        self.assertEqual(self.fetch.call_count, len(CATALOGS))
        self.assertEqual(snapshot["seasonality"]["window"]["ready_in_weeks"], 8)
        self.assertEqual(snapshot["seasonality"]["window"]["selling_window_weeks"], 6)
        trends.assert_called_once()
        self.assertNotIn("cartoon t-shirts", [theme for call in prices.call_args_list for theme in call.args[0]])
        self.assertTrue(any(lot["trend_hits"] == ["flannel"] for lot in snapshot["lots"]))
        self.assertFalse(box_scout.refresh_is_due())

    def test_changed_window_discards_old_themes_without_a_model(self):
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}', "{}", "{}", "{}"])):
            box_scout.refresh()
        box_scout.set_prefs(ready_in_weeks=0)
        snapshot = box_scout.refresh(recrawl=False, research=False)
        self.assertEqual(box_scout.read_state()["trend"]["terms"], [])
        self.assertTrue(all(not lot["trend_hits"] for lot in snapshot["lots"]))

    def test_research_prompts_include_dated_window_and_history(self):
        ask = mock.AsyncMock(return_value=(None, None))
        context = _planning_context(box_scout.DEFAULT_PREFS, datetime(2026, 10, 7, tzinfo=UTC))
        context["seller_history"]["groups"] = [{"category_path": "Clothing > Coats", "count": 5}]
        import asyncio
        with mock.patch.object(box_scout, "_ask", ask):
            asyncio.run(box_scout._research_trends(context))
            asyncio.run(box_scout._research_prices(["coats"], {"coats": "Coats 20 pcs"}, context))
        for call in ask.call_args_list:
            self.assertIn("2026-11-04", call.args[1])
            self.assertIn("2026-12-01", call.args[1])
            self.assertIn("Clothing > Coats", call.args[1])
            self.assertIn("not exposure-adjusted demand", call.args[1])
            self.assertIn("recent sold comps for current prices", call.args[1])

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
        self.assertEqual(self.fetch.call_count, len(CATALOGS))  # one crawl per store, reused for the new ZIP
        self.assertEqual(self.charts.call_count, len(ZONE_CHARTS))  # zone charts are kept too
        self.assertEqual(snapshot["destination_zip"], "10001")
        self.assertEqual({k: v["zone"] for k, v in snapshot["stores"].items()}, {"raghouse": 8, "tvf": 6, "papercrane": None})
        cartoon = next(lot for lot in snapshot["lots"] if lot["title"] == "Cartoon T-Shirts 60 pcs")
        self.assertEqual(cartoon["ship_est"], 44.04)  # FedEx 29 lb, zone 8: ($59.88 + $6.45) x 1.29 x 0.5147
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
        self.assertEqual({lot["store"] for lot in snapshot["lots"]}, {"tvf", "papercrane"})
        self.assertEqual((snapshot["stores"]["papercrane"]["zone"], snapshot["stores"]["papercrane"]["origins"]), (None, 2))


    def test_preferences_saved_during_research_survive_and_request_a_rebuild(self):
        async def research(themes, examples, context):
            box_scout.set_prefs(budget=200, min_roi=1.5, zip="10001", raghouse_vip=True,
                                sell_through=0.6, fees=0.25, cost_per_piece=1.5,
                                ready_in_weeks=8, selling_window_weeks=6)
            return box_scout.clean_prices([_price_evidence("cartoon t-shirts", 40)], set(themes)), "ChatGPT"

        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}'])), \
                mock.patch.object(box_scout, "_research_prices", side_effect=research):
            first = box_scout.refresh()
        prefs = box_scout.read_state()["prefs"]
        self.assertEqual(prefs["budget"], 200)
        self.assertEqual(prefs["zip"], "10001")
        self.assertEqual(first["preferences"]["budget"], 300)
        self.assertEqual(first["seasonality"]["window"]["ready_in_weeks"], 4)
        self.assertEqual(prefs["ready_in_weeks"], 8)
        self.assertTrue(box_scout.refresh_is_due())
        second = box_scout.refresh(recrawl=False, research=False)
        self.assertEqual(second["preferences"], {k: prefs[k] for k in box_scout.PLAN_PREFS})
        self.assertFalse(box_scout.refresh_is_due())

    def test_old_price_only_cache_cannot_qualify(self):
        box_scout._write_state({"prefs": box_scout.DEFAULT_PREFS,
                                "resale": {"cartoon t-shirts": {"per_piece": 100,
                                                               "updated_at": box_scout._now().isoformat()}}})
        with self._models():
            snapshot = box_scout.refresh()
        self.assertEqual(snapshot["buy_list"]["carts"], [])
        self.assertTrue(all(p["resale_per_pc"] is None for p in snapshot["lots"]))

    def test_sources_and_costs_are_in_the_api_snapshot(self):
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}',
                                               json.dumps({"prices": [_price_evidence("cartoon t-shirts", 40)]}), "{}"])):
            box_scout.refresh()
        from vendoo_studio.routes.sourcing import SourcingSnapshot

        snapshot = SourcingSnapshot.model_validate(box_scout.read_state()["snapshot"])
        lot = snapshot.buy_list.carts[0].lots[0]
        self.assertEqual(lot.comps_count, 3)
        self.assertEqual(lot.research_source, "ChatGPT")
        self.assertGreater(lot.operating_cost, 0)
        self.assertGreaterEqual(lot.downside_profit, 0)


def _sale(title: str, price: float, days_ago: int, conv: str = "c1", marketplace: str = "eBay") -> AnalyticsItem:
    sold_at = box_scout._now() - timedelta(days=days_ago)
    return AnalyticsItem(conversation_id=conv, title=title, status="sold", price=price, cost=None, brand="",
                         category="", sold_price=price, sold_at=sold_at, listed_at=None, marketplace=marketplace,
                         days_listed=None)


class ShippingAndVipTest(RefreshTest):
    def test_recorded_orders_set_a_stores_shipping_factor(self):
        mock.patch.object(box_scout, "_shipping_calibration", return_value={
            "tvf": {"factor": 0.5, "orders": 2, "needed": 2}, "raghouse": {"factor": None, "orders": 1, "needed": 2},
        }).start()
        with self._models():
            snapshot = box_scout.refresh()
        graphic = next(lot for lot in snapshot["lots"] if lot["title"].startswith("Wholesale Vintage Graphic"))
        # Half of the $32.46 UPS list estimate; Raghouse keeps the factor from shipping.json.
        self.assertEqual((graphic["ship_list"], graphic["ship_est"]), (32.46, 16.23))
        self.assertEqual(snapshot["shipping"]["factors"], {"raghouse": 0.5147, "tvf": 0.5, "papercrane": 1.0})
        self.assertEqual(snapshot["shipping"]["calibration"]["tvf"]["orders"], 2)

    def test_vip_upside_counts_members_only_boxes_that_would_qualify(self):
        prices = json.dumps({"prices": [_price_evidence("y2k blouses", 40)]})
        with self._models(_search("ChatGPT", ['{"terms": ["y2k"]}', prices, "{}"])):
            snapshot = box_scout.refresh()
        self.assertEqual(snapshot["buy_list"]["carts"], [])  # the Y2K lot is VIP only
        self.assertEqual(snapshot["vip_upside"]["boxes"], 1)
        self.assertGreater(snapshot["vip_upside"]["extra_profit"], 0)
        self.assertEqual(snapshot["vip_upside"]["monthly_fee"], 64)
        box_scout.set_prefs(raghouse_vip=True)
        with self._models():
            snapshot = box_scout.refresh(recrawl=False, research=False)
        self.assertIsNone(snapshot["vip_upside"])
        self.assertTrue(snapshot["buy_list"]["carts"][0]["lots"][0]["vip"])


class OwnSalesTest(RefreshTest):
    SALES = [
        _sale("Vintage 90s Harley Davidson T-Shirt XL", 28, 3, "c1"),
        _sale("Cartoon Looney Tunes Tee Men's L", 32, 10, "c2", "Depop"),
        _sale("Cartoon Garfield T-Shirt", 28, 20, "c3"),
        _sale("Cartoon Simpsons Tee", 30, 25, "c4"),
        _sale("Cartoon Lunchbox", 40, 2, "c5"),  # not a garment
        _sale("Cartoon Snoopy Tee", 24, 60, "c6"),  # older than 30 days: context only
    ]

    def test_own_sales_qualify_a_theme_without_web_research(self):
        mock.patch.object(box_scout, "_own_sales", return_value=self.SALES).start()
        with self._models():
            snapshot = box_scout.refresh()
        lot = snapshot["buy_list"]["carts"][0]["lots"][0]
        self.assertEqual(lot["title"], "Cartoon T-Shirts 60 pcs")
        self.assertEqual((lot["resale_per_pc"], lot["comps_count"], lot["research_source"]), (30, 4, "Your sales"))
        shown = box_scout.evidence("cartoon t-shirts")
        self.assertEqual([c["conversation_id"] for c in shown["comps"]], ["c2", "c3", "c4", "c6"])
        self.assertEqual(shown["source"], "Your sales")
        self.assertEqual(json.loads(self.state_file.read_text())["resale"], {})  # nothing cached as web research

    def test_own_sales_and_web_sales_price_a_theme_together(self):
        mock.patch.object(box_scout, "_own_sales", return_value=self.SALES[1:3]).start()
        web = json.dumps({"prices": [{**_price_evidence("cartoon t-shirts", 30), "comps": _price_evidence("cartoon t-shirts", 30)["comps"][:1]}]})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}', web, "{}"])):
            snapshot = box_scout.refresh()
        lot = snapshot["buy_list"]["carts"][0]["lots"][0]
        self.assertEqual((lot["resale_per_pc"], lot["comps_count"]), (30, 3))
        comps = box_scout.evidence("cartoon t-shirts")["comps"]
        self.assertEqual({c.get("conversation_id") for c in comps}, {"c2", "c3", None})

    def test_a_theme_needs_every_style_it_names(self):
        sales = [_sale(f"Harley Davidson Tee {i}", 20, i, f"h{i}") for i in range(3)]
        own = box_scout.own_evidence(sales, {"harley davidson t-shirts", "vintage harley davidson t-shirts", "t-shirts"})
        self.assertEqual({name: len(comps) for name, comps in own.items()}, {"harley davidson t-shirts": 3, "t-shirts": 3})


class NewPickNoticeTest(unittest.TestCase):
    def _plan(self, *titles):
        return {"carts": [{"store": "raghouse", "lots": [{"store": "raghouse", "variant_id": i, "title": t, "landed": 93.5}
                                                           for i, t in enumerate(titles)]}]}

    def test_notifies_once_a_box_joins_an_unchanged_plan(self):
        prefs = dict(box_scout.DEFAULT_PREFS)
        previous = {"preferences": {k: prefs[k] for k in box_scout.PLAN_PREFS}, "buy_list": self._plan("Old box")}
        with mock.patch("vendoo_studio.desktop.notify") as notify:
            box_scout._announce_new_picks(previous, self._plan("Old box"), prefs)
            box_scout._announce_new_picks(None, self._plan("Old box", "New box"), prefs)
            box_scout._announce_new_picks(previous, self._plan("Old box", "New box"), {**prefs, "budget": 999})
            notify.assert_not_called()
            box_scout._announce_new_picks(previous, self._plan("Old box", "New box", "Third"), prefs)
        notify.assert_called_once_with("New on your buy list: New box (Raghouse, $94 landed) and 1 more.")


class SourcingRouteTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mock.patch.object(box_scout, "state_path", return_value=Path(tmp.name) / "sourcing.json").start()
        mock.patch.object(box_scout, "research_available", return_value=False).start()
        self.background = mock.patch.object(box_scout, "refresh_in_background").start()
        mock.patch.object(box_scout, "planning_context", side_effect=_planning_context).start()
        mock.patch.object(box_scout, "_calibration", return_value={}).start()
        mock.patch.object(box_scout, "_shipping_calibration", return_value={}).start()
        mock.patch.object(box_scout, "_own_sales", return_value=[]).start()
        mock.patch.object(box_scout, "_announce_new_picks").start()
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

    def test_selling_window_preferences_are_validated_and_rebuild_the_plan(self):
        body = self.client.put("/api/sourcing/prefs", json={"ready_in_weeks": 0, "selling_window_weeks": 8}).json()
        self.assertEqual((body["prefs"]["ready_in_weeks"], body["prefs"]["selling_window_weeks"]), (0, 8))
        self.background.assert_called_once_with(recrawl=False)
        for prefs in ({"ready_in_weeks": -1}, {"ready_in_weeks": 27}, {"ready_in_weeks": True},
                      {"selling_window_weeks": 0}, {"selling_window_weeks": 27}, {"selling_window_weeks": 1.5}):
            self.assertEqual(self.client.put("/api/sourcing/prefs", json=prefs).status_code, 422)

    def test_saved_snapshot_is_served(self):
        with mock.patch.object(box_scout.scout(), "fetch_catalog", side_effect=lambda store: CATALOGS[store]), \
                mock.patch.object(box_scout.scout(), "fetch_zone_chart", side_effect=ZONE_CHARTS.__getitem__), \
                mock.patch.dict(box_scout._catalogs, clear=True), \
                mock.patch("vendoo_studio.services.comp_research.model_search", return_value=None):
            box_scout.refresh()
        body = self.client.get("/api/sourcing").json()
        self.assertEqual(body["snapshot"]["destination_zip"], "70115")
        self.assertEqual(set(body["snapshot"]["stores"]), {"raghouse", "tvf", "papercrane"})


class ResearchEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 5, 12, tzinfo=UTC)
        patcher = mock.patch.object(box_scout, "_now", return_value=self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _clean(self, item):
        return box_scout.clean_prices([item], {"cartoon t-shirts"}, now=self.now)

    def test_prices_come_from_sale_evidence_not_an_ai_estimated_number(self):
        item = _price_evidence("cartoon t-shirts", 20)
        item["per_piece"] = 499
        item["comps"][2]["snippet"] = "Sold for US $40.00"
        cleaned = self._clean(item)["cartoon t-shirts"]
        self.assertEqual(cleaned["per_piece"], 20)
        self.assertEqual((cleaned["low"], cleaned["high"]), (20, 40))

    def test_duplicate_listings_cannot_fill_the_minimum_sample(self):
        item = _price_evidence("cartoon t-shirts", 20)
        item["comps"][1]["url"] = "http://ebay.com/itm/other-title/1?tracking=abc"
        item["comps"][2]["url"] = "https://www.ebay.com/itm/1#tracking"
        self.assertEqual(self._clean(item), {})

    def test_old_future_or_unknown_dates_do_not_qualify(self):
        for date_text in ("2026-07-01", "2026-10-06", "", "not-a-date"):
            with self.subTest(date_text=date_text):
                item = _price_evidence("cartoon t-shirts", 20)
                item["comps"][0]["sold_at"] = date_text
                self.assertEqual(self._clean(item), {})

    def test_sale_sample_needs_three_examples_from_the_last_thirty_days(self):
        item = _price_evidence("cartoon t-shirts", 20)
        for comp in item["comps"][1:]:
            comp["sold_at"] = "2026-09-01"
        self.assertEqual(self._clean(item), {})

    def test_active_or_hidden_offer_prices_cannot_be_called_sales(self):
        for snippet in ("Buy it now $20", "$20 best offer accepted", "$20 sold out", "63 items sold $20",
                        "Not sold $20", "Sold AU $20"):
            with self.subTest(snippet=snippet):
                item = _price_evidence("cartoon t-shirts", 20)
                item["comps"][0]["snippet"] = snippet
                self.assertEqual(self._clean(item), {})

    def test_non_usd_or_non_listing_sources_do_not_qualify(self):
        for changes in ({"currency": "CAD"}, {"url": "https://www.ebay.com/sch/sold"},
                        {"url": "https://ebay.com.evil.example/itm/1"},
                        {"url": "https://[broken/itm/1"}, {"title": ""}):
            with self.subTest(changes=changes):
                item = _price_evidence("cartoon t-shirts", 20)
                item["comps"][0].update(changes)
                self.assertEqual(self._clean(item), {})

    def test_current_competition_caps_estimated_resale(self):
        item = _price_evidence("cartoon t-shirts", 30)
        item["active"] = [{"url": f"https://www.ebay.com/itm/{100 + i}", "title": "Cartoon tee",
                           "currency": "USD", "snippet": f"Buy it now US ${price}"}
                          for i, price in enumerate((10, 15, 20))]
        cleaned = self._clean(item)["cartoon t-shirts"]
        self.assertEqual(cleaned["sold_median"], 30)
        self.assertEqual(cleaned["per_piece"], 15)
        self.assertEqual(cleaned["active_median"], 15)
        self.assertEqual(len(cleaned["active"]), 3)

    def test_thin_competition_sample_is_unknown(self):
        item = _price_evidence("cartoon t-shirts", 30)
        item["active"] = [{"url": "https://www.ebay.com/itm/100", "title": "Cartoon tee",
                           "currency": "USD", "snippet": "Buy it now US $5"}]
        cleaned = self._clean(item)["cartoon t-shirts"]
        self.assertEqual(cleaned["per_piece"], 30)
        self.assertIsNone(cleaned["active_median"])

    def test_research_cache_expires_after_a_week(self):
        cleaned = self._clean(_price_evidence("cartoon t-shirts", 30))["cartoon t-shirts"]
        for age, qualifies in ((6, True), (7, False), (-1, False)):
            entry = {**cleaned, "updated_at": (self.now - timedelta(days=age)).isoformat()}
            fresh = box_scout._fresh_research({"resale": {"cartoon t-shirts": entry}}, self.now, {})
            self.assertEqual(bool(fresh), qualifies)

    def test_cached_dates_are_rechecked_even_before_the_week_is_up(self):
        item = _price_evidence("cartoon t-shirts", 30)
        for comp in item["comps"]:
            comp["sold_at"] = "2026-09-05"
        cleaned = self._clean(item)["cartoon t-shirts"]
        fresh = box_scout._fresh_research({"resale": {"cartoon t-shirts": {
            **cleaned, "updated_at": self.now.isoformat(),
        }}}, self.now + timedelta(days=1), {})
        self.assertEqual(fresh, {})


class RefreshConcurrencyTest(unittest.TestCase):
    def test_background_refresh_reserves_the_job_before_starting_a_thread(self):
        with mock.patch.object(box_scout.threading, "Thread") as thread:
            self.assertTrue(box_scout.refresh_in_background())
            try:
                self.assertTrue(box_scout.refreshing())
                self.assertFalse(box_scout.refresh_in_background())
                thread.assert_called_once()
            finally:
                box_scout._refresh_lock.release()

    def test_failed_background_refresh_releases_the_job(self):
        finished = threading.Event()

        def fail(**kwargs):
            finished.set()
            raise RuntimeError("Research failed")

        with mock.patch.object(box_scout, "_refresh", side_effect=fail), \
                mock.patch.object(box_scout.log, "exception"):
            self.assertTrue(box_scout.refresh_in_background())
            self.assertTrue(finished.wait(2))
            # Acquiring the lock waits for the worker's finally block, not just its entry.
            self.assertTrue(box_scout._refresh_lock.acquire(timeout=2))
            box_scout._refresh_lock.release()
        self.assertFalse(box_scout.refreshing())
