from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo


class EnsureDraftJobTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.db = Session()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title="Tee")
        self.conv.notes = json.dumps({
            "vendooItemId": "QVzIZuKs",
            "vendooUrl": "https://web.vendoo.co/app/item/QVzIZuKs",
        })
        self.db.commit()
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Gildan Tee"}, source="user")

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_ensure_creates_completed_job_for_bound_draft(self):
        response = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": self.conv.id})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["current_step"], "fields_applied")
        self.assertEqual(payload["vendoo_item_id"], "QVzIZuKs")
        listed = self.client.get(f"/api/jobs?conversation_id={self.conv.id}")
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(listed.json()[0]["id"], payload["id"])

    def test_ensure_reuses_existing_non_cancelled_job(self):
        first = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": self.conv.id}).json()
        second = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": self.conv.id}).json()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(JobRepo(self.db).list_by_conversation(self.conv.id)), 1)

    def test_ensure_requires_bound_draft(self):
        bare = ConversationRepo(self.db).create(title="Bare")
        ListingRepo(self.db).save_revision(bare.id, {"title": "Bare"}, source="user")
        response = self.client.post("/api/jobs/ensure-draft", json={"conversation_id": bare.id})
        self.assertEqual(response.status_code, 400)
