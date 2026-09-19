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
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo


class MarketplaceStatusesRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        conv = ConversationRepo(self.db).create(title="Nike tee")
        repo = JobRepo(self.db)
        self.cached = repo.create(conv_id=conv.id, approved_revision_id="rev1", listing_snapshot={"title": "Nike tee"})
        self.uncached = repo.create(conv_id=conv.id, approved_revision_id="rev2", listing_snapshot={"title": "Nike tee"})
        repo.save_vendoo_draft(
            self.cached.id,
            item={
                "title": "Nike tee",
                "description": "long text the sidebar never needs",
                "listings": {
                    "ebay": {"status": {"listed": True}, "price": 20},
                    "facebook": {"status": {"notListed": True}},
                },
            },
            form={"statuses": {"general": "DRAFT"}, "fields": {"title": "Nike tee"}},
            statuses={"ebay": "LISTED"},
        )

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_returns_status_slices_for_cached_jobs_only(self):
        response = self.client.get(
            "/api/jobs/marketplace-statuses",
            params={"job_ids": f"{self.cached.id},{self.uncached.id},missing"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(list(body), [self.cached.id])
        self.assertEqual(
            body[self.cached.id],
            {
                "statuses": {"ebay": "LISTED"},
                "form": {"statuses": {"general": "DRAFT"}},
                "item": {
                    "listings": {
                        "ebay": {"status": {"listed": True}},
                        "facebook": {"status": {"notListed": True}},
                    },
                },
            },
        )

    def test_empty_ids(self):
        response = self.client.get("/api/jobs/marketplace-statuses")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {})


if __name__ == "__main__":
    unittest.main()
