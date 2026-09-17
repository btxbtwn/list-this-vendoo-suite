from __future__ import annotations

from datetime import datetime, timedelta, UTC

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import unittest

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo


class ConversationSettlementTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.repo = ConversationRepo(self.db)

    def tearDown(self):
        self.db.close()

    def test_settle_stamps_settled_at(self):
        conv = self.repo.create(title="Nike tee")
        settled = self.repo.settle(conv.id)
        self.assertIsNotNone(settled.settled_at)
        self.assertIsNone(settled.unsettled_at)

    def test_unsettle_returns_listing_to_active(self):
        conv = self.repo.create(title="Nike tee")
        self.repo.settle(conv.id)
        active = self.repo.unsettle(conv.id)
        self.assertIsNone(active.settled_at)
        self.assertIsNotNone(active.unsettled_at)

    def test_completed_status_auto_settles(self):
        conv = self.repo.create(title="Nike tee")
        updated = self.repo.update_status(conv.id, "completed")
        self.assertEqual(updated.status, "completed")
        self.assertIsNotNone(updated.settled_at)

    def test_in_progress_status_auto_unsettles(self):
        conv = self.repo.create(title="Nike tee")
        self.repo.settle(conv.id)
        updated = self.repo.update_status(conv.id, "in_progress")
        self.assertIsNone(updated.settled_at)
        self.assertIsNotNone(updated.unsettled_at)

    def test_listing_status_auto_unsettles(self):
        conv = self.repo.create(title="Nike tee")
        self.repo.settle(conv.id)
        updated = self.repo.update_status(conv.id, "listing")
        self.assertIsNone(updated.settled_at)
        self.assertIsNotNone(updated.unsettled_at)

    def test_reconcile_backfills_completed_listings(self):
        conv = Conversation(title="Old tee", status="completed")
        self.db.add(conv)
        self.db.commit()
        self.assertIsNone(conv.settled_at)
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertIsNotNone(conv.settled_at)

    def test_reconcile_does_not_resettle_after_explicit_unsettle(self):
        conv = self.repo.create(title="Nike tee")
        self.repo.update_status(conv.id, "completed")
        self.repo.unsettle(conv.id)
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertIsNone(conv.settled_at)
        self.assertIsNotNone(conv.unsettled_at)

    def test_explicit_settle_overrides_keep_active(self):
        conv = self.repo.create(title="Nike tee")
        self.repo.update_status(conv.id, "completed")
        self.repo.unsettle(conv.id)
        settled = self.repo.settle(conv.id)
        self.assertIsNotNone(settled.settled_at)
        self.assertIsNone(settled.unsettled_at)

    def test_reconcile_settles_from_completed_job(self):
        conv = self.repo.create(title="Nike tee")
        older = datetime.now(UTC) - timedelta(hours=1)
        conv.updated_at = older
        job = Job(
            conversation_id=conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Nike tee"},
            status="completed",
        )
        self.db.add(job)
        self.db.commit()
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertEqual(conv.status, "completed")
        self.assertIsNotNone(conv.settled_at)


if __name__ == "__main__":
    unittest.main()
