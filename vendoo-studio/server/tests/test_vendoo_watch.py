from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.vendoo_import import merge_notes
from vendoo_studio.services.vendoo_watch import SYNCED_AT, SYNCED_REVISION, apply_pull, sync_state


class SyncStateTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = ConversationRepo(self.db).create(title="Tee")
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Tee"}, source="model")

    def tearDown(self):
        self.db.close()

    def note(self, **values):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "itm1", **values})
        self.db.commit()

    def item(self, stamp):
        return {"itemID": "itm1", "dateLastModified": stamp, "generalDetails": {"title": "From Vendoo"}}

    def test_first_sync_adopts_vendoos_state(self):
        self.note()
        state = sync_state(self.db, self.conv.id, self.item(1000))
        self.assertEqual(state["action"], "pull")
        self.assertEqual(state["reason"], "first sync")

    def test_vendoo_moving_alone_pulls(self):
        self.note(**{SYNCED_AT: "1000", SYNCED_REVISION: self.rev.id})
        self.assertEqual(sync_state(self.db, self.conv.id, self.item(2000))["action"], "pull")

    def test_nothing_moving_does_nothing(self):
        self.note(**{SYNCED_AT: "2000", SYNCED_REVISION: self.rev.id})
        self.assertEqual(sync_state(self.db, self.conv.id, self.item(2000))["action"], "none")

    def test_both_moving_is_a_conflict_not_an_overwrite(self):
        """Studio's edits are not Vendoo's to discard, nor the reverse."""
        self.note(**{SYNCED_AT: "1000", SYNCED_REVISION: self.rev.id})
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Edited here"}, source="user")
        state = sync_state(self.db, self.conv.id, self.item(2000))
        self.assertEqual(state["action"], "conflict")

    def test_studio_moving_alone_does_not_pull(self):
        self.note(**{SYNCED_AT: "2000", SYNCED_REVISION: self.rev.id})
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Edited here"}, source="user")
        self.assertEqual(sync_state(self.db, self.conv.id, self.item(2000))["action"], "none")

    def test_a_pull_records_where_both_sides_stand(self):
        self.note()
        revision_id = apply_pull(self.db, self.conv.id, self.item(5000))
        from vendoo_studio.services.vendoo_import import parse_notes

        binding = parse_notes(ConversationRepo(self.db).get(self.conv.id).notes)
        self.assertEqual(binding[SYNCED_AT], "5000")
        self.assertEqual(binding[SYNCED_REVISION], revision_id)
        # And syncing again now finds nothing to do.
        self.assertEqual(sync_state(self.db, self.conv.id, self.item(5000))["action"], "none")

    def test_a_pull_refreshes_the_job_draft_cache_for_thread_status(self):
        """Sidebar marketplace chips read the job draft; pull must overwrite it."""
        self.note()
        job = JobRepo(self.db).create(
            self.conv.id,
            self.rev.id,
            {"title": "Tee"},
            vendoo_item_id="itm1",
            status="completed",
        )
        JobRepo(self.db).save_vendoo_draft(
            job.id,
            item={
                "itemID": "itm1",
                "listings": {"ebay": {"status": {"notListed": True}}},
            },
            item_id="itm1",
            source="stale",
        )
        fresh = {
            "itemID": "itm1",
            "dateLastModified": 5000,
            "generalDetails": {"title": "From Vendoo"},
            "listings": {
                "ebay": {"status": {"listed": True}},
                "depop": {"status": {"notListed": True}},
            },
        }
        apply_pull(self.db, self.conv.id, fresh)
        cached = JobRepo(self.db).get_vendoo_draft(job.id)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["source"], "vendoo_sync")
        self.assertEqual(cached["item"]["listings"]["ebay"]["status"], {"listed": True})
        self.assertEqual(cached["item"]["listings"]["depop"]["status"], {"notListed": True})


if __name__ == "__main__":
    unittest.main()
