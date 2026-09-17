from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.vendoo_import import parse_vendoo_draft_ref, vendoo_binding


class ParseVendooDraftRefTest(unittest.TestCase):
    def test_parses_full_url(self):
        binding = parse_vendoo_draft_ref("https://web.vendoo.co/app/item/QVzIZuKs?marketplace=ebay")
        self.assertEqual(binding["vendooItemId"], "QVzIZuKs")
        self.assertEqual(binding["vendooUrl"], "https://web.vendoo.co/app/item/QVzIZuKs")

    def test_parses_bare_id(self):
        binding = parse_vendoo_draft_ref("QVzIZuKs")
        self.assertEqual(binding["vendooItemId"], "QVzIZuKs")
        self.assertEqual(binding["vendooUrl"], "https://web.vendoo.co/app/item/QVzIZuKs")

    def test_rejects_new_route(self):
        with self.assertRaises(ValueError):
            parse_vendoo_draft_ref("https://web.vendoo.co/app/item/new")

    def test_rejects_foreign_host(self):
        with self.assertRaises(ValueError):
            parse_vendoo_draft_ref("https://evil.example/item/abc123")


class LinkVendooDraftTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.conv = ConversationRepo(self.db).create(title="Nike tee")
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Nike tee"}, source="user")

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_link_by_url(self):
        response = self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-link",
            json={"url_or_id": "https://web.vendoo.co/app/item/QVzIZuKs"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["vendoo_item_id"], "QVzIZuKs")
        self.assertEqual(body["vendoo_url"], "https://web.vendoo.co/app/item/QVzIZuKs")

        self.db.expire_all()
        refreshed = ConversationRepo(self.db).get(self.conv.id)
        binding = vendoo_binding(refreshed.notes)
        self.assertEqual(binding["vendooItemId"], "QVzIZuKs")

        ensure = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": self.conv.id})
        self.assertEqual(ensure.status_code, 200, ensure.text)
        self.assertEqual(ensure.json()["vendoo_item_id"], "QVzIZuKs")

    def test_link_updates_existing_job(self):
        job = JobRepo(self.db).create(
            conv_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Nike tee"},
            status="completed",
            current_step="fields_applied",
        )
        response = self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-link",
            json={"url_or_id": "abc123XYZ"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.db.expire_all()
        refreshed = JobRepo(self.db).get(job.id)
        self.assertEqual(refreshed.vendoo_item_id, "abc123XYZ")
        self.assertEqual(refreshed.vendoo_url, "https://web.vendoo.co/app/item/abc123XYZ")

    def test_conflict_when_another_listing_owns_draft(self):
        other = ConversationRepo(self.db).create(title="Other tee")
        other.notes = json.dumps({
            "vendooItemId": "taken123",
            "vendooUrl": "https://web.vendoo.co/app/item/taken123",
        })
        self.db.commit()

        response = self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-link",
            json={"url_or_id": "taken123"},
        )
        self.assertEqual(response.status_code, 409, response.text)

    @patch("vendoo_studio.services.vendoo_import.download_vendoo_photos", new_callable=AsyncMock)
    def test_import_draft_copies_fields_and_photos_into_blank_listing(self, download):
        blank = ConversationRepo(self.db).create(title="New Listing")
        download.return_value = [{
            "original_filename": "a.jpg",
            "stored_filename": "stored-a.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 10,
        }]
        link = self.client.post(
            f"/api/conversations/{blank.id}/vendoo-link",
            json={"url_or_id": "draft789"},
        )
        self.assertEqual(link.status_code, 200, link.text)
        ensure = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": blank.id})
        self.assertEqual(ensure.status_code, 200, ensure.text)
        job_id = ensure.json()["id"]
        JobRepo(self.db).save_vendoo_draft(
            job_id,
            item={
                "generalDetails": {"title": "Levi's 501 jeans", "price": 42, "brand": "Levi's"},
                "images": [{"url": "https://cdn.example/a.jpg"}],
            },
            form=None,
            item_id="draft789",
            url="https://web.vendoo.co/app/item/draft789",
            source="api",
            step="fields_applied",
        )

        response = self.client.post(f"/api/jobs/{job_id}/import-draft")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["photo_count"], 1)
        self.assertEqual(body["listing_title"], "Levi's 501 jeans")
        download.assert_awaited_once_with(["https://cdn.example/a.jpg"])

        self.db.expire_all()
        listing = ListingRepo(self.db).get_revisions(blank.id)[0].listing_json
        self.assertEqual(listing["brand"], "Levi's")
        self.assertEqual(listing["price"], 42)
        self.assertEqual(len(ConversationRepo(self.db).get_photos(blank.id)), 1)
        self.assertEqual(JobRepo(self.db).get(job_id).listing_snapshot["title"], "Levi's 501 jeans")

    def test_import_draft_requires_a_read_draft(self):
        self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-link",
            json={"url_or_id": "unread123"},
        )
        job_id = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": self.conv.id}).json()["id"]
        response = self.client.post(f"/api/jobs/{job_id}/import-draft")
        self.assertEqual(response.status_code, 400, response.text)

    def test_rejects_invalid_ref(self):
        response = self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-link",
            json={"url_or_id": "https://web.vendoo.co/app/item/new"},
        )
        self.assertEqual(response.status_code, 400, response.text)


if __name__ == "__main__":
    unittest.main()
