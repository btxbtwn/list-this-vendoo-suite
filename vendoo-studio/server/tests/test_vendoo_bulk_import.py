from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import vendoo_bulk_import
from vendoo_studio.services.vendoo_import import (
    import_vendoo_item,
    merge_notes,
    parse_notes,
    vendoo_item_status,
    vendoo_listed_marketplaces,
    vendoo_updated_at,
)


def photo_meta(url: str) -> dict:
    return {
        "original_filename": url.rsplit("/", 1)[-1],
        "stored_filename": f"stored-{url.rsplit('/', 1)[-1]}",
        "mime_type": "image/jpeg",
        "size_bytes": 12,
        "checksum": url,
        "width": 10,
        "height": 10,
    }


def vendoo_item(item_id: str, *, title: str, status: dict | None = None, modified: int = 1) -> dict:
    return {
        "id": item_id,
        "itemID": item_id,
        "dateLastModified": modified,
        "generalDetails": {
            "title": title,
            "description": "A tee",
            "price": "24.00",
            # What Vendoo actually stores: a record naming its image server path.
            "images": [{"version": 3, "id": f"images/u1/{item_id}-1.jpg", "originalMaxDimension": 1600}],
        },
        "listings": {"ebay": {"status": status or {"notListed": True}}},
    }


class VendooItemStatusTest(unittest.TestCase):
    def test_unlisted_item_is_a_draft(self):
        self.assertEqual(vendoo_item_status(vendoo_item("a", title="Tee")), "draft")

    def test_listed_item_is_active(self):
        item = vendoo_item("a", title="Tee", status={"listed": True})
        self.assertEqual(vendoo_item_status(item), "active")

    def test_sold_on_any_marketplace_wins(self):
        item = vendoo_item("a", title="Tee", status={"listed": True})
        item["listings"]["poshmark"] = {"status": {"sold": True}}
        self.assertEqual(vendoo_item_status(item), "sold")

    def test_shipped_counts_as_sold(self):
        item = vendoo_item("a", title="Tee", status={"shipped": True})
        self.assertEqual(vendoo_item_status(item), "sold")

    def test_validate_pseudo_listing_is_ignored(self):
        item = vendoo_item("a", title="Tee")
        item["listings"]["validate"] = {"status": {"listed": True}}
        self.assertEqual(vendoo_item_status(item), "draft")

    def test_sale_record_counts_as_sold_after_vendoo_delists(self):
        # Vendoo delists a sold item, leaving the listing flagged delisted; its
        # own Inventory still reads the sale record and calls the item sold.
        item = vendoo_item("a", title="Tee", status={"delisted": True})
        item["saleRecord"] = {"marketplace": "poshmark", "price_sold": 24}
        self.assertEqual(vendoo_item_status(item), "sold")

    def test_sold_on_an_external_listing_counts(self):
        item = vendoo_item("a", title="Tee")
        item["externalListings"] = {"grailed": {"status": {"sold": True}}}
        self.assertEqual(vendoo_item_status(item), "sold")

    def test_listing_sales_count_as_sold(self):
        item = vendoo_item("a", title="Tee", status={"listed": True})
        item["listings"]["ebay"]["sales"] = [{"price_sold": 24}]
        self.assertEqual(vendoo_item_status(item), "sold")

    def test_empty_sale_record_is_not_a_sale(self):
        item = vendoo_item("a", title="Tee")
        item["saleRecord"] = {}
        item["listings"]["ebay"]["sales"] = []
        self.assertEqual(vendoo_item_status(item), "draft")

    def test_external_listing_alone_does_not_make_an_item_active(self):
        item = vendoo_item("a", title="Tee")
        item["externalListings"] = {"grailed": {"status": {"listed": True}}}
        self.assertEqual(vendoo_item_status(item), "draft")

    def test_sale_record_marketplace_stands_in_for_the_cleared_flag(self):
        item = vendoo_item("a", title="Tee", status={"delisted": True})
        item["saleRecord"] = {"marketplace": "poshmark"}
        self.assertEqual(vendoo_listed_marketplaces(item), ["poshmark"])

    def test_update_stamp_prefers_vendoos_own(self):
        item = vendoo_item("a", title="Tee", modified=1750000000000)
        self.assertEqual(vendoo_updated_at(item), "1750000000000")
        self.assertEqual(vendoo_updated_at({"updatedAt": {"_seconds": 12, "_nanoseconds": 5}}), "12.5")


class BulkImportRunTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        vendoo_bulk_import._progress = vendoo_bulk_import.BulkImportProgress()

    async def _run(self, pages: list[list[dict]], download=None) -> dict:
        """Drive one whole run against a canned inventory, page by page."""
        async def fake_list_page(page_token: str, *, ids_only: bool = False):
            index = int(page_token or 0)
            items = pages[index]
            next_token = str(index + 1) if index + 1 < len(pages) else ""
            if ids_only:
                items = [{"id": item["id"]} for item in items]
            return items, next_token

        db = self.db

        class SessionCtx:
            def __enter__(self):
                return db

            def __exit__(self, *args):
                return False

        vendoo_bulk_import._progress = vendoo_bulk_import.BulkImportProgress(running=True)
        with (
            patch.object(vendoo_bulk_import, "_list_page", side_effect=fake_list_page),
            patch("vendoo_studio.database.SessionLocal", SessionCtx),
            patch(
                "vendoo_studio.services.vendoo_import.download_vendoo_photos",
                new_callable=AsyncMock,
                side_effect=download or (lambda urls: [photo_meta(url) for url in urls]),
            ),
        ):
            await vendoo_bulk_import._run()
        return vendoo_bulk_import.status()

    async def test_run_imports_every_page_with_its_photos(self):
        pages = [
            [vendoo_item("a", title="Tee A"), vendoo_item("b", title="Tee B", status={"listed": True})],
            [vendoo_item("c", title="Tee C", status={"sold": True})],
        ]
        progress = await self._run(pages)

        self.assertEqual(progress["photos"], 3)
        self.assertEqual(progress["total"], 3)
        self.assertEqual(progress["imported"], 3)
        self.assertEqual(progress["skipped"], 0)
        self.assertEqual(progress["failed"], 0)
        self.assertFalse(progress["running"])

        repo = ConversationRepo(self.db)
        convs = {conv.title: conv for conv in repo.list_all()}
        self.assertEqual(set(convs), {"Tee A", "Tee B", "Tee C"})
        self.assertEqual(convs["Tee A"].status, "draft")
        self.assertEqual(convs["Tee B"].status, "active")
        self.assertEqual(convs["Tee C"].status, "sold")
        # A sold item belongs on the settled shelf, out of the working list.
        self.assertIsNotNone(convs["Tee C"].settled_at)
        # The photos came down with the item, so nothing is left to fetch.
        photos = repo.get_photos(convs["Tee A"].id)
        self.assertEqual(
            [photo.checksum for photo in photos],
            ["https://images.vendoo.co/images/u1/a-1.jpg"],
        )
        self.assertTrue(JobRepo(self.db).list_by_conversation(convs["Tee A"].id))

    async def test_rerun_skips_items_vendoo_has_not_touched(self):
        pages = [[vendoo_item("a", title="Tee A", modified=5)]]
        await self._run(pages)

        progress = await self._run(pages)

        self.assertEqual(progress["skipped"], 1)
        self.assertEqual(progress["imported"], 0)
        self.assertEqual(progress["updated"], 0)
        self.assertEqual(len(ConversationRepo(self.db).list_all()), 1)

    async def test_rerun_relabels_an_item_studio_read_wrong_before(self):
        # An item Studio labelled a draft under the old sold rule is put right
        # on the next pass, even though Vendoo has not touched it since.
        item = vendoo_item("a", title="Tee A", modified=5, status={"delisted": True})
        item["saleRecord"] = {"marketplace": "poshmark", "price_sold": 24}
        await self._run([[item]])

        repo = ConversationRepo(self.db)
        conv = repo.list_all()[0]
        conv.notes = merge_notes(conv.notes, {"vendooStatus": "draft", "vendooMarketplaces": []})
        repo.update_status(conv.id, "draft")
        self.db.commit()

        progress = await self._run([[item]])

        self.assertEqual(progress["updated"], 1)
        self.assertEqual(progress["skipped"], 0)
        conv = ConversationRepo(self.db).list_all()[0]
        self.assertEqual(conv.status, "sold")
        self.assertEqual(parse_notes(conv.notes)["vendooStatus"], "sold")
        self.assertEqual(parse_notes(conv.notes)["vendooMarketplaces"], ["poshmark"])

    async def test_rerun_updates_an_item_that_changed_in_vendoo(self):
        await self._run([[vendoo_item("a", title="Tee A", modified=5)]])
        progress = await self._run([[vendoo_item("a", title="Tee A", modified=9)]])

        self.assertEqual(progress["updated"], 1)
        self.assertEqual(progress["skipped"], 0)
        conv = ConversationRepo(self.db).list_all()[0]
        self.assertEqual(parse_notes(conv.notes)["vendooUpdatedAt"], "9")

    async def test_an_item_cut_short_is_redone_next_run(self):
        """A stamp is only written once the whole item landed."""
        pages = [[vendoo_item("a", title="Tee A", modified=5)]]

        def boom(urls):
            raise RuntimeError("network died")

        failed = await self._run(pages, download=boom)
        self.assertEqual(failed["failed"], 1)

        progress = await self._run(pages)
        self.assertEqual(progress["skipped"], 0)
        self.assertEqual(progress["updated"], 1)
        conv = ConversationRepo(self.db).list_all()[0]
        self.assertEqual(len(ConversationRepo(self.db).get_photos(conv.id)), 1)

    async def test_a_listing_missing_its_photos_gets_just_its_photos(self):
        """Fields can land while the photos do not; the next run fetches those."""
        pages = [[vendoo_item("a", title="Tee A", modified=5)]]

        progress = await self._run(pages, download=lambda urls: [])
        self.assertEqual(progress["imported"], 1)
        self.assertEqual(progress["photos"], 0)
        conv = ConversationRepo(self.db).list_all()[0]
        revisions = len(ListingRepo(self.db).get_revisions(conv.id))

        progress = await self._run(pages)
        self.assertEqual(progress["skipped"], 0)
        self.assertEqual(progress["updated"], 1)
        self.assertEqual(progress["photos"], 1)
        self.assertEqual(len(ConversationRepo(self.db).get_photos(conv.id)), 1)
        # Repairing photos must not write the listing over again.
        self.assertEqual(len(ListingRepo(self.db).get_revisions(conv.id)), revisions)

        # With everything local, a third run has nothing to do.
        progress = await self._run(pages)
        self.assertEqual(progress["skipped"], 1)

    async def test_one_bad_item_does_not_end_the_run(self):
        pages = [[vendoo_item("a", title="Tee A"), vendoo_item("b", title="Tee B")]]

        async def flaky(db, *, item_id: str, **kwargs):
            if item_id == "a":
                raise RuntimeError("boom")
            return await import_vendoo_item(db, item_id=item_id, **kwargs)

        with patch("vendoo_studio.services.vendoo_import.import_vendoo_item", side_effect=flaky):
            progress = await self._run(pages)

        self.assertEqual(progress["failed"], 1)
        self.assertEqual(progress["imported"], 1)
        self.assertEqual(progress["failures"][0]["item_id"], "a")
        self.assertEqual(len(ConversationRepo(self.db).list_all()), 1)


