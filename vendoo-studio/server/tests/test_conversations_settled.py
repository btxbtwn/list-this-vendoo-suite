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

    def test_sold_status_auto_settles(self):
        conv = self.repo.create(title="Nike tee")
        updated = self.repo.update_status(conv.id, "sold")
        self.assertEqual(updated.status, "sold")
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

    def test_reconcile_backfills_sold_listings(self):
        conv = Conversation(title="Old tee", status="sold")
        self.db.add(conv)
        self.db.commit()
        self.assertIsNone(conv.settled_at)
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertIsNotNone(conv.settled_at)

    def test_reconcile_does_not_resettle_after_explicit_unsettle(self):
        conv = self.repo.create(title="Nike tee")
        self.repo.update_status(conv.id, "sold")
        self.repo.unsettle(conv.id)
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertIsNone(conv.settled_at)
        self.assertIsNotNone(conv.unsettled_at)

    def test_explicit_settle_overrides_keep_active(self):
        conv = self.repo.create(title="Nike tee")
        self.repo.update_status(conv.id, "sold")
        self.repo.unsettle(conv.id)
        settled = self.repo.settle(conv.id)
        self.assertIsNotNone(settled.settled_at)
        self.assertIsNone(settled.unsettled_at)

    def test_reconcile_wears_the_vendoo_label_of_a_finished_job(self):
        """A finished send leaves the listing wearing Vendoo's own label."""
        conv = self.repo.create(title="Nike tee", notes='{"vendooStatus": "sold"}')
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
        self.assertEqual(conv.status, "sold")
        self.assertIsNotNone(conv.settled_at)

    def test_reconcile_leaves_an_unlisted_item_a_draft(self):
        conv = self.repo.create(title="Nike tee", notes='{"vendooStatus": "draft"}')
        conv.updated_at = datetime.now(UTC) - timedelta(hours=1)
        self.db.add(Job(
            conversation_id=conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Nike tee"},
            status="completed",
        ))
        self.db.commit()
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertEqual(conv.status, "draft")
        self.assertIsNone(conv.settled_at)

    def test_reconcile_clears_stuck_listing_when_job_is_finished(self):
        """A finished send must not leave Listing forever after chat bumps updated_at."""
        conv = self.repo.create(title="Hurley polo", notes='{"vendooStatus": "active"}')
        self.repo.update_status(conv.id, "listing")
        older = datetime.now(UTC) - timedelta(hours=1)
        job = Job(
            conversation_id=conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Hurley polo"},
            status="completed",
            updated_at=older,
        )
        self.db.add(job)
        self.db.commit()
        # Chat / field fills stamp the conversation after the job settled.
        conv.updated_at = datetime.now(UTC)
        self.db.commit()
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertEqual(conv.status, "active")

    def test_reconcile_clears_listing_with_no_job(self):
        conv = self.repo.create(title="Hurley polo", notes='{"vendooStatus": "active"}')
        self.repo.update_status(conv.id, "listing")
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertEqual(conv.status, "active")

    def test_reconcile_keeps_listing_while_job_is_dispatched(self):
        conv = self.repo.create(title="Hurley polo", notes='{"vendooStatus": "active"}')
        self.repo.update_status(conv.id, "listing")
        older = datetime.now(UTC) - timedelta(hours=1)
        self.db.add(Job(
            conversation_id=conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Hurley polo"},
            status="dispatched",
            updated_at=older,
        ))
        conv.updated_at = datetime.now(UTC)
        self.db.commit()
        self.repo.reconcile_job_statuses()
        self.db.refresh(conv)
        self.assertEqual(conv.status, "listing")


if __name__ == "__main__":
    unittest.main()
