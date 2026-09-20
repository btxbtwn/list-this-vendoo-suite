from __future__ import annotations

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
from vendoo_studio.repositories.queries import ConversationRepo


class ConversationStatusTest(unittest.TestCase):
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

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_status_cannot_be_set_through_the_api(self):
        """The label belongs to the bound Vendoo item, so nothing else may set it."""
        for attempt in ("sold", "active", "draft", "failed", "listing", "ready"):
            response = self.client.patch(
                f"/api/conversations/{self.conv.id}",
                json={"status": attempt},
            )
            self.assertEqual(response.status_code, 422, f"{attempt}: {response.text}")

        self.db.expire_all()
        self.assertEqual(ConversationRepo(self.db).get(self.conv.id).status, "draft")

    def test_title_and_notes_are_still_editable(self):
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"title": "Nike tee, large"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["title"], "Nike tee, large")
        self.assertEqual(response.json()["status"], "draft")

    def test_status_follows_the_bound_vendoo_item(self):
        repo = ConversationRepo(self.db)
        conv = repo.create(title="Sold tee", notes='{"vendooItemId": "i1", "vendooStatus": "sold"}')
        self.db.add(Job(
            conversation_id=conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Sold tee"},
            status="imported",
            vendoo_item_id="i1",
        ))
        self.db.commit()

        listed = self.client.get("/api/conversations").json()
        row = next(item for item in listed if item["id"] == conv.id)
        self.assertEqual(row["status"], "sold")
        self.assertEqual(row["vendoo_status"], "sold")


if __name__ == "__main__":
    unittest.main()
