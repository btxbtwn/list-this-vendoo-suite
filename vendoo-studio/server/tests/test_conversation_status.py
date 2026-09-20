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

    def test_set_sold_status(self):
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"status": "sold"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "sold")
        self.assertIsNotNone(body["settled_at"])

        self.db.expire_all()
        refreshed = ConversationRepo(self.db).get(self.conv.id)
        self.assertEqual(refreshed.status, "sold")
        self.assertIsNotNone(refreshed.settled_at)

    def test_set_active_status(self):
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"status": "active"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "active")
        self.assertIsNone(body["settled_at"])

    def test_set_draft_status(self):
        ConversationRepo(self.db).update_status(self.conv.id, "sold")
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"status": "draft"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "draft")

    def test_set_failed_status(self):
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"status": "failed"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "failed")

    def test_rejects_process_status(self):
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"status": "listing"},
        )
        self.assertEqual(response.status_code, 400, response.text)

        self.db.expire_all()
        refreshed = ConversationRepo(self.db).get(self.conv.id)
        self.assertEqual(refreshed.status, "draft")

    def test_rejects_unknown_status(self):
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"status": "ready"},
        )
        self.assertEqual(response.status_code, 400, response.text)


if __name__ == "__main__":
    unittest.main()
