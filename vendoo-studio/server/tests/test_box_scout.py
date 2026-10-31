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
from vendoo_studio.services import box_scout, sold_listings
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


    def test_free_shipping_keeps_each_boxs_own_sell_through(self):
        # Two $110 TVF boxes clear the $200 free-shipping line together. Each was
        # picked on its theme's 90% sell-through; the cart must not reprice them at
        # the 30% overall rate, which would put them under the return target.
        rows = [self.s.price_lot({"store": "tvf", "variant_id": i, "theme": f"theme-{i}", "price": 110, "pcs": 40,
                                  "usable_pcs": 36.0, "demand": 1, "trend_hits": [], "vip": False, "resale_low": 20,
                                  "theme_sell_through": 0.9}, 30, 20, sell_through=0.9) for i in range(2)]
        plan = self.s.buy_list(rows, self.cfg, budget=400, min_roi=0.5, sell_through=0.3)
        cart = plan["carts"][0]
        self.assertTrue(cart["free_shipping"])
        self.assertEqual([lot["sell_through"] for lot in cart["lots"]], [0.9, 0.9])
        self.assertTrue(all(lot["roi"] >= 0.5 and lot["ship_est"] == 0 for lot in cart["lots"]))
        self.assertEqual(plan["expected_profit"], round(sum(lot["expected_profit"] for lot in cart["lots"]), 2))

    def test_top_picks_give_each_store_its_best_boxes_whether_or_not_they_qualify(self):
        def box(vid, theme, price, resale, store="raghouse"):
            row = {"store": store, "variant_id": vid, "theme": theme, "price": price, "pcs": 40, "usable_pcs": 36.0,
                   "demand": 1, "trend_hits": [], "vip": False, "resale_low": resale}
            return self.s.price_lot(row, 20, resale)

        rows = [
            box(1, "dresses", 60, 20), box(2, "dresses", 50, 20), box(3, "t-shirts", 60, 20),
            box(4, "jackets", 60, 6),  # priced, but under the return target
            box(5, "skirts", 60, None),  # no sold evidence
            box(6, "hoodies", 900, 40),  # over the budget
            box(7, "tops", 60, 20, store="tvf"),
        ]
        rows.sort(key=lambda r: (r["roi"] is None, -(r["roi"] or 0)))
        picks = self.s.top_picks(rows, budget=300, min_roi=1.0)
        self.assertEqual(set(picks), set(self.s.STORES))
        raghouse = picks["raghouse"]
        self.assertEqual(len(raghouse), 5)
        # Passing boxes first, one per kind before a kind repeats, then the closest misses.
        self.assertEqual([(p["variant_id"], p["check"]) for p in raghouse],
                         [(2, "qualifies"), (3, "qualifies"), (1, "qualifies"), (4, "return_target"),
                          (5, "needs_research")])
        self.assertEqual([p["variant_id"] for p in picks["tvf"]], [7])
        self.assertEqual(picks["papercrane"], [])
        self.assertNotIn("check", rows[0])  # the ranked rows are left as they were
        self.assertEqual(len(self.s.top_picks(rows, budget=1000, min_roi=1.0, count=6)["raghouse"]), 6)

    def test_wholesale_demand_cannot_inflate_resale_sales(self):
        base = next(r for r in self._lots() if r["store"] == "raghouse")
        slow = self.s.price_lot({**base, "demand": 0.1}, 30, 30)
        popular = self.s.price_lot({**base, "demand": 10, "trend_hits": ["cartoon"]}, 30, 30)
        self.assertEqual(slow["sell_through"], 0.5)
        self.assertEqual(slow["expected_profit"], popular["expected_profit"])

    def test_operating_allowance_is_charged_on_planned_sales_and_break_even_follows_it(self):
        row = {"price": 60, "pcs": 20, "usable_pcs": 10, "demand": 50, "resale_low": 15}
        priced = self.s.price_lot(row, 20, 20, sell_through=0.6, fees=0.25, cost_per_piece=2)
        self.assertEqual(priced["operating_cost"], 12)  # 6 planned sales x $2
        self.assertEqual(priced["expected_revenue"], 90)
        self.assertEqual(priced["expected_profit"], -2)
        self.assertEqual(priced["break_even_pcs"], 7)  # $80 landed / ($15 - $2) per sale
        # Half the 6 planned sales at the $15 low: 3 x ($15 x 0.75 - $2) - $80 landed.
        self.assertEqual(priced["downside_profit"], -52.25)

    def test_theme_capacity_allows_more_boxes_of_a_theme_until_it_is_full_or_stocked(self):
        # Three $40 boxes of one theme, each planning 10 sales at $40 a piece.
        rows = [self.s.price_lot({"store": "raghouse", "variant_id": 200 + i, "theme": "dresses", "price": 40,
                                  "pcs": 20, "usable_pcs": 20.0, "demand": 1, "trend_hits": [], "vip": False,
                                  "resale_low": 40}, 20, 40) for i in range(3)]

        def picked(cap):
            plan = self.s.buy_list(rows, self.cfg, budget=500, min_roi=0, theme_capacity=cap)
            return sum(len(c["lots"]) for c in plan["carts"])

        self.assertEqual(picked(None), 1)  # one box per theme without a capacity
        self.assertEqual(picked({"dresses": 25}), 2)
        self.assertEqual(picked({"dresses": 5}), 1)  # the first box is allowed while any capacity is left
        plan = self.s.buy_list(rows, self.cfg, budget=500, min_roi=0, theme_capacity={"dresses": 0})
        self.assertEqual(plan["carts"], [])
        self.assertEqual(set(plan["exclusions"].values()), {"theme_stocked"})

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


