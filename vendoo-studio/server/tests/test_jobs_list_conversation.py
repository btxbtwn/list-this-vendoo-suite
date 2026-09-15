from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo


class JobsListConversationTest(unittest.TestCase):
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

        self.keep = ConversationRepo(self.db).create(title="Keep")
        self.other = ConversationRepo(self.db).create(title="Other")
        keep_rev = ListingRepo(self.db).save_revision(self.keep.id, {"title": "Keep"}, source="user")
        other_rev = ListingRepo(self.db).save_revision(self.other.id, {"title": "Other"}, source="user")
        self.keep_job = JobRepo(self.db).create(
            conv_id=self.keep.id,
            approved_revision_id=keep_rev.id,
            listing_snapshot={"title": "Keep"},
            vendoo_item_id="keep-draft",
            status="completed",
            current_step="fields_applied",
        )
        for index in range(55):
            JobRepo(self.db).create(
                conv_id=self.other.id,
                approved_revision_id=other_rev.id,
                listing_snapshot={"title": f"Other {index}"},
                status="completed",
            )

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_global_list_can_drop_older_jobs(self):
        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)
        ids = {job["id"] for job in response.json()}
        self.assertNotIn(self.keep_job.id, ids)

    def test_conversation_filter_returns_bound_draft_job(self):
        response = self.client.get(f"/api/jobs?conversation_id={self.keep.id}")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], self.keep_job.id)
        self.assertEqual(payload[0]["vendoo_item_id"], "keep-draft")

    def test_conversation_filter_unknown_conversation_404(self):
        response = self.client.get("/api/jobs?conversation_id=missing")
        self.assertEqual(response.status_code, 404)
