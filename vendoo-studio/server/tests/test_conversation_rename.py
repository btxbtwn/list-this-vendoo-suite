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


class ConversationRenameTest(unittest.TestCase):
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

    def test_rename_updates_title(self):
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"title": "  Vintage Nike Tee  "},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["title"], "Vintage Nike Tee")

        self.db.expire_all()
        refreshed = ConversationRepo(self.db).get(self.conv.id)
        self.assertEqual(refreshed.title, "Vintage Nike Tee")

    def test_rename_rejects_empty_title(self):
        response = self.client.patch(
            f"/api/conversations/{self.conv.id}",
            json={"title": "   "},
        )
        self.assertEqual(response.status_code, 400, response.text)

        self.db.expire_all()
        refreshed = ConversationRepo(self.db).get(self.conv.id)
        self.assertEqual(refreshed.title, "Nike tee")

    def test_rename_missing_conversation_is_404(self):
        response = self.client.patch(
            "/api/conversations/missing",
            json={"title": "Gone"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