def _comps(theme: str, price: float, vid: int = 1, marketplace: str = "eBay", count: int = 3) -> list[dict]:
    today = box_scout._now().date()
    base = "https://www.ebay.com/itm/" if marketplace == "eBay" else "https://poshmark.com/listing/"
    return [{
        "url": f"{base}{vid + index}", "title": f"{theme} used clothing", "currency": "USD",
        "sold_at": (today - timedelta(days=index + 1)).isoformat(), "price": float(price),
        "marketplace": marketplace, "snippet": f"Sold for ${price:.2f}",
    } for index in range(count)]


def _ebay(by_theme: dict[str, list[dict]]):
    """What Chrome reads from eBay: every search answers, most with nothing."""
    by_query = {sold_listings.search_query(theme): comps for theme, comps in by_theme.items()}
    return lambda queries, today: {query: by_query.get(query, []) for query in queries}


def _poshmark_listing(price: float, days_ago: int, lid: int = 1, *, status: str = "sold_out", **changes) -> dict:
    changed = (box_scout._now() - timedelta(days=days_ago)).strftime("%Y-%m-%dT10:00:00-07:00")
    return {"id": f"{lid:024x}", "title": "Cartoon tee", "condition": "ug",
            "price_amount": {"val": str(price), "currency_code": "USD"},
            "inventory": {"status": status, "status_changed_at": changed}, **changes}


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
        mock.patch.object(box_scout, "measured_sell_through", return_value=None).start()
        mock.patch.object(box_scout, "_own_rows", return_value=[]).start()
        mock.patch.object(box_scout, "_announce_new_picks").start()
        mock.patch.dict(box_scout._catalogs, clear=True).start()
        # Chrome is not connected and Poshmark has nothing, unless a test says otherwise.
        self.ebay = mock.patch.object(sold_listings, "ebay_sold", return_value={}).start()
        self.poshmark = mock.patch.object(sold_listings, "poshmark_listings", return_value=[]).start()
        mock.patch.object(box_scout, "RESEARCH_PAUSE_SEC", 0).start()
        self.addCleanup(mock.patch.stopall)

    def _models(self, search=None):
        return mock.patch("vendoo_studio.services.comp_research.model_search", return_value=search)

    def test_researches_trends_and_prices_then_builds_the_buy_list(self):
        self.ebay.side_effect = _ebay({"cartoon t-shirts": _comps("cartoon t-shirts", 30)})
        model = _search("ChatGPT", ['```json\n{"terms": ["Cartoon", "y2k"]}\n```'])
        with self._models(model):
            snapshot = box_scout.refresh()
        state = json.loads(self.state_file.read_text())
        self.assertEqual(state["trend"]["terms"], ["cartoon", "y2k"])
        self.assertTrue(state["resale"]["cartoon t-shirts"]["ebay"])
        lots = snapshot["buy_list"]["carts"][0]["lots"]
        self.assertEqual(lots[0]["title"], "Cartoon T-Shirts 60 pcs")
        self.assertEqual(lots[0]["comps_count"], 3)
        self.assertNotIn("comps", lots[0])  # examples are served on request, not kept per lot
        self.assertTrue(snapshot["research"])
        shown = box_scout.evidence("cartoon t-shirts")
        self.assertEqual([c["url"] for c in shown["comps"]], [f"https://www.ebay.com/itm/{i}" for i in range(1, 4)])
        self.assertEqual((shown["per_piece"], shown["source"]), (30, "eBay"))
        self.assertIsNone(box_scout.evidence("hawaiian shirts"))

    def test_prices_need_no_model(self):
        self.ebay.side_effect = _ebay({"cartoon t-shirts": _comps("cartoon t-shirts", 30)})
        with self._models():
            snapshot = box_scout.refresh()
        self.assertFalse(snapshot["research"])  # no model, so no trend words
        self.assertEqual(snapshot["buy_list"]["carts"][0]["lots"][0]["research_source"], "eBay")

    def test_ebay_goes_before_poshmark_and_poshmark_fills_a_short_theme(self):
        self.ebay.side_effect = _ebay({"cartoon t-shirts": _comps("cartoon t-shirts", 30),
                                       "vintage graphic t-shirts": _comps("vintage graphic t-shirts", 100, vid=100, count=1)})
        self.poshmark.side_effect = lambda query, sold: [_poshmark_listing(90, day, day) for day in (1, 2)] if sold else []
        with self._models():
            box_scout.refresh()
        sold_searches = [call.args[0] for call in self.poshmark.call_args_list if call.kwargs["sold"]]
        self.assertNotIn("cartoon t-shirt", sold_searches)  # eBay already had three
        self.assertIn("vintage graphic t-shirt", sold_searches)
        self.assertEqual(box_scout.evidence("cartoon t-shirts")["source"], "eBay")
        graphic = box_scout.evidence("vintage graphic t-shirts")
        self.assertEqual((graphic["source"], graphic["per_piece"]), ("eBay + Poshmark", 90))

    def test_a_theme_searched_without_chrome_is_searched_again_once_ebay_can_be_read(self):
        self.poshmark.side_effect = lambda query, sold: [_poshmark_listing(30, day, day) for day in (1, 2, 3)] if sold else []
        with self._models():
            box_scout.refresh()
        self.assertEqual(box_scout.evidence("cartoon t-shirts")["source"], "Poshmark")
        research = mock.Mock(return_value={})
        with self._models(), mock.patch.object(box_scout, "_research_prices", research):
            box_scout.refresh(recrawl=False)
            self.assertEqual(research.call_args.args[0], [])  # priced a moment ago, and still no Chrome
            with mock.patch.object(sold_listings, "ebay_ready", return_value=True):
                box_scout.refresh(recrawl=False)
        self.assertIn("cartoon t-shirts", research.call_args.args[0])

    def test_both_store_choices_use_the_same_budget_and_keep_evidence(self):
        self.ebay.side_effect = _ebay({"cartoon t-shirts": _comps("cartoon t-shirts", 30),
                                       "vintage graphic t-shirts": _comps("vintage graphic t-shirts", 100, vid=100)})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}'])):
            snapshot = box_scout.refresh()
        self.assertEqual(set(snapshot["store_buy_lists"]), {"raghouse", "tvf", "papercrane"})
        self.assertEqual(set(snapshot["store_picks"]), {"raghouse", "tvf", "papercrane"})
        for store, picks in snapshot["store_picks"].items():
            in_stock = [lot for lot in snapshot["lots"] if lot["store"] == store]
            self.assertEqual(len(picks), min(box_scout.TOP_PICKS, len(in_stock)))
            self.assertEqual({p["store"] for p in picks}, {store})
            self.assertEqual(picks[0]["check"], "qualifies")
            self.assertTrue(picks[0]["comps_count"])
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

        self.assertIsNone(_response().snapshot)
        self.assertTrue(box_scout.refresh_is_due())

    def test_cached_research_is_not_repeated(self):
        self.ebay.side_effect = _ebay({"cartoon t-shirts": _comps("cartoon t-shirts", 30)})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}'])):
            box_scout.refresh()
        searched = self.ebay.call_args.args[0]
        self.assertIn("cartoon t-shirt", searched)
        self.assertFalse([query for query in searched if "mixed clothing" in query])
        trends = mock.AsyncMock(return_value=([], None))
        with self._models(_search("ChatGPT", [])), mock.patch.object(box_scout, "_research_trends", trends):
            box_scout.refresh()
        trends.assert_not_called()  # a week has not passed
        self.assertEqual(self.ebay.call_args.args[0], [])  # priced, or found nothing, a moment ago

    def test_selling_window_change_researches_new_themes_but_reuses_recent_prices(self):
        self.ebay.side_effect = _ebay({"cartoon t-shirts": _comps("cartoon t-shirts", 30)})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}'])):
            box_scout.refresh()
        box_scout.set_prefs(ready_in_weeks=8, selling_window_weeks=6)
        self.assertTrue(box_scout.refresh_is_due())
        trends = mock.AsyncMock(return_value=(["flannel"], "ChatGPT"))
        prices = mock.Mock(return_value={})
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

    def test_fees_follow_the_sellers_recent_sales_until_they_type_a_rate(self):
        now = datetime(2026, 10, 7, tzinfo=UTC)
        sales = [AnalyticsItem(
            conversation_id=str(i), title="Cartoon t-shirt", status="sold", price=10, cost=None, brand="",
            category="", sold_price=10.0, sold_at=now - timedelta(days=i), listed_at=None,
            marketplace="eBay", days_listed=None, fees=2.5,
        ) for i in range(box_scout.MEASURED_MIN_SALES)]
        self.assertIsNone(box_scout.measured_fees(sales[:-1], now))
        self.assertEqual(box_scout.measured_fees(sales, now), {"rate": 0.25, "sales": len(sales)})
        mock.patch.object(box_scout, "_own_sales", return_value=sales).start()
        snapshot = box_scout.refresh(recrawl=False, research=False)
        self.assertEqual(snapshot["assumptions"]["fees"], 0.25)
        self.assertEqual(box_scout.read_state()["prefs"]["fees"], 0.25)
        box_scout.set_prefs(fees=0.1)
        self.assertFalse(box_scout.read_state()["prefs"]["fees_auto"])
        self.assertEqual(box_scout.refresh(recrawl=False, research=False)["assumptions"]["fees"], 0.1)

    def test_cost_and_selling_window_are_measured_from_recent_sales(self):
        now = datetime(2026, 10, 7, tzinfo=UTC)
        sales = [AnalyticsItem(
            conversation_id=str(i), title="Cartoon t-shirt", status="sold", price=10, cost=None, brand="",
            category="", sold_price=10.0, sold_at=now - timedelta(days=i), listed_at=None,
            marketplace="eBay", days_listed=20, fees=0.0, shipping_cost=4.0,
        ) for i in range(box_scout.MEASURED_MIN_SALES)]
        self.assertIsNone(box_scout.measured_cost_per_piece(sales[:-1], now))
        self.assertIsNone(box_scout.measured_selling_window(sales[:-1], now))
        self.assertEqual(box_scout.measured_cost_per_piece(sales, now), {"value": 4.0, "sales": len(sales)})
        # What buyers paid toward the label is not the seller's cost.
        credited = [AnalyticsItem(**{**s.__dict__, "shipping_cost": 7.0, "shipping_credit": 4.5}) for s in sales]
        self.assertEqual(box_scout.measured_cost_per_piece(credited, now)["value"], 2.5)
        # Free shipping never takes the allowance below the default.
        free = [AnalyticsItem(**{**s.__dict__, "shipping_cost": 0.0}) for s in sales]
        self.assertEqual(box_scout.measured_cost_per_piece(free, now)["value"], box_scout.DEFAULT_PREFS["cost_per_piece"])
        self.assertEqual(box_scout.measured_selling_window(sales, now), {"value": 3, "sales": len(sales)})
        mock.patch.object(box_scout, "measured_cost_per_piece", return_value={"value": 4.0, "sales": 30}).start()
        mock.patch.object(box_scout, "measured_selling_window", return_value={"value": 3, "sales": 30}).start()
        snapshot = box_scout.refresh(recrawl=False, research=False)
        self.assertEqual(snapshot["assumptions"]["cost_per_piece"], 4.0)
        self.assertEqual(snapshot["preferences"]["selling_window_weeks"], 3)
        box_scout.set_prefs(cost_per_piece=1.0, selling_window_weeks=2)
        prefs = box_scout.read_state()["prefs"]
        self.assertFalse(prefs["cost_per_piece_auto"])
        self.assertFalse(prefs["selling_window_auto"])
        self.assertEqual(box_scout.refresh(recrawl=False, research=False)["assumptions"]["cost_per_piece"], 1.0)

    def test_sell_through_follows_analytics_until_the_seller_types_a_rate(self):
        mock.patch.object(box_scout, "measured_sell_through", return_value={"rate": 0.431, "sales": 426}).start()
        snapshot = box_scout.refresh(recrawl=False, research=False)
        self.assertEqual(snapshot["assumptions"]["sell_through"], 0.431)
        self.assertEqual(snapshot["assumptions"]["sell_through_measured"], {"rate": 0.431, "sales": 426})
        box_scout.set_prefs(sell_through=0.6)
        self.assertEqual(box_scout.refresh(recrawl=False, research=False)["assumptions"]["sell_through"], 0.6)

    def _sale(self, title, price, days_ago=5, now=datetime(2026, 10, 7, tzinfo=UTC), status="sold"):
        return AnalyticsItem(
            conversation_id=f"{title}-{price}-{days_ago}", title=title, status=status, price=price, cost=None,
            brand="", category="", sold_price=price if status == "sold" else None,
            sold_at=now - timedelta(days=days_ago) if status == "sold" else None, listed_at=None,
            marketplace="eBay", days_listed=None, fees=0.0)

    def test_theme_sell_through_blends_toward_the_overall_rate_and_capacity_counts_what_is_held(self):
        now = datetime(2026, 10, 7, tzinfo=UTC)
        rows = [self._sale("Floral dress", 10, i) for i in range(8)] + \
               [self._sale("Floral dress", 0, status="active") for _ in range(12)] + \
               [self._sale("Graphic t-shirt", 10, i) for i in range(30)]
        inventory = box_scout.theme_inventory(rows, {"dresses", "t-shirts", "kimonos"}, now)
        self.assertEqual(inventory["dresses"], {"sold": 8, "active": 12})
        self.assertEqual(inventory["kimonos"], {"sold": 0, "active": 0})
        rates = box_scout.theme_sell_through(inventory, 0.5)
        # (8 sold + 10 x 0.5) / (20 + 10); a theme with under 10 pieces has no rate of its own.
        self.assertEqual(rates["dresses"], round(13 / 30, 3))
        self.assertNotIn("kimonos", rates)
        # 38 sales in 90 days is about 27 over a 9-week selling window, less the 12 dresses held.
        capacity = box_scout.theme_capacity(rows, inventory, now, 9)
        self.assertEqual(capacity, {"dresses": 15, "t-shirts": 27, "kimonos": 27})
        # A short window still leaves room for a box of a kind the seller does not hold.
        self.assertEqual(box_scout.theme_capacity(rows, inventory, now, 1)["kimonos"], box_scout.CAPACITY_MIN)
        self.assertIsNone(box_scout.theme_capacity(rows[:3], inventory, now, 4))

    def test_marketplace_prices_are_scaled_to_the_sellers_own_and_mixed_boxes_use_all_sales(self):
        now = datetime(2026, 10, 7, tzinfo=UTC)
        themes = ["dresses", "t-shirts", "jackets"]
        own = {name: [{"price": 10.0, "sold_at": (now - timedelta(days=3 + i)).date().isoformat()} for i in range(3)]
               for name in themes}
        comps = [{"url": f"u{i}", "title": "Dress", "snippet": "", "price": 30.0, "marketplace": "Poshmark",
                  "sold_at": (now - timedelta(days=2 + i)).date().isoformat()} for i in range(4)]
        state = {"resale": {name: {"comps": comps, "active": [], "updated_at": now.isoformat()} for name in themes}}
        mock.patch.object(box_scout.scout(), "sale_mismatch", return_value=None).start()
        self.assertEqual(box_scout.market_haircut(state, now, own), {"factor": 0.33, "themes": 3})
        self.assertIsNone(box_scout.market_haircut(state, now, {"dresses": own["dresses"]}))
        sales = [self._sale(f"Piece {i}", 8.0 + i % 5, i % 30) for i in range(40)]
        mixed = box_scout.all_sales_price(sales, now)
        self.assertEqual(mixed["source"], "Your sales (all items)")
        self.assertLessEqual(mixed["low"], mixed["per_piece"])
        self.assertIsNone(box_scout.all_sales_price(sales[:5], now))

    def test_changed_window_discards_old_themes_without_a_model(self):
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}'])):
            box_scout.refresh()
        box_scout.set_prefs(ready_in_weeks=0)
        snapshot = box_scout.refresh(recrawl=False, research=False)
        self.assertEqual(box_scout.read_state()["trend"]["terms"], [])
        self.assertTrue(all(not lot["trend_hits"] for lot in snapshot["lots"]))

    def test_trend_research_prompt_includes_dated_window_and_history(self):
        ask = mock.AsyncMock(return_value=(None, None))
        context = _planning_context(box_scout.DEFAULT_PREFS, datetime(2026, 10, 7, tzinfo=UTC))
        context["seller_history"]["groups"] = [{"category_path": "Clothing > Coats", "count": 5}]
        import asyncio
        with mock.patch.object(box_scout, "_ask", ask):
            asyncio.run(box_scout._research_trends(context))
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
        def research(themes, own, now):
            box_scout.set_prefs(budget=200, min_roi=1.5, zip="10001", raghouse_vip=True,
                                sell_through=0.6, fees=0.25, cost_per_piece=1.5,
                                ready_in_weeks=8, selling_window_weeks=6)
            return {"cartoon t-shirts": {"comps": _comps("cartoon t-shirts", 40), "active": [], "ebay": True}}

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
        self.ebay.side_effect = _ebay({"cartoon t-shirts": _comps("cartoon t-shirts", 40)})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}'])):
            box_scout.refresh()
        from vendoo_studio.routes.sourcing import SourcingSnapshot

        snapshot = SourcingSnapshot.model_validate(box_scout.read_state()["snapshot"])
        lot = snapshot.buy_list.carts[0].lots[0]
        self.assertEqual(lot.comps_count, 3)
        self.assertEqual(lot.research_source, "eBay")
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
        self.ebay.side_effect = _ebay({"y2k blouses": _comps("y2k blouses", 40)})
        with self._models(_search("ChatGPT", ['{"terms": ["y2k"]}'])):
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
        self.assertNotIn("cartoon t-shirts", json.loads(self.state_file.read_text())["resale"])  # never searched for

    def test_own_sales_and_web_sales_price_a_theme_together(self):
        mock.patch.object(box_scout, "_own_sales", return_value=self.SALES[1:3]).start()
        self.ebay.side_effect = _ebay({"cartoon t-shirts": _comps("cartoon t-shirts", 30, count=1)})
        with self._models(_search("ChatGPT", ['{"terms": ["cartoon"]}'])):
            snapshot = box_scout.refresh()
        lot = snapshot["buy_list"]["carts"][0]["lots"][0]
        self.assertEqual((lot["resale_per_pc"], lot["comps_count"], lot["research_source"]), (30, 3, "Your sales + eBay"))
        comps = box_scout.evidence("cartoon t-shirts")["comps"]
        self.assertEqual({c.get("conversation_id") for c in comps}, {"c2", "c3", None})

    def test_enough_own_sales_leave_the_marketplaces_out_of_the_price(self):
        own = box_scout.own_evidence(self.SALES, {"cartoon t-shirts"})["cartoon t-shirts"]
        priced = box_scout.price_evidence({"comps": _comps("cartoon t-shirts", 99)}, own)
        self.assertEqual((priced["per_piece"], priced["source"]), (30, "Your sales"))
        self.assertFalse([c for c in priced["comps"] if c.get("url")])

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
        mock.patch.object(box_scout, "_research_prices", return_value={}).start()
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


