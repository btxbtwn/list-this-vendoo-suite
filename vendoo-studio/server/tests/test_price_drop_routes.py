from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from vendoo_studio.database import SessionLocal
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
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
        with (
            patch("vendoo_studio.services.price_drop.comps_search_available", return_value=False),
            patch("vendoo_studio.services.price_drop.research_sold_comps", new=AsyncMock()),
        ):
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
