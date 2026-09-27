from __future__ import annotations

import unittest
import urllib.error
from datetime import date
from unittest import mock

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services import box_scout


def _product(title: str, price: str, grams: int, *, available: bool = True, tags=(), handle=None):
    return {
        "title": title,
        "handle": handle or title.lower().replace(" ", "-"),
        "product_type": "T-Shirts",
        "tags": ["09-20-2026", *tags],
        "variants": [
            {"available": available, "price": price, "grams": grams, "compare_at_price": None}
        ],
    }


CATALOG = [
    _product("Cartoon T-Shirts 60 pcs", "60.00", 12701),
    _product("Recycle Cartoon T-Shirts 70 pcs", "30.00", 12701),
    _product("Cartoon Tees 50 pcs", "40.00", 9072, available=False),
    _product("Plain Blank Tees 80 pcs", "40.00", 12701),
    _product("Y2K Blouses 40 pcs", "45.00", 7258, tags=("VIP_Product",)),
    _product("Tiny Lot 5 pcs", "10.00", 2000),
    {**_product("Gift Card", "25.00", 0), "product_type": "Membership"},
]


class BoxScoutRouteTest(unittest.TestCase):
    def setUp(self):
        box_scout._catalog = None
        scout = box_scout._scout()
        self.fetch = mock.patch.object(scout, "fetch_catalog", return_value=CATALOG).start()
        mock.patch.object(scout, "store_today", return_value=date(2026, 9, 27)).start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(setattr, box_scout, "_catalog", None)
        self.client = TestClient(app)

    def test_ranks_in_stock_boxes_with_zone_six_shipping(self):
        body = self.client.get("/api/sourcing/raghouse").json()
        titles = [box["title"] for box in body["boxes"]]
        self.assertNotIn("Cartoon Tees 50 pcs", titles)  # sold out
        self.assertNotIn("Tiny Lot 5 pcs", titles)  # under 20 pieces
        self.assertNotIn("Gift Card", titles)
        # 12701 g bills as 29 lb: ($44.23 + $6.50 residential) x 1.26 fuel.
        cartoon = next(box for box in body["boxes"] if box["title"] == "Cartoon T-Shirts 60 pcs")
        self.assertEqual(cartoon["ship_est"], 63.92)
        self.assertEqual(cartoon["landed"], 123.92)
        self.assertEqual(body["shipping"]["destination_zip"], "70115")
        # A sold-out cartoon box makes cartoon lots rank above the plain ones.
        self.assertLess(titles.index("Cartoon T-Shirts 60 pcs"), titles.index("Plain Blank Tees 80 pcs"))

    def test_recycle_boxes_count_fewer_usable_pieces(self):
        body = self.client.get("/api/sourcing/raghouse").json()
        recycle = next(box for box in body["boxes"] if box["title"].startswith("Recycle"))
        self.assertEqual(recycle["grade"], "recycle")
        self.assertAlmostEqual(recycle["cog_per_usable_pc"], round(recycle["landed"] / (70 * 0.6), 2))

    def test_trend_terms_and_vip_filter(self):
        body = self.client.get("/api/sourcing/raghouse", params={"trend": "y2k, band"}).json()
        vip = next(box for box in body["boxes"] if box["vip"])
        self.assertEqual(vip["trend_hits"], ["y2k"])
        body = self.client.get("/api/sourcing/raghouse", params={"include_vip": "false"}).json()
        self.assertFalse(any(box["vip"] for box in body["boxes"]))

    def test_catalog_is_crawled_once_until_refresh(self):
        self.client.get("/api/sourcing/raghouse")
        self.client.get("/api/sourcing/raghouse", params={"min_pcs": 30})
        self.assertEqual(self.fetch.call_count, 1)
        self.client.get("/api/sourcing/raghouse", params={"refresh": "true"})
        self.assertEqual(self.fetch.call_count, 2)

    def test_blocked_crawl_is_a_bad_gateway(self):
        self.fetch.side_effect = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        response = self.client.get("/api/sourcing/raghouse")
        self.assertEqual(response.status_code, 502)
        self.assertIn("Raghouse did not return its catalog", response.json()["detail"])