class SoldListingsTest(unittest.TestCase):
    TODAY = date(2026, 10, 5)

    def _card(self, **changes):
        return {"id": "101", "title": "Cartoon Tee Mens L\nOpens in a new window or tab", "caption": "Sold Oct 3, 2026",
                "price": "$20.00", "offer": False, **changes}

    def test_ebay_cards_become_dated_comps(self):
        comps = sold_listings.parse_ebay_cards([self._card(), self._card(id="102", title="NEW LISTINGGarfield Tee", price="$1,234.50"),
                                                self._card(id="103", price="$31.50", caption="Sold Jul 9, 2026")], self.TODAY)
        self.assertEqual([(c["url"], c["title"], c["sold_at"], c["price"]) for c in comps], [
            ("https://www.ebay.com/itm/101", "Cartoon Tee Mens L", "2026-10-03", 20.0),
            ("https://www.ebay.com/itm/103", "Cartoon Tee Mens L", "2026-07-09", 31.5),  # 88 days: context only
        ])
        self.assertEqual({c["marketplace"] for c in comps}, {"eBay"})

    def test_ebay_cards_without_a_real_sale_price_are_left_out(self):
        for changes in ({"offer": True}, {"price": "$20.00 to $35.00"}, {"price": "AU $20.00"}, {"caption": ""},
                        {"caption": "Ended Oct 3, 2026"}, {"caption": "Sold Oct 6, 2026"}, {"caption": "Sold Jun 1, 2026"},
                        {"caption": "Sold Feb 30, 2026"}, {"id": "Shop on eBay"}, {"title": ""}):
            with self.subTest(changes=changes):
                self.assertEqual(sold_listings.parse_ebay_cards([self._card(**changes)], self.TODAY), [])
        self.assertEqual(len(sold_listings.parse_ebay_cards([self._card(), self._card(), "junk"], self.TODAY)), 1)

    def test_poshmark_sold_listings_carry_the_day_they_sold(self):
        with mock.patch.object(box_scout, "_now", return_value=datetime(2026, 10, 5, 12, tzinfo=UTC)):
            listings = [
                _poshmark_listing(22, 2, 1),
                _poshmark_listing(30, 2, 2, condition="nwt"),  # new with tags is not a thrifted piece
                _poshmark_listing(30, 2, 3, status="available"),
                _poshmark_listing(30, 2, 4, price_amount={"val": "30.0", "currency_code": "CAD"}),
                _poshmark_listing(30, 120, 5),
                {"id": "x"}, None,
            ]
        comps = sold_listings.parse_poshmark_sold(listings, self.TODAY)
        self.assertEqual([(c["url"], c["sold_at"], c["price"], c["marketplace"]) for c in comps],
                         [(f"https://poshmark.com/listing/{1:024x}", "2026-10-03", 22.0, "Poshmark")])
        self.assertIn("listed at $22.00 when it sold", comps[0]["snippet"])
        active = sold_listings.parse_poshmark_active(listings)
        self.assertEqual([(c["url"], c["price"]) for c in active], [(f"https://poshmark.com/listing/{3:024x}", 30.0)])

    def test_a_theme_without_a_garment_is_not_searched(self):
        self.assertEqual(sold_listings.search_query("y2k jeans"), "y2k jeans")
        self.assertEqual(sold_listings.search_query("vintage brand name t-shirts"), "vintage t-shirt")  # one piece, not a lot
        self.assertEqual(sold_listings.search_query("premium brand jackets"), "jacket")
        self.assertEqual(sold_listings.search_query("levis denim shorts"), "levis denim shorts")
        for theme in ("mixed clothing", "y2k mixed clothing", "accessories"):
            self.assertIsNone(sold_listings.search_query(theme))

    def test_without_chrome_ebay_is_not_asked(self):
        self.assertFalse(sold_listings.ebay_ready())
        self.assertEqual(sold_listings.ebay_sold(["y2k jeans"], self.TODAY), {})

    def test_what_chrome_read_is_parsed_per_search(self):
        from vendoo_studio.services.extension_connection import extension_manager

        async def read(queries):
            return {"ok": False, "error": "eBay did not show search results",
                    "results": {"y2k jeans": [self._card()], "never asked": [self._card()]}}

        import asyncio
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(loop.call_soon_threadsafe, loop.stop)
        with mock.patch.object(extension_manager, "loop", loop), \
                mock.patch.object(sold_listings, "ebay_ready", return_value=True), \
                mock.patch.object(sold_listings, "_read_ebay", read):
            found = sold_listings.ebay_sold(["y2k jeans", "y2k dresses"], self.TODAY)
        self.assertEqual({query: len(comps) for query, comps in found.items()}, {"y2k jeans": 1})  # the batch stopped early


class PriceEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 5, 12, tzinfo=UTC)
        patcher = mock.patch.object(box_scout, "_now", return_value=self.now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _price(self, comps, active=()):
        return box_scout.price_evidence({"comps": comps, "active": list(active)}, [], now=self.now)

    def test_the_price_is_the_median_of_recent_sales(self):
        comps = _comps("cartoon t-shirts", 20)
        comps[2]["price"] = 40.0
        priced = self._price(comps)
        self.assertEqual(priced["per_piece"], 20)
        self.assertEqual((priced["low"], priced["high"]), (20, 40))

    def test_sale_sample_needs_three_examples_from_the_last_thirty_days(self):
        comps = _comps("cartoon t-shirts", 20)
        for comp in comps[1:]:
            comp["sold_at"] = "2026-09-01"
        self.assertIsNone(self._price(comps))
        self.assertIsNone(self._price([]))

    def test_poshmark_is_only_used_when_ebay_is_short(self):
        ebay, poshmark = _comps("cartoon t-shirts", 20), _comps("cartoon t-shirts", 60, marketplace="Poshmark")
        self.assertEqual((self._price([*poshmark, *ebay])["per_piece"], self._price([*poshmark, *ebay])["source"]), (20, "eBay"))
        ebay[0]["price"] = 55.0
        short = self._price([*poshmark, *ebay[:1]])
        self.assertEqual((short["per_piece"], short["source"]), (60, "eBay + Poshmark"))
        self.assertEqual(self._price(poshmark)["source"], "Poshmark")

    def test_a_sale_must_be_one_used_piece_of_the_themes_garment(self):
        mismatch = box_scout.scout().sale_mismatch
        for theme, title, reason in (
            ("carhartt t-shirts", "Carhartt K87 Pocket T-Shirt Mens Large", None),
            ("carhartt t-shirts", "Carhartt Detroit Jacket Mens XL", "garment"),
            ("harley davidson t-shirts", "Vintage Harley Davidson Shirt XL", None),  # titles call tees shirts
            ("hoodies", "Nike Hoodie Sweatshirt", None),
            ("vintage sweatshirts", "Ugly Christmas Sweater", "garment"),
            ("sports t-shirts", "Dallas Cowboys Jersey", "garment"),
            ("levis shorts", "Levis 501 Jeans", "garment"),
            ("denim jackets", "Levi's Denim Trucker", None),  # denim describes, it is not jeans
            ("pants", "Y2K Crop Hoodie", "garment"),
            ("vintage t-shirts", "1998 Harley Davidson Sturgis XL", None),  # names no garment
            ("mixed clothing", "Zara Dress", None),  # the theme names no garment
            ("cartoon t-shirts", "Lot of 3 Looney Tunes Tees", "bundle"),
            ("cartoon t-shirts", "Vintage Lot 29 Looney Tunes Taz Shirt", None),  # a label, not a lot
            ("skirts", "2 Piece Skirt Set", "bundle"),
            ("cartoon t-shirts", "Taz Tee NWT", "unworn"),
        ):
            with self.subTest(theme=theme, title=title):
                self.assertEqual(mismatch(theme, title), reason)
        self.assertEqual(mismatch("cartoon t-shirts", "Taz Tee", "Condition: New with tags"), "unworn")

    def test_listings_that_do_not_fit_the_theme_cannot_price_or_cap_it(self):
        sold = _comps("cartoon t-shirts", 20)
        for comp, title in zip(sold, ("Looney Tunes Taz Varsity Jacket", "Lot of 3 Looney Tunes Tees", "Taz T-Shirt NWT"), strict=True):
            comp["title"] = title
        asking = [_poshmark_listing(10, 0, lid, status="available", title="Cartoon tee bundle") for lid in range(3)]
        with mock.patch.object(sold_listings, "ebay_sold", return_value={"cartoon t-shirt": [*sold, *_comps("cartoon t-shirts", 30, vid=50)]}), \
                mock.patch.object(sold_listings, "poshmark_listings", return_value=asking), \
                mock.patch.object(box_scout, "RESEARCH_PAUSE_SEC", 0):
            entry = box_scout._research_prices(["cartoon t-shirts"], {}, self.now)["cartoon t-shirts"]
        self.assertEqual([c["price"] for c in entry["comps"]], [30, 30, 30])
        self.assertEqual(entry["active"], [])

    def test_cached_sales_are_rechecked_against_the_theme(self):
        comps = _comps("cartoon t-shirts", 30)
        comps[0]["title"] = "Cartoon Hoodie"
        fresh = box_scout._fresh_research({"resale": {"cartoon t-shirts": {
            "comps": comps, "updated_at": self.now.isoformat(),
        }}}, self.now, {})
        self.assertEqual(fresh, {})

    def test_current_competition_caps_estimated_resale(self):
        active = [{"url": f"https://poshmark.com/listing/{100 + i}", "title": "Cartoon tee", "price": price,
                   "marketplace": "Poshmark", "currency": "USD"} for i, price in enumerate((10, 15, 20))]
        priced = self._price(_comps("cartoon t-shirts", 30), active)
        self.assertEqual((priced["sold_median"], priced["per_piece"], priced["active_median"]), (30, 15, 15))
        self.assertEqual(len(priced["active"]), 3)

    def test_thin_competition_sample_is_unknown(self):
        priced = self._price(_comps("cartoon t-shirts", 30), [{"url": "https://poshmark.com/listing/100", "price": 5}])
        self.assertEqual(priced["per_piece"], 30)
        self.assertIsNone(priced["active_median"])

    def test_research_cache_expires_after_a_week(self):
        for age, qualifies in ((6, True), (7, False), (-1, False)):
            entry = {"comps": _comps("cartoon t-shirts", 30), "updated_at": (self.now - timedelta(days=age)).isoformat()}
            fresh = box_scout._fresh_research({"resale": {"cartoon t-shirts": entry}}, self.now, {})
            self.assertEqual(bool(fresh), qualifies)

    def test_cached_dates_are_rechecked_even_before_the_week_is_up(self):
        comps = _comps("cartoon t-shirts", 30)
        for comp in comps:
            comp["sold_at"] = "2026-09-05"
        entry = {"comps": comps, "updated_at": self.now.isoformat()}
        self.assertTrue(box_scout._fresh_research({"resale": {"cartoon t-shirts": entry}}, self.now, {}))
        self.assertEqual(box_scout._fresh_research({"resale": {"cartoon t-shirts": entry}}, self.now + timedelta(days=1), {}), {})


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
