"""Vinted categories and the confirmed direct list."""

from __future__ import annotations

import asyncio
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.services.photo_store import LocalPhotoStore
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services import native_marketplaces as native
from vendoo_studio.services.marketplace_delist import listing_id
from vendoo_studio.services.vinted_listing import apply_vinted_listing, map_vinted_category_path


class VintedCategoryTest(unittest.TestCase):
    def test_womens_tee_uses_vinted_catalog_path(self):
        listing = {
            "title": "Black tee",
            "category_path": "Women > Clothing > Tops",
            "condition": "Pre-Owned - Excellent",
            "brand": "Levi's",
            "primaryColor": "Black",
            "size": "M",
            "price": 18,
            "weight_oz": 8,
        }
        self.assertEqual(map_vinted_category_path(listing), "Women > Clothing > Tops & t-shirts > T-shirts")
        apply_vinted_listing(listing)
        self.assertEqual(listing["vinted_specifics"]["condition"], "Very good")
        self.assertEqual(listing["vinted_specifics"]["packageSize"], "Small")
        self.assertEqual(listing["vinted_specifics"]["brand"], "Levi's")

    def test_no_department_does_not_invent_a_category(self):
        listing = {"title": "Tee", "condition": "Pre-Owned - Good"}
        self.assertEqual(map_vinted_category_path(listing), "")
        apply_vinted_listing(listing)
        self.assertFalse(str((listing.get("vinted_specifics") or {}).get("category") or "").strip())

    def test_seller_condition_is_kept(self):
        listing = {"title": "Tee", "category_path": "Women > Tops", "vinted_specifics": {"condition": "Good"}}
        apply_vinted_listing(listing)
        self.assertEqual(listing["vinted_specifics"]["condition"], "Good")

    def test_listing_link(self):
        self.assertEqual(listing_id("vinted", "https://www.vinted.com/items/42-black-tee"), "42")
        self.assertIsNone(listing_id("vinted", "https://www.vinted.com/items/new"))


class VintedListRouteTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        store = LocalPhotoStore(directory)
        store.put("test.jpg", b"test photo")
        self.enterContext(patch("vendoo_studio.services.photo_store._store", store))
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine)
        self.db = self.sessions()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        listing = {
            "title": "Black tee",
            "description": "Cotton tee.",
            "price": 18,
            "condition": "Pre-Owned - Excellent",
            "category_path": "Women > Clothing > Tops",
            "brand": "Levi's",
            "primaryColor": "Black",
        }
        self.conv = ConversationRepo(self.db).create(title=listing["title"])
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, listing, "model")
        ConversationRepo(self.db).add_photo(self.conv.id, "test.jpg", "test.jpg", "image/jpeg", 1)
        self.base = f"/api/conversations/{self.conv.id}/native-marketplaces"
        self.bridge = self.enterContext(patch("vendoo_studio.services.native_marketplaces.browser_bridge.request", new_callable=AsyncMock))
        self.draft_url = "https://www.vinted.com/items/42/edit"
        self.bridge.side_effect = [
            {"ok": True, "state": "draft", "draft_url": self.draft_url},
            {"ok": True, "state": "published", "draft_url": self.draft_url, "listing_url": "https://www.vinted.com/items/42-black-tee"},
        ]
        self.manager = SimpleNamespace(connected=True, build="test-build", send_message=AsyncMock(return_value=True))
        self.enterContext(patch("vendoo_studio.services.extension_connection.extension_manager", self.manager))
        self.enterContext(patch("vendoo_studio.services.native_marketplaces.expected_extension_build", return_value="test-build"))
        self.enterContext(patch("vendoo_studio.services.extension_connection.schedule_advance_job_queue"))
        self.enterContext(patch("vendoo_studio.database.SessionLocal", self.sessions))
        self.launched = []
        self.enterContext(patch.object(native, "_launch", self.launched.append))

    def tearDown(self):
        for coro in self.launched:
            coro.close()
        app.dependency_overrides.clear()
        self.db.close()

    def test_list_requires_confirm_then_saves_and_publishes(self):
        refused = self.client.post(f"{self.base}/vinted/list", json={"revision_id": self.rev.id, "confirm": False})
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Confirm", refused.json()["detail"])
        self.assertEqual(self.launched, [])

        started = self.client.post(f"{self.base}/vinted/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["state"], "saving")
        while self.launched:
            asyncio.run(self.launched.pop(0))
        record = self.client.get(self.base).json()["vinted"]
        self.assertEqual(record["state"], "published")
        self.assertEqual(record["draft_url"], self.draft_url)
        self.assertEqual(record["listing_url"], "https://www.vinted.com/items/42-black-tee")
        save, publish = (call.args[2] for call in self.bridge.call_args_list)
        self.assertEqual((save["action"], save["confirm"]), ("save_draft", False))
        self.assertEqual((publish["action"], publish["confirm"], publish["draft_url"]), ("publish", True, self.draft_url))
        self.assertEqual(save["listing"]["vinted_specifics"]["category"], "Women > Clothing > Tops & t-shirts > T-shirts")
