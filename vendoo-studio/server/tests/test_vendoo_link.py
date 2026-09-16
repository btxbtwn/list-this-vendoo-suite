from __future__ import annotations

import json
import unittest

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

    def test_rejects_invalid_ref(self):
        response = self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-link",
            json={"url_or_id": "https://web.vendoo.co/app/item/new"},
        )
        self.assertEqual(response.status_code, 400, response.text)


if __name__ == "__main__":
    unittest.main()
