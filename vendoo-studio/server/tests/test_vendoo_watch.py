from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.vendoo_import import merge_notes, parse_notes
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.services.vendoo_watch import (
    CONTENT_FINGERPRINT,
    SYNCED_AT,
    SYNCED_REVISION,
    apply_pull,
    item_content_fingerprint,
    sync_conversation,
    sync_state,
    sync_status,
)


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

    def item(self, stamp, *, title="From Vendoo", listed=False):
        payload = {
            "itemID": "itm1",
            "dateLastModified": stamp,
            "generalDetails": {"title": title},
        }
        if listed:
            payload["listings"] = {"ebay": {"status": {"listed": True}}}
        return payload

    def level_with(self, stamp, *, title="From Vendoo"):
        """Record Studio as synced to this Vendoo stamp and form content."""
        item = self.item(stamp, title=title)
        self.note(**{
            SYNCED_AT: str(stamp),
            SYNCED_REVISION: self.rev.id,
            CONTENT_FINGERPRINT: item_content_fingerprint(item),
        })
        return item

    def test_first_sync_adopts_vendoos_state(self):
        self.note()
        state = sync_state(self.db, self.conv.id, self.item(1000))
        self.assertEqual(state["action"], "pull")
        self.assertEqual(state["reason"], "first sync")

    def test_vendoo_content_change_pulls(self):
        self.level_with(1000, title="Old")
        state = sync_state(self.db, self.conv.id, self.item(2000, title="New"))
        self.assertEqual(state["action"], "pull")
        self.assertEqual(state["reason"], "vendoo changed")

    def test_status_only_change_is_label_not_pull(self):
        self.level_with(1000, title="Same")
        state = sync_state(self.db, self.conv.id, self.item(2000, title="Same", listed=True))
        self.assertEqual(state["action"], "label")
        self.assertEqual(state["reason"], "status only")

    def test_nothing_moving_does_nothing(self):
        self.level_with(2000)
        self.assertEqual(sync_state(self.db, self.conv.id, self.item(2000))["action"], "none")

    def test_both_moving_prefers_vendoo_when_content_changed(self):
        self.level_with(1000, title="Old")
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Edited here"}, source="user")
        state = sync_state(self.db, self.conv.id, self.item(2000, title="From Vendoo"))
        self.assertEqual(state["action"], "pull")
        self.assertEqual(state["reason"], "both changed, prefer vendoo")

    def test_studio_edits_survive_status_only_vendoo_list(self):
        """List in Vendoo after a Studio regenerate: keep the regenerate."""
        self.level_with(1000, title="Old")
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Regenerated"}, source="user")
        state = sync_state(self.db, self.conv.id, self.item(2000, title="Old", listed=True))
        self.assertEqual(state["action"], "label")

    def test_studio_moving_alone_does_not_pull(self):
        self.level_with(2000)
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Edited here"}, source="user")
        self.assertEqual(sync_state(self.db, self.conv.id, self.item(2000))["action"], "none")

    def test_a_pull_records_where_both_sides_stand(self):
        self.note()
        revision_id = apply_pull(self.db, self.conv.id, self.item(5000))
        binding = parse_notes(ConversationRepo(self.db).get(self.conv.id).notes)
        self.assertEqual(binding[SYNCED_AT], "5000")
        self.assertEqual(binding[SYNCED_REVISION], revision_id)
        self.assertTrue(binding[CONTENT_FINGERPRINT])
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

    def test_a_pull_refreshes_the_bound_job_even_when_a_newer_job_exists(self):
        """The sidebar may read an older bound job; a newer unbound one must not hide it."""
        self.note()
        bound = JobRepo(self.db).create(
            self.conv.id, self.rev.id, {"title": "Tee"}, vendoo_item_id="itm1", status="completed",
        )
        JobRepo(self.db).save_vendoo_draft(
            bound.id,
            item={"itemID": "itm1", "listings": {"ebay": {"status": {"notListed": True}}}},
            item_id="itm1",
            source="stale",
        )
        JobRepo(self.db).create(self.conv.id, self.rev.id, {"title": "Tee"}, status="failed")
        fresh = {
            "itemID": "itm1",
            "dateLastModified": 5000,
            "generalDetails": {"title": "From Vendoo"},
            "listings": {"ebay": {"status": {"listed": True}}},
        }
        apply_pull(self.db, self.conv.id, fresh)
        cached = JobRepo(self.db).get_vendoo_draft(bound.id)
        self.assertEqual(cached["item"]["listings"]["ebay"]["status"], {"listed": True})


