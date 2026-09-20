from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import vendoo_bulk_import, vendoo_label_sync
from vendoo_studio.services.vendoo_import import merge_notes, parse_notes


def listed_item(item_id: str, *, modified: int = 2) -> dict:
    return {
        "id": item_id,
        "itemID": item_id,
        "dateLastModified": modified,
        "generalDetails": {"title": "Tee"},
        "listings": {"ebay": {"status": {"listed": True}}},
    }


class LabelSyncTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        vendoo_label_sync._progress = vendoo_label_sync.LabelSyncProgress()
        vendoo_label_sync._task = None
        vendoo_label_sync._last_finished_mono = 0.0

    def tearDown(self):
        self.db.close()

    def bind_draft(self, item_id: str):
        conv = ConversationRepo(self.db).create(title="Tee")
        conv.notes = merge_notes(conv.notes, {
            "vendooItemId": item_id,
            "vendooStatus": "draft",
        })
        ConversationRepo(self.db).update_status(conv.id, "draft")
        rev = ListingRepo(self.db).save_revision(conv.id, {"title": "Tee"}, source="user")
        JobRepo(self.db).create(conv.id, rev.id, {"title": "Tee"}, vendoo_item_id=item_id, status="completed")
        return conv

    async def _run(self, pages: dict[str, tuple[list[dict], str]]) -> dict:
        async def fake_list_page(page_token: str):
            return pages[page_token]

        class SessionCtx:
            def __enter__(self_inner):
                return self.db

            def __exit__(self_inner, *args):
                return False

        vendoo_label_sync._progress = vendoo_label_sync.LabelSyncProgress(running=True)
        with (
            patch.object(vendoo_label_sync, "_list_page", side_effect=fake_list_page),
            patch("vendoo_studio.database.SessionLocal", SessionCtx),
        ):
            await vendoo_label_sync._run()
        return vendoo_label_sync.status()

    async def test_bound_draft_becomes_active_from_inventory_page(self):
        conv = self.bind_draft("itm1")
        progress = await self._run({"": ([listed_item("itm1")], "")})

        conv = ConversationRepo(self.db).get(conv.id)
        self.assertEqual(conv.status, "active")
        self.assertEqual(parse_notes(conv.notes)["vendooStatus"], "active")
        self.assertEqual(progress["updated"], 1)
        self.assertEqual(progress["checked"], 1)
        self.assertFalse(progress["running"])

    async def test_sweeping_an_unchanged_listing_leaves_its_recency_alone(self):
        # The sidebar's "Recent activity" order is updated_at, so a sweep that
        # restamped every item it paged over would reshuffle the list under the
        # reader once per page.
        conv = self.bind_draft("itm1")
        await self._run({"": ([listed_item("itm1")], "")})
        before = ConversationRepo(self.db).get(conv.id).updated_at

        # A second pass over the same inventory has nothing new to say.
        progress = await self._run({"": ([listed_item("itm1")], "")})

        conv = ConversationRepo(self.db).get(conv.id)
        self.assertEqual(progress["checked"], 1)
        self.assertEqual(progress["updated"], 0)
        # The label pass still recorded what Vendoo reported.
        notes = parse_notes(conv.notes)
        self.assertEqual(notes["vendooStatus"], "active")
        self.assertEqual(notes["vendooMarketplaces"], ["ebay"])
        self.assertEqual(conv.updated_at, before)

    async def test_a_real_label_change_still_counts_as_activity(self):
        conv = self.bind_draft("itm1")
        before = ConversationRepo(self.db).get(conv.id).updated_at

        await self._run({"": ([listed_item("itm1")], "")})

        conv = ConversationRepo(self.db).get(conv.id)
        self.assertEqual(conv.status, "active")
        self.assertGreater(conv.updated_at, before)

    async def test_unbound_vendoo_items_are_ignored(self):
        self.bind_draft("mine")
        progress = await self._run({"": ([listed_item("other")], "")})

        self.assertEqual(progress["checked"], 0)
        self.assertEqual(progress["updated"], 0)

    def test_debounce_skips_a_second_pass(self):
        vendoo_label_sync._last_finished_mono = 1e12
        result = vendoo_label_sync.start()
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "recent")

    def test_skips_while_bulk_import_runs(self):
        vendoo_bulk_import._progress = vendoo_bulk_import.BulkImportProgress(running=True)
        try:
            result = vendoo_label_sync.start(force=True)
            self.assertTrue(result["skipped"])
            self.assertEqual(result["reason"], "bulk import running")
        finally:
            vendoo_bulk_import._progress = vendoo_bulk_import.BulkImportProgress()


if __name__ == "__main__":
    unittest.main()
