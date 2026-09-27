from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from vendoo_studio.database import SessionLocal
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services import live_trace
from vendoo_studio.services.comp_research import CompsEvent
from vendoo_studio.services.price_drop import PRICE_DROP_SOURCE


class PriceDropRouteTest(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title="Price drop")
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {
                "title": "Nike Tee",
                "description": "Soft tee.",
                "price": 48,
                "brand": "Nike",
                "category_path": "Tops > T-Shirts",
                "condition": "Pre-Owned - Good",
                "quantity": 1,
            },
            source="generation",
        )

    def tearDown(self):
        self.db.close()

    def test_preview_and_apply(self):
        with patch("vendoo_studio.services.price_drop.comps_search_available", return_value=False):
            preview = self.client.post(f"/api/conversations/{self.conv.id}/price-drop/preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        body = preview.json()
        self.assertEqual(body["current_price"], 48)
        self.assertEqual(body["suggested_price"], 43)

        apply = self.client.post(
            f"/api/conversations/{self.conv.id}/price-drop",
            json={"price": 41, "percent": 15, "mode": "percent"},
        )
        self.assertEqual(apply.status_code, 200, apply.text)
        payload = apply.json()
        self.assertEqual(payload["price"], 41)
        self.assertEqual(payload["previous_price"], 48)

        revisions = ListingRepo(self.db).get_revisions(self.conv.id)
        self.assertEqual(revisions[0].source, PRICE_DROP_SOURCE)
        self.assertEqual(revisions[0].listing_json["price"], 41)

        listing = self.client.get(f"/api/conversations/{self.conv.id}/listing")
        self.assertEqual(listing.json()["listing"]["price"], 41)

    def test_comps_stream_reports_sources_then_the_preview(self):
        comps = (
            "Sold comps:\n"
            "Query: Nike T-Shirts sold comps\n"
            "Source: ChatGPT + Cursor\n"
            "\n"
            "- $20 · eBay · Nike Tee\n"
            "  https://www.ebay.com/itm/1\n"
            "- $18 · Poshmark · Nike Tee\n"
            "  https://poshmark.com/listing/2\n"
            "- $22 · Mercari · Nike Tee\n"
            "  https://www.mercari.com/item/3\n"
        )

        async def fake_stream(_analysis, evidence):
            self.assertEqual(evidence["brand"], "Nike")
            live_trace.emit("step", "Cursor searched: nike tee sold")
            yield CompsEvent("source", source="Cursor", state="searching")
            yield CompsEvent("source", source="Cursor", state="done", sold=3, live=0)
            yield CompsEvent("done", text=comps)

        with (
            patch("vendoo_studio.services.price_drop.comps_search_available", return_value=True),
            patch("vendoo_studio.services.comp_research.stream_sold_comps", new=fake_stream),
        ):
            res = self.client.post(f"/api/conversations/{self.conv.id}/price-drop/comps")
        self.assertEqual(res.status_code, 200, res.text)
        events = [
            (block.split("\n", 1)[0].removeprefix("event: "), block.split("data: ", 1)[1])
            for block in res.text.strip().split("\n\n")
            if block.startswith("event:")
        ]
        self.assertEqual(events[0], ("step", "Cursor searched: nike tee sold"))
        self.assertEqual(json.loads(events[1][1])["state"], "searching")
        self.assertEqual(json.loads(events[2][1])["sold"], 3)
        preview = json.loads(events[-1][1])
        self.assertEqual(events[-1][0], "preview")
        self.assertEqual(preview["comps"]["target_price"], 27)
        self.assertEqual(preview["suggested_mode"], "comps")
        self.assertTrue(res.text.rstrip().endswith("data: [DONE]"))

    def test_rejects_raise_or_missing_price(self):
        bad = self.client.post(
            f"/api/conversations/{self.conv.id}/price-drop",
            json={"price": 60, "mode": "custom"},
        )
        self.assertEqual(bad.status_code, 400)

        empty = ConversationRepo(self.db).create(title="Empty")
        missing = self.client.post(f"/api/conversations/{empty.id}/price-drop/preview")
        self.assertEqual(missing.status_code, 400)


if __name__ == "__main__":
    unittest.main()