class SyncConversationTest(unittest.TestCase):
    """When Vendoo moved: label if status-only, else take Vendoo's form content."""

    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = ConversationRepo(self.db).create(title="Tee")
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Tee"}, source="model")
        item = {
            "itemID": "itm1",
            "dateLastModified": 1000,
            "generalDetails": {"title": "From Vendoo"},
        }
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {
            "vendooItemId": "itm1",
            SYNCED_AT: "1000",
            SYNCED_REVISION: self.rev.id,
            CONTENT_FINGERPRINT: item_content_fingerprint(item),
        })
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def sync(self, *, stamp=2000, error=None, item=None):
        async def fake_run_ops(job, ops):
            if error:
                raise error
            payload = item or {
                "itemID": "itm1",
                "dateLastModified": stamp,
                "generalDetails": {"title": "From Vendoo"},
            }
            return {"ok": True, "results": [{"op": "get_item", "ok": True, "item": payload}]}

        with mock.patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops):
            return asyncio.run(sync_conversation(self.db, self.conv.id))

    def test_vendoo_content_change_pulls_without_asking(self):
        result = self.sync(item={
            "itemID": "itm1",
            "dateLastModified": 2000,
            "generalDetails": {"title": "Changed in Vendoo"},
        })
        self.assertEqual(result["action"], "pull")
        self.assertEqual(ListingRepo(self.db).get_revisions(self.conv.id)[0].id, result["revision_id"])
        status = sync_status(self.db, self.conv.id)
        self.assertTrue(status["checked_at"])
        self.assertFalse(status["conflict"])
        self.assertEqual(status["revision_id"], result["revision_id"])

    def test_status_only_list_keeps_studio_fields(self):
        edited = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Regenerated"}, source="user")
        listed = {
            "itemID": "itm1",
            "dateLastModified": 2000,
            "generalDetails": {"title": "From Vendoo"},
            "listings": {"ebay": {"status": {"listed": True}}},
        }
        result = self.sync(item=listed)
        self.assertEqual(result["action"], "label")
        self.assertEqual(result["reason"], "status only")
        self.assertEqual(result["vendoo_status"], "active")
        self.assertEqual(ListingRepo(self.db).get_revisions(self.conv.id)[0].id, edited.id)
        self.assertEqual(
            ListingRepo(self.db).get_revisions(self.conv.id)[0].listing_json["title"],
            "Regenerated",
        )
        conv = ConversationRepo(self.db).get(self.conv.id)
        self.assertEqual(conv.status, "active")
        notes = parse_notes(conv.notes)
        self.assertEqual(notes[SYNCED_AT], "2000")
        self.assertEqual(notes[SYNCED_REVISION], self.rev.id)
        self.assertFalse(sync_status(self.db, self.conv.id)["conflict"])

    def test_up_to_date_still_stamps_the_check(self):
        result = self.sync(stamp=1000)
        self.assertEqual(result["action"], "none")
        self.assertTrue(sync_status(self.db, self.conv.id)["checked_at"])

    def test_content_change_with_studio_edits_takes_vendoo(self):
        ListingRepo(self.db).save_revision(self.conv.id, {"title": "Edited here"}, source="user")
        result = self.sync(item={
            "itemID": "itm1",
            "dateLastModified": 2000,
            "generalDetails": {"title": "Vendoo rewrote this"},
        })
        self.assertEqual(result["action"], "pull")
        self.assertEqual(result["reason"], "both changed, prefer vendoo")
        self.assertEqual(
            ListingRepo(self.db).get_revisions(self.conv.id)[0].listing_json["title"],
            "Vendoo rewrote this",
        )

    def test_stuck_listing_badge_clears_when_no_send_is_running(self):
        """Listed on Vendoo with a finished job must not stay on Listing."""
        ConversationRepo(self.db).update_status(self.conv.id, "listing")
        JobRepo(self.db).create(
            self.conv.id, self.rev.id, {"title": "Tee"}, vendoo_item_id="itm1", status="completed",
        )
        listed = {
            "itemID": "itm1",
            "dateLastModified": 2000,
            "generalDetails": {"title": "From Vendoo"},
            "listings": {"ebay": {"status": {"listed": True}}},
        }
        result = self.sync(item=listed)
        self.assertEqual(result["vendoo_status"], "active")
        conv = ConversationRepo(self.db).get(self.conv.id)
        self.assertEqual(conv.status, "active")
        self.assertEqual(parse_notes(conv.notes)["vendooStatus"], "active")

    def test_chrome_away_records_nothing(self):
        result = self.sync(error=BrowserBridgeError("Connect Chrome"))
        self.assertEqual(result["action"], "unavailable")
        self.assertIsNone(sync_status(self.db, self.conv.id)["checked_at"])


if __name__ == "__main__":
    unittest.main()