class BulkImportControlTest(unittest.IsolatedAsyncioTestCase):
    """Starting, refusing a second run, and stopping one — through the service."""

    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()
        vendoo_bulk_import._progress = vendoo_bulk_import.BulkImportProgress()
        vendoo_bulk_import._task = None

    def _session_patch(self):
        db = self.db

        class SessionCtx:
            def __enter__(self):
                return db

            def __exit__(self, *args):
                return False

        return patch("vendoo_studio.database.SessionLocal", SessionCtx)

    def test_status_before_any_run(self):
        app.dependency_overrides[get_db] = lambda: iter([self.db])
        try:
            body = TestClient(app).get("/api/imports/vendoo/bulk").json()
        finally:
            app.dependency_overrides.clear()
        self.assertFalse(body["running"])
        self.assertEqual(body["processed"], 0)

    async def test_a_run_without_chrome_reports_why_it_stopped(self):
        with (
            self._session_patch(),
            patch(
                "vendoo_studio.services.vendoo_create.run_ops",
                side_effect=BrowserBridgeError("Connect Chrome to use the Vendoo browser."),
            ),
        ):
            vendoo_bulk_import.start()
            await asyncio.gather(vendoo_bulk_import._task, return_exceptions=True)

        status = vendoo_bulk_import.status()
        self.assertIn("Connect Chrome", status["error"])
        self.assertEqual(status["processed"], 0)
        self.assertFalse(status["running"])

    async def test_a_second_run_is_refused_while_one_is_going(self):
        released: list[bool] = []

        async def slow_list_page(page_token: str, *, ids_only: bool = False):
            while not released:
                await asyncio.sleep(0.01)
            return [], ""

        with self._session_patch(), patch.object(
            vendoo_bulk_import, "_list_page", side_effect=slow_list_page
        ):
            vendoo_bulk_import.start()
            await asyncio.sleep(0.02)
            with self.assertRaises(RuntimeError):
                vendoo_bulk_import.start()
            self.assertTrue(vendoo_bulk_import.cancel())
            released.append(True)
            await asyncio.gather(vendoo_bulk_import._task, return_exceptions=True)

        status = vendoo_bulk_import.status()
        self.assertTrue(status["cancelled"])
        self.assertFalse(status["running"])
        self.assertFalse(vendoo_bulk_import.cancel())


if __name__ == "__main__":
    unittest.main()
