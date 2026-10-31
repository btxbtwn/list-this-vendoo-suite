from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import utcnow
from vendoo_studio.repositories.marketplace_listings import MarketplaceListingRepo
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import native_marketplaces as native
from vendoo_studio.services.api_job_lock import api_job_is_live, claim_api_job, release_api_job
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.services.job_watchdog import fail_stalled_jobs
from vendoo_studio.services.photo_store import LocalPhotoStore
from vendoo_studio.services.vendoo_import import merge_notes, parse_notes

URLS = {"mercari": "https://www.mercari.com/sell/draft/testNativeDraft/",
        "depop": "https://www.depop.com/sellinghub/drafts/edit/123456/"}
LIVE = {"mercari": "https://www.mercari.com/us/item/m123456789/", "depop": None}
POSH_URL = "https://poshmark.com/listing/6adc371572e62463d992ffef"
SELLWILD_URL = "https://sellwild.com/product/123/test"
LISTING = {"title": "ANTEROOM DRAFT CHECK - DO NOT PUBLISH", "description": "Private test draft.", "price": 12,
           "size": "M",
           "weight_oz": 8, "package_dimensions_in": "12x9x2",
           "marketplace_category_ids": {"ebay": "11450", "poshmark": "5c3c3d4a6a2b3c4d5e6f7081", "mercari": "1934", "depop": "menswear_tshirts"},
           "direct_category_ids": {"ebay": "11450", "poshmark": "01008c10d97b4e1245005764/07008c10d97b4e1245005764/33009813d97b4e3995005764",
                                   "mercari": "1934", "depop": "menswear_tshirts"},
           "mercari_specifics": {"shipsFrom": "70125", "shippingClassId": "2550",
                                "package": {"fitsShoebox": "no", "pounds": 1}},
           "depop_specifics": {"parcelSize": "Medium"}}
SELLWILD = {"sellwild_category_id": 272, "sellwild_condition_id": 2}


class NativeMarketplacesTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        store = LocalPhotoStore(directory)
        for name in ("test.jpg", "back.jpg", "collage.jpg"):
            store.put(name, b"test photo")
        self.enterContext(patch("vendoo_studio.services.photo_store._store", store))
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine)
        self.db = self.sessions()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title=LISTING["title"])
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, LISTING, "model")
        ConversationRepo(self.db).add_photo(self.conv.id, "test.jpg", "test.jpg", "image/jpeg", 1)
        self.base = f"/api/conversations/{self.conv.id}/native-marketplaces"
        self.bridge = self.enterContext(patch("vendoo_studio.services.native_marketplaces.browser_bridge.request", new_callable=AsyncMock))
        self.manager = SimpleNamespace(connected=True, build="test-build", send_message=AsyncMock(return_value=True))
        self.enterContext(patch("vendoo_studio.services.extension_connection.extension_manager", self.manager))
        self.enterContext(patch("vendoo_studio.services.native_marketplaces.expected_extension_build", return_value="test-build"))
        self.enterContext(patch("vendoo_studio.services.extension_connection.schedule_advance_job_queue"))
        self.enterContext(patch("vendoo_studio.database.SessionLocal", self.sessions))
        self.enterContext(patch.object(native, "SETTLE_POLL_S", 0))
        self.launched = []
        self.enterContext(patch.object(native, "_launch", self.launched.append))

    def tearDown(self):
        for coro in self.launched:
            coro.close()
        app.dependency_overrides.clear()
        self.db.close()

    # --- helpers ---------------------------------------------------------------

    def run_jobs(self):
        while self.launched:
            asyncio.run(self.launched.pop(0))
        self.db.expire_all()

    def list(self, platform="mercari", **extra):
        response = self.client.post(f"{self.base}/{platform}/list", json={"revision_id": self.rev.id, "confirm": True, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["running"])
        self.run_jobs()
        return self.status()[platform]

    def status(self):
        return self.client.get(self.base).json()

    def test_editor_preflight_uses_saved_native_requirements_without_chrome_or_category_writes(self):
        import copy
        from vendoo_studio.services import native_contract

        snapshot = copy.deepcopy(LISTING)
        snapshot["direct_category_ids"] = {"depop": "menswear_tshirts"}
        snapshot = native.direct_preflight.prepare(self.db, self.conv, snapshot, "depop")
        form = {"category_id": "menswear_tshirts", "page_labels": True, "fields": [
            {"path": "depop_specifics.size", "label": "Size", "required": True,
             "selection_only": True, "options": ["M", "L"]}]}
        snapshot[native_contract.KEY] = native_contract.capture(snapshot, {"depop": form}, ["depop"])
        revision = ListingRepo(self.db).save_revision(self.conv.id, snapshot, "native_schema")
        before = copy.deepcopy(revision.listing_json)
        read = AsyncMock(side_effect=AssertionError("Chrome or remote catalog used during editor preflight"))
        with patch("vendoo_studio.services.chrome_catalog.live_preview", new=read):
            for connected in (False, True):
                self.manager.connected = connected
                response = self.client.get(f"{self.base}/preflight")
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()["marketplaces"]["depop"]
                self.assertFalse(result["ready"])
                self.assertTrue(any(gap["field"] == "depop_specifics.size" for gap in result["gaps"]), result)
        read.assert_not_awaited()
        self.bridge.assert_not_awaited()
        self.db.expire_all()
        self.assertEqual(ListingRepo(self.db).get_revision(revision.id).listing_json, before)
        self.assertEqual(ListingRepo(self.db).get_current(self.conv.id).current_revision_id, revision.id)
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])

    def record(self, platform):
        return MarketplaceListingRepo(self.db).get(self.conv.id, platform)

    def actions(self):
        return [call.args[2]["action"] for call in self.bridge.call_args_list if call.args[1] == "marketplace.execute"]

    def published(self, platform):
        return {"ok": True, "state": "published", "draft_url": URLS[platform], **({"listing_url": LIVE[platform]} if LIVE[platform] else {})}

    # --- listing -----------------------------------------------------------------

    def test_list_without_a_category_never_starts_a_marketplace_job(self):
        listing = {**LISTING, "marketplace_category_ids": {}, "marketplace_category_objects": {},
                   "marketplace_categories": {}, "direct_category_ids": {}}
        revision = ListingRepo(self.db).save_revision(self.conv.id, listing, "user_form")
        self.bridge.reset_mock()
        response = self.client.post(f"{self.base}/mercari/list", json={"revision_id": revision.id, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["error_code"], "missing_fields")
        self.assertEqual(self.launched, [])
        self.assertNotIn("list", self.actions())

    def test_save_draft_runs_one_private_step_and_never_publishes_on_check(self):
        for platform in URLS:
            with self.subTest(platform=platform):
                self.bridge.reset_mock()
                self.bridge.return_value = {"ok": True, "state": "draft", "draft_url": URLS[platform]}
                response = self.client.post(f"{self.base}/{platform}/draft", json={"revision_id": self.rev.id})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()["running"])
                self.run_jobs()
                self.assertEqual(self.actions(), ["save_draft"])
                self.assertIs(self.bridge.call_args.args[2]["confirm"], False)
                self.assertEqual(self.record(platform)["state"], "draft")
                # Re-saving updates the same draft, with no publish step.
                response = self.client.post(f"{self.base}/{platform}/draft", json={"revision_id": self.rev.id})
                self.assertEqual(response.status_code, 200, response.text)
                self.run_jobs()
                self.assertEqual(self.actions(), ["save_draft", "save_draft"])
                self.assertEqual(self.bridge.call_args.args[2]["draft_url"], URLS[platform])

    def test_an_approved_job_keeps_its_photos_after_the_item_photos_are_replaced(self):
        from vendoo_studio.services.photo_store import photo_store
        from vendoo_studio.services.listing_delete import delete_listing

        repo = ConversationRepo(self.db)
        [original] = repo.get_photos(self.conv.id)
        self.bridge.return_value = {"ok": True, "state": "draft", "draft_url": URLS["mercari"]}
        reply = self.client.post(f"{self.base}/mercari/draft", json={"revision_id": self.rev.id})
        self.assertEqual(reply.status_code, 200, reply.text)
        job_id = reply.json()["job_id"]
        pinned = JobRepo(self.db).get(job_id).listing_snapshot["_approved_photos"][0]["stored_filename"]
        repo.delete_photo(self.conv.id, original.id)
        photo_store().delete("test.jpg")
        photo_store().put("new.jpg", b"Different product")
        replacement = repo.add_photo(self.conv.id, "new.jpg", "new.jpg", "image/jpeg", 17)
        self.run_jobs()
        payload = self.bridge.call_args.args[2]
        self.assertEqual([photo["id"] for photo in payload["photos"]], [original.id])
        image = self.client.get(f"/api/jobs/{job_id}/photos/{original.id}")
        self.assertEqual(image.status_code, 200, image.text)
        self.assertEqual(image.content, b"test photo")
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}/photos/{replacement.id}").status_code, 404)
        delete_listing(self.db, self.conv.id)
        self.assertFalse(photo_store().exists(pinned))

    def test_a_missing_photo_prevents_dispatch(self):
        from vendoo_studio.services.photo_store import photo_store

        photo_store().delete("test.jpg")
        reply = self.client.post(f"{self.base}/mercari/draft", json={"revision_id": self.rev.id})
        self.assertEqual(reply.status_code, 409, reply.text)
        self.assertEqual(self.launched, [])
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])

    def test_clear_keeps_approved_files_shared_by_the_action_and_its_check(self):
        from vendoo_studio.services.listing_delete import wipe_contents
        from vendoo_studio.services.photo_store import photo_store

        draft = {"ok": True, "state": "draft", "draft_url": URLS["mercari"]}
        self.bridge.return_value = draft
        saved = self.client.post(f"{self.base}/mercari/draft", json={"revision_id": self.rev.id})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.run_jobs()
        job_id = saved.json()["job_id"]
        key = JobRepo(self.db).get(job_id).listing_snapshot["_approved_photos"][0]["stored_filename"]
        self.bridge.return_value = {"finished": True, "result": draft}
        checked = self.client.post(f"{self.base}/mercari/check")
        self.assertEqual(checked.status_code, 200, checked.text)
        wipe_contents(self.db, self.conv.id, keep_photos=True, keep_marketplace_listings=True)
        self.db.commit()
        self.assertTrue(photo_store().exists(key))
        self.assertIsNotNone(JobRepo(self.db).get(job_id))

    def test_listing_a_saved_draft_refreshes_a_photo_edited_since_the_save(self):
        from vendoo_studio.services.photo_store import photo_store

        self.bridge.return_value = {"ok": True, "state": "draft", "draft_url": URLS["mercari"]}
        reply = self.client.post(f"{self.base}/mercari/draft", json={"revision_id": self.rev.id})
        self.assertEqual(reply.status_code, 200, reply.text)
        self.run_jobs()
        [photo] = ConversationRepo(self.db).get_photos(self.conv.id)
        photo_store().put("edited.jpg", b"Edited photo")
        photo.stored_filename = "edited.jpg"
        self.db.commit()
        self.bridge.reset_mock()
        self.bridge.side_effect = [
            {"ok": True, "state": "draft", "draft_url": URLS["mercari"]},
            self.published("mercari"),
        ]
        self.list("mercari")
        self.assertEqual(self.actions(), ["save_draft", "publish"])

    def test_a_form_with_its_own_photos_sends_them_and_every_other_form_keeps_the_item_photos(self):
        repo = ConversationRepo(self.db)
        [front] = repo.get_photos(self.conv.id)
        back = repo.add_photo(self.conv.id, "back.jpg", "back.jpg", "image/jpeg", 1)
        collage = repo.add_photo(self.conv.id, "collage.jpg", "collage.jpg", "image/jpeg", 1, marketplace="mercari")
        repo.add_photo(self.conv.id, "stock.jpg", "stock.jpg", "image/jpeg", 1, marketplace="depop")
        self.rev = ListingRepo(self.db).save_revision(
            self.conv.id, {**LISTING, "marketplace_photos": {"mercari": [collage.id, back.id]}}, "user_form")
        sent = {}
        for platform in URLS:
            self.bridge.return_value = {"ok": True, "state": "draft", "draft_url": URLS[platform]}
            response = self.client.post(f"{self.base}/{platform}/draft", json={"revision_id": self.rev.id})
            self.assertEqual(response.status_code, 200, response.text)
            self.run_jobs()
            sent[platform] = [photo["id"] for photo in self.bridge.call_args.args[2]["photos"]]
            self.assertEqual(self.record(platform)["photo_ids"], sent[platform])
        # Mercari's pick, in its order; Depop's own photo is not ticked, so Depop gets the item's.
        self.assertEqual(sent, {"mercari": [collage.id, back.id], "depop": [front.id, back.id]})

    def test_draft_route_refuses_publish_parameters_unsupported_markets_and_live_items(self):
        response = self.client.post(f"{self.base}/mercari/draft", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(response.status_code, 422)
        for market in ["sellwild", "vinted"]:
            response = self.client.post(f"{self.base}/{market}/draft", json={"revision_id": self.rev.id})
            self.assertEqual(response.status_code, 400, response.text)
        MarketplaceListingRepo(self.db).save(self.conv.id, "mercari", {"state": "published", "listing_id": "m123456789",
                                                                     "listing_url": LIVE["mercari"]})
        response = self.client.post(f"{self.base}/mercari/draft", json={"revision_id": self.rev.id})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.actions(), [])
        self.assertEqual(self.launched, [])

    def test_poshmark_saves_and_reuses_a_private_draft_without_publication(self):
        draft = "https://poshmark.com/edit-listing/6adc371572e62463d992ffef"
        self.bridge.return_value = {"ok": True, "state": "draft", "draft_url": draft}
        for _ in range(2):
            response = self.client.post(f"{self.base}/poshmark/draft", json={"revision_id": self.rev.id})
            self.assertEqual(response.status_code, 200, response.text)
            self.run_jobs()
            self.assertEqual(self.record("poshmark")["state"], "draft")
            payload = self.bridge.call_args.args[2]
            self.assertEqual((payload["action"], payload["confirm"]), ("save_draft", False))
        self.assertEqual(self.actions(), ["save_draft", "save_draft"])
        self.assertEqual(payload["draft_url"], draft)
        context = native._result_context(self.db, self.conv.id, "poshmark", self.record("poshmark"), LISTING, draft)
        self.assertEqual(context["listing"], LISTING)
        self.assertEqual(context["expected_photo_count"], 1)
        self.bridge.return_value = {"ok": True, "state": "published", "listing_url": POSH_URL}
        self.assertEqual(self.list("poshmark")["state"], "published")
        self.assertEqual(self.actions(), ["save_draft", "save_draft", "list"])
        self.assertEqual(self.bridge.call_args.args[2]["draft_url"], draft)

    def test_poshmark_draft_links_reject_other_hosts_queries_and_invalid_ids(self):
        draft = "https://poshmark.com/edit-listing/6adc371572e62463d992ffef"
        self.assertEqual(native.draft_url("poshmark", draft), draft)
        for bad in [draft + "?publish=true", draft + "#publish", draft.replace("poshmark.com", "evil.example"), draft[:-1]]:
            with self.subTest(url=bad), self.assertRaises(native.NativeMarketplaceError):
                native.draft_url("poshmark", bad)

    def test_recovery_keeps_category_size_shipping_and_the_sent_photo_count(self):
        for market in ("mercari", "depop", "poshmark"):
            context = native._result_context(self.db, self.conv.id, market,
                                            {"action": "save_draft", "previous_revision_id": "older", "photo_ids": ["sent-1", "sent-2"]},
                                            LISTING, None)
            self.assertEqual(context["listing"], LISTING)
            self.assertEqual(context["expected_photo_count"], 2)

    def test_list_saves_then_publishes_in_one_job_that_holds_the_slot(self):
        import gc
        from sqlalchemy import event

        # An unclosed observer session can be collected during the worker's
        # next flush and roll back their shared StaticPool connection.
        def collect_during_flush(session, context):
            gc.collect()

        event.listen(self.sessions.class_, "after_flush", collect_during_flush)
        self.addCleanup(event.remove, self.sessions.class_, "after_flush", collect_during_flush)
        for platform in URLS:
            seen = []

            async def bridge(job, kind, payload, timeout=None, platform=platform, seen=seen):
                with self.sessions() as observer:
                    seen.append([j.id for j in JobRepo(observer).get_running()])
                return ({"ok": True, "state": "draft", "draft_url": URLS[platform]} if payload["action"] == "save_draft"
                        else self.published(platform))

            self.bridge.side_effect = bridge
            self.bridge.reset_mock()
            record = self.list(platform)
            self.assertEqual(record["state"], "published", record)
            self.assertEqual(self.actions(), ["save_draft", "publish"])
            calls = self.bridge.call_args_list
            self.assertFalse(calls[0].args[2]["confirm"])
            self.assertTrue(calls[1].args[2]["confirm"])
            self.assertEqual(calls[1].args[2]["draft_url"], URLS[platform])
            # Each step is journaled under its own id, and one job held the slot for both.
            self.assertEqual(calls[0].args[2]["operation_id"], record["job_id"])
            self.assertEqual(calls[1].args[2]["operation_id"], f"{record['job_id']}-2")
            self.assertEqual(seen, [[record["job_id"]], [record["job_id"]]])
            self.assertEqual(JobRepo(self.db).get(record["job_id"]).status, "completed")
            self.assertFalse(api_job_is_live(record["job_id"]))

    def test_list_does_not_publish_when_preparation_fails(self):
        self.bridge.return_value = {"ok": False, "safe_to_retry": True, "error": "Mercari needs a brand.", "error_code": "missing_fields",
                                    "fields": [{"field": "brand", "message": "Mercari needs a brand."}],
                                    "marketplace_message": "Brand is required"}
        record = self.list()
        self.assertEqual(record["state"], "not_saved")
        self.assertEqual(self.actions(), ["save_draft"])
        # A definite refusal says why, without the "unconfirmed" warning.
        self.assertEqual(record["error"], "Mercari needs a brand.")
        self.assertEqual((record["error_code"], record["marketplace_message"]), ("missing_fields", "Brand is required"))
        self.assertEqual(record["error_fields"], [{"field": "brand", "message": "Mercari needs a brand."}])
        self.assertEqual(JobRepo(self.db).get(record["job_id"]).status, "failed")
        events = [event.payload for event in JobRepo(self.db).get_events(record["job_id"]) if event.event_type == "native_result"]
        self.assertEqual(events[-1]["marketplace_message"], "Brand is required")

    def test_list_finishes_the_current_draft_without_creating_another(self):
        self.bridge.side_effect = [{"ok": False, "safe_to_retry": True, "draft_url": URLS["depop"], "error": "Finish photos."}]
        self.list("depop")
        self.assertEqual(self.record("depop")["state"], "draft")
        MarketplaceListingRepo(self.db).save(self.conv.id, "depop", {"revision_id": self.rev.id, "error": None})
        self.bridge.reset_mock()
        self.bridge.side_effect = [self.published("depop")]
        self.assertEqual(self.list("depop")["state"], "published")
        self.assertEqual(self.actions(), ["publish"])
        self.assertEqual(self.bridge.call_args.args[2]["draft_url"], URLS["depop"])

    def test_list_requires_confirmation_before_any_write(self):
        self.assertEqual(self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id}).status_code, 400)
        self.bridge.assert_not_called()
        self.assertFalse(self.launched)

    def test_publish_still_requires_the_explicit_list_endpoint(self):
        self.assertIn(self.client.post(f"{self.base}/mercari/publish", json={"revision_id": self.rev.id, "confirm": True}).status_code, {404, 405})

    def test_list_refuses_an_existing_imported_listing_before_preparing_or_writing(self):
        self.conv.notes = merge_notes(self.conv.notes, {"vendooListingUrls": {"mercari": LIVE["mercari"]}})
        self.db.commit()
        with patch.object(native, "_preflight", new_callable=AsyncMock) as prepare:
            response = self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("already listed", response.text)
        prepare.assert_not_called()
        self.bridge.assert_not_called()
        self.assertFalse(self.launched)
        self.assertFalse(JobRepo(self.db).list_by_conversation(self.conv.id))

    def test_list_refuses_an_item_sold_on_another_marketplace(self):
        self.conv.notes = merge_notes(self.conv.notes, {"marketplaceMarks": {"depop": {"state": "sold"}}})
        self.db.commit()
        with patch.object(native, "_preflight", new_callable=AsyncMock) as prepare:
            response = self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("sold", response.text)
        prepare.assert_not_called()
        self.bridge.assert_not_called()
        self.assertFalse(self.launched)

    def test_an_imported_listing_marked_not_listed_can_be_listed_again(self):
        self.conv.notes = merge_notes(self.conv.notes, {
            "vendooListingUrls": {"mercari": LIVE["mercari"]},
            "marketplaceMarks": {"mercari": {"state": "not_listed", "listing_id": "m123456789"}},
        })
        self.db.commit()
        self.bridge.side_effect = [{"ok": True, "state": "draft", "draft_url": URLS["mercari"]}, self.published("mercari")]
        self.assertEqual(self.list("mercari")["state"], "published")

    def test_poshmark_lists_in_one_step_and_updates_the_same_listing(self):
        self.bridge.return_value = {"ok": True, "state": "published", "listing_url": POSH_URL}
        record = self.list("poshmark")
        self.assertEqual((record["state"], record["listing_url"]), ("published", POSH_URL))
        self.assertEqual(self.actions(), ["list"])
        self.assertEqual(self.client.post(f"{self.base}/poshmark/list", json={"revision_id": self.rev.id, "confirm": True}).status_code, 409)
        revised = ListingRepo(self.db).save_revision(self.conv.id, {**LISTING, "title": "Updated tee"}, "user")
        self.rev = revised
        self.assertEqual(self.client.post(f"{self.base}/poshmark/update", json={"revision_id": revised.id}).status_code, 400)
        self.bridge.reset_mock()
        response = self.client.post(f"{self.base}/poshmark/update", json={"revision_id": revised.id, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.run_jobs()
        payload = self.bridge.call_args.args[2]
        self.assertEqual((payload["action"], payload["listing_id"], payload["confirm"]), ("update", "6adc371572e62463d992ffef", True))
        self.bridge.return_value = {"ok": False, "safe_to_retry": True, "error": "Poshmark needs a size.", "error_code": "rejected"}
        self.client.post(f"{self.base}/poshmark/update", json={"revision_id": revised.id, "confirm": True})
        self.run_jobs()
        refused = self.record("poshmark")
        self.assertEqual(refused["state"], "published")
        self.assertIn("size", refused["error"])
        mercari = self.client.post(f"{self.base}/mercari/update", json={"revision_id": revised.id, "confirm": True})
        self.assertEqual(mercari.status_code, 409)
        self.assertIn("not live on Mercari", mercari.text)

    def live_on(self, platform, listing_id, url, **record):
        MarketplaceListingRepo(self.db).save(self.conv.id, platform, {
            "state": "published", "listing_id": listing_id, "listing_url": url, "revision_id": self.rev.id, **record})
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, {**LISTING, "title": "Updated tee"}, "user")

    def update(self, platform):
        self.enterContext(patch.object(native.direct_preflight, "gaps", return_value=[]))
        response = self.client.post(f"{self.base}/{platform}/update", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.run_jobs()
        return self.record(platform)

    def test_mercari_vinted_and_sellwild_update_the_live_listing_in_place(self):
        cases = [("mercari", "m123456789", LIVE["mercari"], {"photo_ids": ["kept"]}),
                 ("vinted", "4567890123", "https://www.vinted.com/items/4567890123", {}),
                 ("sellwild", "123", SELLWILD_URL, {"photo_ids": ["photos-from-an-earlier-list"], **SELLWILD})]
        for platform, listing_id, url, record in cases:
            with self.subTest(platform=platform):
                self.live_on(platform, listing_id, url, **record)
                self.bridge.reset_mock()
                self.bridge.return_value = {"ok": True, "state": "published", "listing_url": url}
                updated = self.update(platform)
                self.assertEqual(self.actions(), ["update"])
                payload = self.bridge.call_args.args[2]
                self.assertEqual((payload["action"], payload["listing_id"], payload["confirm"]), ("update", listing_id, True))
                self.assertEqual((updated["state"], updated["listing_id"], updated["revision_id"]), ("published", listing_id, self.rev.id))
                if platform == "mercari":
                    self.assertEqual(updated["photo_ids"], ["kept"])

    def test_a_sellwild_edit_held_for_review_settles_as_pending_review(self):
        self.live_on("sellwild", "123", SELLWILD_URL, **SELLWILD)
        self.bridge.return_value = {"ok": True, "state": "pending_review", "listing_url": SELLWILD_URL}
        self.assertEqual(self.update("sellwild")["state"], "pending_review")

    def test_a_live_update_answer_naming_another_listing_is_not_trusted(self):
        self.live_on("vinted", "4567890123", "https://www.vinted.com/items/4567890123")
        self.bridge.return_value = {"ok": True, "state": "published", "listing_url": "https://www.vinted.com/items/999"}
        updated = self.update("vinted")
        self.assertNotEqual(updated["state"], "published")
        self.assertEqual(self.actions(), ["update"])

    def test_a_refused_poshmark_listing_can_be_tried_again(self):
        self.bridge.return_value = {"ok": False, "safe_to_retry": True, "error": "Poshmark needs a size.", "error_code": "rejected"}
        self.assertEqual(self.list("poshmark")["state"], "not_saved")
        self.bridge.return_value = {"ok": True, "state": "published", "listing_url": POSH_URL}
        self.assertEqual(self.list("poshmark")["state"], "published")

    def test_sellwild_records_the_choice_then_lists_once(self):
        self.bridge.return_value = {"ok": True, "state": "pending_review", "listing_url": SELLWILD_URL}
        record = self.list("sellwild", **SELLWILD)
        self.assertEqual(record["state"], "pending_review")
        payload = self.bridge.call_args.args[2]
        self.assertEqual((payload["action"], payload["confirm"]), ("publish", True))
        self.assertEqual(payload["sellwild"], {"category_id": 272, "condition_id": 2, "parcel_template": "", "coupon_ids": [],
                                               "fixed_package": False, "package_dimensions": {"depth": 12.0, "width": 9.0, "height": 2.0}})
        self.assertTrue(payload["local_draft_id"])
        self.assertEqual(self.client.post(f"{self.base}/sellwild/list", json={"revision_id": self.rev.id, "confirm": True, **SELLWILD}).status_code, 409)
        self.assertEqual(self.bridge.call_count, 1)

    def test_sellwild_requires_a_saved_category_instead_of_matching_one_at_list_time(self):
        mens = {**LISTING, "condition": "Pre-Owned - Good", "category_path": "Clothing, Shoes & Accessories > Men > Coats & Jackets"}
        mens.pop("marketplace_category_ids")
        rev = ListingRepo(self.db).save_revision(self.conv.id, mens, "model")
        with self.assertRaises(native.NativeMarketplaceError):
            native.save_local_sellwild_draft(self.conv.id, native.ListRequest(revision_id=rev.id, sellwild_condition_id=2), self.db)
        native.save_local_sellwild_draft(self.conv.id, native.ListRequest(
            revision_id=rev.id, sellwild_category_id=272, sellwild_condition_id=2), self.db)
        record = self.record("sellwild")
        self.assertEqual(record["sellwild_category_id"], 272)
        self.assertEqual(record["sellwild_condition_id"], 2)
        payload = native._execute_payload("sellwild", "publish", {**record, "operation_id": "op"}, mens, [], "job")["sellwild"]
        self.assertEqual((payload["category_id"], payload["condition_id"]), (272, 2))
        boys = {**mens, "category_path": "", "department": "Boys", "title": "Columbia windbreaker jacket",
                "marketplace_category_objects": {"sellwild": {"displayPath": ["Fashion", "Mens Clothing"]}}}
        payload = native._execute_payload("sellwild", "publish", {**record, "operation_id": "op"}, boys, [], "job")["sellwild"]
        self.assertEqual((payload["category_id"], payload["condition_id"]), (272, 2))

    def test_sellwild_needs_a_category_and_condition(self):
        for extra in ({"sellwild_category_id": 183, "sellwild_condition_id": 2}, {"sellwild_category_id": 272, "sellwild_condition_id": 9}):
            response = self.client.post(f"{self.base}/sellwild/list", json={"revision_id": self.rev.id, "confirm": True, **extra})
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertFalse(body["running"])
            self.assertEqual(body["error_code"], "missing_fields")
        self.bridge.assert_not_called()
        self.assertFalse(self.launched)

    def test_sellwild_match_prefers_marketplace_categories_and_ignores_sleeve_words(self):
        tee = {"title": "Graphic tee", "category_path": "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts",
               "marketplace_category_objects": {"poshmark": {"displayPath": ["Men", "Shirts", "Tees - Short Sleeve"]}}}
        self.assertEqual(native.suggest_sellwild(tee)["category_id"], 270)
        self.assertEqual(native.suggest_sellwild({"title": "Kids hoodie", "category_path": "Clothing, Shoes & Accessories > Kids > Boys"})["category_id"], 246)
        self.assertEqual(native.suggest_sellwild({"title": "Jacket", "sellwild_specifics": {"nativeCategoryId": 269}})["category_id"], 269)

    def test_etsy_uses_the_listing_package(self):
        self.assertEqual(native.listing_package({"weight_lb": 1, "weight_oz": 4, "package_dimensions_in": "13x10x3"}),
                         {"item_weight": 20.0, "item_length": 13.0, "item_width": 10.0, "item_height": 3.0,
                          "item_weight_unit": "oz", "item_dimensions_unit": "in"})
        self.assertIsNone(native.listing_package({"weight_oz": 0, "package_dimensions_in": "13x10x3"}))

    def test_sellwild_form_choices_override_old_picks_and_clears_do_not_restore_them(self):
        from vendoo_studio.services import sellwild_listing
        from vendoo_studio.services.direct_preflight import Context

        listing = {**LISTING, "description": "", "sellwild_specifics": {"nativeCategoryId": "246", "nativeConditionId": "3"}}
        old = {"sellwild_category_id": 272, "sellwild_condition_id": 2}
        self.assertEqual(sellwild_listing.chosen(listing, old), {"category_id": 246, "condition_id": 3})
        self.assertNotIn("description", [row["field"] for row in sellwild_listing.requirements(listing, Context(choices=old))])
        listing["sellwild_specifics"]["nativeCategoryId"] = ""
        self.assertIsNone(sellwild_listing.chosen(listing, old)["category_id"])
        self.assertIn("sellwild_specifics.nativeCategoryId", [row["field"] for row in sellwild_listing.requirements(listing, Context(choices=old))])

    def test_sellwild_native_packaging_uses_the_template_sides_in_the_create_payload(self):
        from vendoo_studio.services import sellwild_listing
        from vendoo_studio.services.direct_preflight import Context

        listing = {**LISTING, "weight_oz": 0, "package_dimensions_in": "", "sellwild_specifics": {
            "nativeCategoryId": 246, "nativeConditionId": 3, "parcelTemplate": "USPS_FlatRatePaddedEnvelope"}}
        self.assertEqual(sellwild_listing.package_sides(listing), [13, 10, 1])
        self.assertEqual(sellwild_listing.requirements(listing, Context()), [])
        payload = native._execute_payload("sellwild", "publish", {"operation_id": "test"}, listing, [], "job")["sellwild"]
        self.assertEqual(payload["parcel_template"], "USPS_FlatRatePaddedEnvelope")
        self.assertTrue(payload["fixed_package"])
        self.assertEqual(payload["package_dimensions"], {"depth": 13, "width": 10, "height": 1})
        # Irregular Parcel has sides but is not flat rate, so Sellwild still asks for a weight.
        listing["sellwild_specifics"]["parcelTemplate"] = "USPS_IrregularParcel"
        listing["weight_lb"] = 0
        self.assertFalse(native._execute_payload("sellwild", "publish", {"operation_id": "test"}, listing, [], "job")["sellwild"]["fixed_package"])
        self.assertIn("weight_oz", [row["field"] for row in sellwild_listing.requirements(listing, Context())])
        listing["sellwild_specifics"]["parcelTemplate"] = "invented"
        self.assertIn("sellwild_specifics.parcelTemplate", [row["field"] for row in sellwild_listing.requirements(listing, Context())])

    def test_sellwild_options_suggest_from_the_listing(self):
        listing = {**LISTING, "title": "Vintage Patagonia fleece jacket", "condition": "Pre-Owned - Good",
                   "category_path": "Clothing, Shoes & Accessories > Men > Men's Clothing > Coats, Jackets & Vests"}
        listing.pop("depop_specifics", None)
        ListingRepo(self.db).save_revision(self.conv.id, listing, "model")
        result = self.client.get(f"{self.base}/sellwild/options").json()
        self.assertEqual(result["suggested"], {"category_id": 272, "condition_id": 3})
        self.assertEqual(len(result["conditions"]), 5)

    def test_a_listed_poshmark_post_keeps_the_extensions_warning(self):
        outcome = native._outcome("poshmark", "list", {}, {
            "ok": True, "state": "published", "listing_url": POSH_URL, "warning": "Poshmark left Smart Pricing on.",
        })
        self.assertEqual((outcome["state"], outcome["error"], outcome["error_code"]), ("published", "Poshmark left Smart Pricing on.", None))

    def test_a_depop_category_change_keeps_the_rewritten_slug(self):
        old = "https://www.depop.com/products/vassarette-womens-tan-vest/"
        new = "https://www.depop.com/products/vassarette-womens-tan-sweater/"
        outcome = native._outcome("depop", "update", {
            "state": "published", "listing_id": "vassarette-womens-tan-vest", "listing_url": old,
        }, {"ok": True, "state": "published", "listing_url": new, "previous_slug": "vassarette-womens-tan-vest"})
        self.assertEqual(outcome["listing_id"], "vassarette-womens-tan-sweater")
        self.assertEqual(outcome["listing_url"], new)
        with self.assertRaises(native.NativeMarketplaceError):
            native._outcome("depop", "update", {
                "state": "published", "listing_id": "vassarette-womens-tan-vest", "listing_url": old,
            }, {"ok": True, "state": "published", "listing_url": new, "previous_slug": "someone-elses-vest"})

    def test_a_depop_publish_keeps_the_public_product_link(self):
        url = "https://www.depop.com/products/seller-columbia-xl/"
        outcome = native._outcome("depop", "publish", {"state": "draft", "draft_url": URLS["depop"]}, {
            "ok": True, "state": "published", "draft_url": URLS["depop"], "listing_url": url,
        })
        self.assertEqual(outcome["state"], "published")
        self.assertEqual(outcome["listing_url"], url)

    def test_a_boosted_depop_list_turns_boost_on_with_one_edit_of_the_new_listing(self):
        url = "https://www.depop.com/products/seller-boosted-tee/"

        def answer(_job, kind, payload, **_kwargs):
            if kind != "marketplace.execute":
                return {"ok": True}
            if payload["action"] == "save_draft":
                return {"ok": True, "state": "draft", "draft_url": URLS["depop"]}
            return {"ok": True, "state": "published", "draft_url": URLS["depop"], "listing_url": url}

        self.bridge.side_effect = answer
        listing = {**LISTING, "depop_specifics": {**LISTING["depop_specifics"], "boost": True}}
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, listing, "seller")
        self.list("depop")
        # A plain List stops at publish (test_list_saves_then_publishes_in_one_job_that_holds_the_slot).
        self.assertEqual(self.actions(), ["save_draft", "publish", "update"])
        update = [call.args[2] for call in self.bridge.call_args_list
                  if call.args[1] == "marketplace.execute" and call.args[2]["action"] == "update"][0]
        self.assertIs(update["confirm"], True)
        self.assertEqual(update["listing_id"], "seller-boosted-tee")
        self.assertIs(update["listing"]["depop_specifics"]["boost"], True)

    def test_a_deleted_depop_draft_is_forgotten_and_a_replacement_is_kept(self):
        old = URLS["depop"]
        new = "https://www.depop.com/sellinghub/drafts/edit/newdraft1/"
        record = {"state": "draft", "draft_url": old, "revision_id": "current"}
        gone = native._outcome("depop", "publish", record, {
            "ok": False, "safe_to_retry": True, "error": "Depop refused the request (HTTP 404).",
            "marketplace_message": "Could not find draft with id: [hidden]", "error_code": "rejected",
            "draft_url": old,
        })
        self.assertIsNone(gone["draft_url"])
        self.assertEqual(gone["state"], "not_saved")
        kept = native._outcome("depop", "save_draft", record, {
            "ok": True, "state": "draft", "draft_url": new, "draft_replaced": True,
        })
        self.assertEqual(kept["draft_url"], new)
        with self.assertRaises(native.NativeMarketplaceError):
            native._outcome("depop", "save_draft", record, {"ok": True, "state": "draft", "draft_url": new})
        refused = native._outcome("depop", "save_draft", record, {
            "ok": False, "safe_to_retry": True, "draft_replaced": True, "draft_url": new,
            "error": "Depop refused the request (HTTP 400).", "error_code": "rejected",
            "marketplace_message": "parcel_size is required",
        })
        self.assertEqual(refused["draft_url"], new)
        self.assertEqual(refused["state"], "draft")
        self.assertIn("HTTP 400", refused["error"])
        self.assertEqual(refused["marketplace_message"], "parcel_size is required")
        unrelated = native._outcome("depop", "save_draft", record, {
            "ok": False, "safe_to_retry": True, "draft_url": new,
            "error": "Depop refused the request (HTTP 400).", "error_code": "rejected",
        })
        self.assertNotIn("draft_url", unrelated)
        self.assertEqual(unrelated["state"], "draft")
        self.assertIn("HTTP 400", unrelated["error"])
        self.assertNotEqual(unrelated["state"], "unknown")

    def test_listing_again_replaces_a_deleted_depop_draft_in_the_same_list(self):
        self.bridge.return_value = {"ok": True, "state": "draft", "draft_url": URLS["depop"]}
        saved = self.client.post(f"{self.base}/depop/draft", json={"revision_id": self.rev.id})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.run_jobs()
        self.bridge.reset_mock()
        new = "https://www.depop.com/sellinghub/drafts/edit/newdraft1/"
        self.bridge.side_effect = [
            {"ok": False, "safe_to_retry": True, "error": "Depop refused the request (HTTP 404).",
             "marketplace_message": "Could not find draft with id: [hidden]", "error_code": "rejected"},
            {"ok": True, "state": "draft", "draft_url": new},
            {"ok": True, "state": "published", "draft_url": new},
        ]
        record = self.list("depop")
        self.assertEqual(record["state"], "published")
        self.assertEqual(record["draft_url"], new)
        actions = [call.args[2]["action"] for call in self.bridge.call_args_list]
        self.assertEqual(actions, ["publish", "save_draft", "publish"])
        self.assertEqual(self.bridge.call_args_list[0].args[2]["draft_url"], URLS["depop"])
        self.assertIsNone(self.bridge.call_args_list[1].args[2]["draft_url"])

    def test_listing_links_are_validated_for_every_marketplace(self):
        self.bridge.side_effect = [{"ok": True, "state": "draft", "draft_url": URLS["mercari"]},
                                   {"ok": True, "state": "published", "draft_url": URLS["mercari"], "listing_url": "https://www.mercari.com/us/search/"}]
        record = self.list()
        self.assertEqual(record["state"], "unknown")
        self.assertIn("invalid listing link", record["error"])
        self.bridge.side_effect = None
        self.bridge.return_value = {"ok": True, "state": "published", "listing_url": "https://poshmark.com/closet/someone"}
        self.assertEqual(self.list("poshmark")["state"], "unknown")
        self.assertEqual(native.listing_url("mercari", "https://www.mercari.com/us/item/m123456789/?ref=x"),
                         "https://www.mercari.com/us/item/m123456789/")

    # --- lost replies, check, reset ------------------------------------------------

    def test_a_late_chrome_reply_keeps_the_slot_until_chrome_reports_then_a_queued_send_can_start(self):
        replies = iter([{"finished": False}, {"finished": True, "result": self.published("mercari")}])
        running_during_wait = []

        async def bridge(job, kind, payload, timeout=None):
            if kind == "marketplace.execute":
                if payload["action"] == "save_draft":
                    # The seller approves a Vendoo Send while the List runs: it waits in the queue.
                    queued.append(JobRepo(self.sessions()).create(self.conv.id, self.rev.id, LISTING, status="queued",
                                                                  current_step="vendoo_api_queued").id)
                    return {"ok": True, "state": "draft", "draft_url": URLS["mercari"]}
                raise BrowserBridgeError("Chrome did not answer in time.")
            running_during_wait.append([j.current_step for j in JobRepo(self.sessions()).get_running()])
            return next(replies)

        queued = []
        self.bridge.side_effect = bridge
        record = self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True}).json()
        self.run_jobs()
        # Chrome was told to stop the late step, by the id it journals it under.
        cancel = self.manager.send_message.call_args_list[0].args[0]
        self.assertEqual((cancel["type"], cancel["job_id"]), ("job.cancel", f"{record['job_id']}-2"))
        self.assertEqual(running_during_wait, [["native_mercari_publish"], ["native_mercari_publish"]])
        self.assertEqual(self.record("mercari")["state"], "published")
        # Only now is the slot free for the queued Send.
        self.assertFalse(JobRepo(self.db).get_running())
        self.assertEqual([job.id for job in JobRepo(self.db).get_dispatchable()], queued)

    def test_no_journal_is_surfaced_and_the_seller_can_reset(self):
        async def bridge(job, kind, payload, timeout=None):
            if kind == "marketplace.execute":
                raise BrowserBridgeError("lost")
            return {"finished": False}

        self.bridge.side_effect = bridge
        with patch.object(native, "SETTLE_DEADLINE_S", 0):
            record = self.list()
        self.assertEqual((record["state"], record["error_code"]), ("unknown", "uncertain"))
        self.assertIn("Chrome has not said whether this Mercari action finished", record["error"])
        self.assertEqual(self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True}).status_code, 409)
        checked = self.client.post(f"{self.base}/mercari/check")
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertEqual(checked.json()["state"], "unknown")
        self.assertIn("I checked it myself", checked.json()["error"])
        self.assertEqual(self.client.post(f"{self.base}/mercari/reset", json={}).status_code, 400)
        writes = self.actions()
        reset = self.client.post(f"{self.base}/mercari/reset", json={"confirm": True})
        self.assertEqual(reset.json()["state"], "not_saved", reset.text)
        self.assertIsNone(reset.json().get("error"))
        self.assertEqual(self.actions(), writes)
        events = [event for event in JobRepo(self.db).get_events(record["job_id"]) if event.event_type == "native_reset"]
        self.assertEqual(events[0].payload, {"marketplace": "mercari", "from": "unknown", "to": "not_saved"})
        self.assertEqual(self.client.post(f"{self.base}/mercari/reset", json={"confirm": True}).status_code, 409)
        self.bridge.side_effect = [{"ok": True, "state": "draft", "draft_url": URLS["mercari"]}, self.published("mercari")]
        self.assertEqual(self.list()["state"], "published")

    def test_check_reads_the_journal_and_verifies_the_job(self):
        self.bridge.side_effect = BrowserBridgeError("lost")
        with patch.object(native, "SETTLE_DEADLINE_S", 0):
            record = self.list("poshmark")
        self.assertEqual(record["state"], "unknown")
        self.bridge.side_effect = None
        self.bridge.return_value = {"finished": True, "result": {"ok": True, "state": "published", "listing_url": POSH_URL}}
        checked = self.client.post(f"{self.base}/poshmark/check").json()
        self.assertEqual(checked["state"], "published")
        self.assertEqual(self.bridge.call_args.args[1], "marketplace.result")
        self.assertEqual(self.bridge.call_args.args[2]["context"]["action"], "list")
        self.assertEqual(JobRepo(self.db).get(record["job_id"]).status, "completed")
        jobs = self.client.get(f"/api/jobs?conversation_id={self.conv.id}").json()
        self.assertTrue(all(job["mode"] == "native_marketplace" for job in jobs))

    def test_vinted_list_saves_a_draft_then_publishes_it(self):
        listing = {**LISTING, "vinted_specifics": {
            "category": "Women > Clothing > Jeans > Straight jeans", "condition": "Good",
        }}
        revision = ListingRepo(self.db).save_revision(self.conv.id, listing, "model")
        draft = "https://www.vinted.com/items/42/edit"
        live = "https://www.vinted.com/items/42"
        self.assertEqual(native.draft_url("vinted", draft + "/"), draft)
        self.assertEqual(native.draft_url("vinted", draft), draft)
        with self.assertRaises(native.NativeMarketplaceError):
            native.draft_url("vinted", draft + "?draft_id=1")
        with self.assertRaises(native.NativeMarketplaceError):
            native.draft_url("vinted", live)
        self.assertEqual(native._plan("vinted", "list", {}, revision.id), ["save_draft", "publish"])
        self.assertEqual(native._plan("vinted", "list", {"state": "draft", "revision_id": revision.id, "draft_url": draft}, revision.id), ["publish"])
        self.assertEqual(native._plan("sellwild", "list", {}, revision.id), ["publish"])
        replaced = native._outcome("vinted", "save_draft", {"state": "draft", "draft_url": draft, "revision_id": revision.id}, {
            "ok": True, "state": "draft", "draft_url": "https://www.vinted.com/items/43/edit", "draft_replaced": True,
        })
        self.assertEqual(replaced["draft_url"], "https://www.vinted.com/items/43/edit")
        gone = native._outcome("vinted", "publish", {"state": "draft", "draft_url": draft}, {
            "ok": False, "safe_to_retry": True, "error": "Could not find draft on Vinted. List again.",
            "marketplace_message": "Could not find draft", "error_code": "rejected",
        })
        self.assertIsNone(gone["draft_url"])
        self.assertEqual(gone["state"], "not_saved")

        async def bridge(job, kind, payload, timeout=None):
            return ({"ok": True, "state": "draft", "draft_url": draft} if payload["action"] == "save_draft"
                    else {"ok": True, "state": "published", "draft_url": draft, "listing_url": live})

        self.bridge.side_effect = bridge
        response = self.client.post(f"{self.base}/vinted/list", json={"revision_id": revision.id, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.run_jobs()
        record = self.status()["vinted"]
        self.assertEqual(record["state"], "published", record)
        self.assertEqual(record["draft_url"], draft)
        self.assertEqual(record["listing_url"], live)
        self.assertEqual(self.actions(), ["save_draft", "publish"])
        calls = self.bridge.call_args_list
        self.assertFalse(calls[0].args[2]["confirm"])
        self.assertTrue(calls[1].args[2]["confirm"])
        self.assertEqual(calls[1].args[2]["draft_url"], draft)
        self.assertEqual(JobRepo(self.db).get(record["job_id"]).status, "completed")

    def test_a_deleted_vinted_draft_is_saved_again_in_the_same_list(self):
        from vendoo_studio.services import approved_photos

        listing = {**LISTING, "vinted_specifics": {"category": "Women > Clothing", "condition": "Good"}}
        revision = ListingRepo(self.db).save_revision(self.conv.id, listing, "model")
        old = "https://www.vinted.com/items/42/edit"
        new = "https://www.vinted.com/items/43/edit"
        snapshot = {**listing, approved_photos.KEY: approved_photos.capture(ConversationRepo(self.db).get_photos(self.conv.id))}
        saved = JobRepo(self.db).create(self.conv.id, revision.id, snapshot, status="completed")
        MarketplaceListingRepo(self.db).save(self.conv.id, "vinted", {
            "state": "draft", "draft_url": old, "revision_id": revision.id, "job_id": saved.id,
        })
        self.bridge.side_effect = [
            {"ok": False, "safe_to_retry": True, "error": "Could not find draft on Vinted. List again.",
             "marketplace_message": "Could not find draft", "error_code": "rejected"},
            {"ok": True, "state": "draft", "draft_url": new},
            {"ok": True, "state": "published", "draft_url": new, "listing_url": "https://www.vinted.com/items/43"},
        ]
        response = self.client.post(f"{self.base}/vinted/list", json={"revision_id": revision.id, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.run_jobs()
        record = self.status()["vinted"]
        self.assertEqual(record["state"], "published", record)
        self.assertEqual(record["draft_url"], new)
        self.assertEqual(self.actions(), ["publish", "save_draft", "publish"])
        self.assertIsNone(self.bridge.call_args_list[1].args[2]["draft_url"])

    def test_a_pasted_vinted_draft_link_is_checked_without_writing(self):
        listing = {**LISTING, "vinted_specifics": {"category": "Women > Clothing", "condition": "Good"}}
        revision = ListingRepo(self.db).save_revision(self.conv.id, listing, "model")
        draft = "https://www.vinted.com/items/42/edit"
        self.bridge.side_effect = BrowserBridgeError("lost")
        with patch.object(native, "SETTLE_DEADLINE_S", 0):
            response = self.client.post(f"{self.base}/vinted/list", json={"revision_id": revision.id, "confirm": True})
            self.assertEqual(response.status_code, 200, response.text)
            self.run_jobs()
        self.assertEqual(self.status()["vinted"]["state"], "unknown")
        self.bridge.side_effect = None
        self.bridge.return_value = {"finished": True, "result": {"ok": True, "state": "draft", "draft_url": draft}}
        result = self.client.post(f"{self.base}/vinted/check", json={"draft_url": draft}).json()
        self.assertEqual(result["state"], "draft", result)
        self.assertEqual(result["draft_url"], draft)
        self.assertEqual(self.bridge.call_args.args[1], "marketplace.result")
        self.assertEqual(self.bridge.call_args.args[2]["context"]["draft_url"], draft)

    def test_a_pasted_draft_link_is_checked_without_repeating_the_write(self):
        self.bridge.side_effect = BrowserBridgeError("lost")
        with patch.object(native, "SETTLE_DEADLINE_S", 0):
            self.list()
        self.bridge.side_effect = None
        self.bridge.return_value = {"finished": True, "result": {"ok": True, "state": "draft", "draft_url": URLS["mercari"]}}
        result = self.client.post(f"{self.base}/mercari/check", json={"draft_url": URLS["mercari"]}).json()
        self.assertEqual(result["state"], "draft", result)
        self.assertEqual(self.bridge.call_args.args[2]["context"]["draft_url"], URLS["mercari"])

    def test_cancel_stops_a_running_list_before_it_publishes(self):
        started = []

        async def bridge(job, kind, payload, timeout=None):
            started.append(payload["action"])
            # The seller presses Cancel while the draft saves.
            self.assertEqual(self.client.post(f"{self.base}/mercari/cancel").status_code, 200)
            return {"ok": True, "state": "draft", "draft_url": URLS["mercari"]}

        self.bridge.side_effect = bridge
        response = self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True}).json()
        self.run_jobs()
        self.assertEqual(started, ["save_draft"])
        self.assertEqual(self.record("mercari")["state"], "draft")
        self.assertEqual(JobRepo(self.db).get(response["job_id"]).status, "cancelled")
        sent = self.manager.send_message.call_args.args[0]
        self.assertEqual((sent["type"], sent["job_id"]), ("job.cancel", response["job_id"]))
        self.assertEqual(self.client.post(f"{self.base}/mercari/cancel").status_code, 409)

    def test_an_ebay_list_whose_reply_was_lost_is_checked_before_the_job_lets_go(self):
        from vendoo_studio.services import ebay_listings

        async def execute(action, snapshot, photos, binding, record, active, **kwargs):
            record({"ebay_sku": "ar-x", "ebay_offer_id": "9", "ebay_inventory_written": True})
            return {"ok": False, "safe_to_retry": False, "error": "eBay did not confirm the listing.", "error_code": "uncertain"}

        checked = AsyncMock(return_value={"ok": True, "state": "published", "listing_url": "https://www.ebay.com/itm/123456789012"})
        with patch("vendoo_studio.services.ebay_client.EbayClient.connect", AsyncMock()), \
             patch.object(ebay_listings, "execute", execute), patch.object(ebay_listings, "check", checked):
            record = self.list("ebay")
        self.assertEqual((record["state"], record["listing_url"]), ("published", "https://www.ebay.com/itm/123456789012"))
        self.assertEqual(checked.await_args.args[0]["ebay_offer_id"], "9")
        self.assertEqual(JobRepo(self.db).get(record["job_id"]).status, "completed")

    def test_a_refused_ebay_publish_leaves_a_resumable_draft_with_its_ids(self):
        from vendoo_studio.services import ebay_listings

        async def execute(action, snapshot, photos, binding, record, active, **kwargs):
            record({"ebay_sku": "ar-x", "ebay_offer_id": "9", "ebay_inventory_written": True})
            return {"ok": False, "safe_to_retry": True, "error": "eBay returned HTTP 400.", "error_code": "rejected",
                    "marketplace_message": "25002: Color is missing."}

        with patch("vendoo_studio.services.ebay_client.EbayClient.connect", AsyncMock()), patch.object(ebay_listings, "execute", execute):
            record = self.list("ebay")
            self.assertEqual((record["state"], record["ebay_offer_id"], record["error_code"]), ("draft", "9", "rejected"))
            self.assertEqual(record["marketplace_message"], "25002: Color is missing.")
            # List again is allowed and starts from the same offer.
            self.assertEqual(self.client.post(f"{self.base}/ebay/list", json={"revision_id": self.rev.id, "confirm": True}).status_code, 200)

    def test_an_ebay_draft_is_an_unpublished_offer_checked_without_a_link(self):
        from vendoo_studio.services import ebay_listings

        async def execute(action, snapshot, photos, binding, record, active, **kwargs):
            self.assertEqual((action, kwargs["confirm"]), ("save_draft", False))
            record({"ebay_sku": "ar-x", "ebay_offer_id": "9", "ebay_inventory_written": True})
            return {"ok": True, "state": "draft"}

        checked = AsyncMock(return_value={"ok": True, "state": "draft"})
        with patch("vendoo_studio.services.ebay_client.EbayClient.connect", AsyncMock()), \
             patch.object(ebay_listings, "execute", execute), patch.object(ebay_listings, "check", checked):
            response = self.client.post(f"{self.base}/ebay/draft", json={"revision_id": self.rev.id})
            self.assertEqual(response.status_code, 200, response.text)
            self.run_jobs()
            record = self.status()["ebay"]
            self.assertEqual((record["state"], record.get("draft_url"), record.get("error")), ("draft", None, None))
            self.assertEqual(JobRepo(self.db).get(record["job_id"]).status, "completed")
            self.assertEqual(self.client.post(f"{self.base}/ebay/check", json={}).status_code, 200)
            self.run_jobs()
        # Check compares the revision the draft was saved from.
        self.assertIn(self.rev.listing_json["title"], checked.await_args.args[1]["title"])

    # --- records outlive the editor ---------------------------------------------------

    def test_clear_and_regenerate_keep_records_and_stale_notes_cannot_overwrite_them(self):
        self.bridge.return_value = {"ok": True, "state": "published", "listing_url": POSH_URL}
        record = self.list("poshmark")
        stale = merge_notes(self.conv.notes, {"nativeMarketplaceDrafts": {"poshmark": {"state": "not_saved"}}, "brand": "Levi"})
        self.assertEqual(self.client.patch(f"/api/conversations/{self.conv.id}", json={"notes": stale}).status_code, 200)
        self.assertEqual(self.record("poshmark")["state"], "published")
        for body in ({"keep_inputs": True}, {}):
            response = self.client.post(f"/api/conversations/{self.conv.id}/reset", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.db.expire_all()
            self.assertEqual(self.record("poshmark")["listing_url"], POSH_URL)
            # The job the record names stays, so Check can still read its snapshot.
            self.assertIsNotNone(JobRepo(self.db).get(record["job_id"]))
        self.assertEqual(self.client.get(f"/api/conversations/{self.conv.id}/marketplace-listings").json()["poshmark"]["listing_id"],
                         "6adc371572e62463d992ffef")
        claim_api_job(record["job_id"])
        MarketplaceListingRepo(self.db).save(self.conv.id, "poshmark", {"state": "updating"})
        try:
            self.assertEqual(self.client.post(f"/api/conversations/{self.conv.id}/reset", json={}).status_code, 409)
        finally:
            release_api_job(record["job_id"])

    def test_deleting_the_item_deletes_its_records(self):
        from vendoo_studio.services.listing_delete import delete_listing

        MarketplaceListingRepo(self.db).save(self.conv.id, "ebay", {"state": "published"})
        delete_listing(self.db, self.conv.id)
        self.assertEqual(MarketplaceListingRepo(self.db).for_conversation(self.conv.id), {})

    def test_a_failed_direct_listing_does_not_relabel_the_item(self):
        self.bridge.return_value = {"ok": False, "safe_to_retry": True, "error": "Poshmark needs a size.", "error_code": "rejected"}
        self.list("poshmark")
        ConversationRepo(self.db).reconcile_job_statuses()
        self.db.refresh(self.conv)
        self.assertNotEqual(self.conv.status, "failed")

    # --- the slot, restarts and reconnects ------------------------------------------------

    def test_inspection_is_read_only_and_holds_the_slot(self):
        seen = []

        async def bridge(job, kind, payload, timeout=None):
            seen.append(([j.current_step for j in JobRepo(self.sessions()).get_running()], kind))
            return {"ok": True, "fields": [], "scripts": []}

        self.bridge.side_effect = bridge
        self.assertEqual(self.client.post(f"{self.base}/mercari/inspect", json={}).status_code, 200)
        self.assertEqual(seen, [(["native_mercari_inspect"], "marketplace.inspect")])
        self.assertFalse(JobRepo(self.db).get_running())
        self.assertEqual(self.client.post(f"{self.base}/unknown/inspect", json={}).status_code, 422)

    def test_standalone_bridge_without_app_stamp_is_rejected_until_managed_copy_is_restored(self):
        # A web-only extension ZIP can pair, but it is not the app's installed
        # worker. Never disguise it as that worker or send a marketplace action.
        self.manager.build = None
        result = self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(result.status_code, 409)
        self.assertIn("current Anteroom Bridge", result.json()["detail"])
        self.assertFalse(JobRepo(self.db).list_all())
        self.bridge.assert_not_called()
        # Connect Chrome installs/stamps the bundled worker. Once it reconnects
        # with the expected build, the same approved request can start.
        self.manager.build = "test-build"
        restored = self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertTrue(restored.json()["running"])

    def test_old_bridge_is_rejected_before_making_a_job(self):
        with patch("vendoo_studio.services.native_marketplaces.expected_extension_build", return_value="new-build"):
            result = self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(result.status_code, 409)
        self.assertFalse(JobRepo(self.db).list_all())

    def test_other_jobs_block_native_actions(self):
        JobRepo(self.db).create(self.conv.id, self.rev.id, LISTING)
        self.assertEqual(self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True}).status_code, 409)
        self.bridge.assert_not_called()

    def test_listing_runs_beside_other_marketplaces_but_not_its_own(self):
        repo = JobRepo(self.db)
        other = ConversationRepo(self.db).create(title="Other item")
        repo.create(other.id, self.rev.id, LISTING, status="dispatched", current_step="native_poshmark_list")
        started = self.client.post(f"{self.base}/mercari/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(started.status_code, 200, started.text)
        refused = self.client.post(f"{self.base}/poshmark/list", json={"revision_id": self.rev.id, "confirm": True})
        self.assertEqual(refused.status_code, 409)
        self.assertIn("Another Poshmark action", refused.json()["detail"])

    def test_delist_and_inspection_still_hold_every_marketplace(self):
        for step in ("native_delist", "native_poshmark_inspect"):
            job = JobRepo(self.db).create(self.conv.id, self.rev.id, LISTING, status="dispatched", current_step=step)
            self.assertEqual(native.blocking_job(JobRepo(self.db), "mercari").id, job.id)
            JobRepo(self.db).update_status(job.id, "completed")

    def test_restart_marks_cut_off_actions_unconfirmed_and_reconcile_reads_them(self):
        repo = JobRepo(self.db)
        job = repo.create(self.conv.id, self.rev.id, LISTING, status="dispatched", current_step="native_poshmark_list")
        MarketplaceListingRepo(self.db).save(self.conv.id, "poshmark", {"state": "publishing", "action": "list", "job_id": job.id,
                                                                       "operation_id": job.id})
        repo.requeue_interrupted()
        self.assertEqual(job.status, "failed")
        self.assertFalse(repo.requeue_interrupted_send(job.id))
        self.assertEqual(self.record("poshmark")["state"], "unknown")
        self.bridge.return_value = {"finished": True, "result": {"ok": True, "state": "published", "listing_url": POSH_URL}}
        # Startup reconciles eBay and Etsy only; Chrome's records wait for Chrome.
        self.assertEqual(asyncio.run(native.reconcile(chrome=False)), 0)
        self.assertEqual(asyncio.run(native.reconcile(chrome=True)), 1)
        self.db.expire_all()
        self.assertEqual(self.record("poshmark")["state"], "published")
        self.assertEqual(self.bridge.call_args.args[1], "marketplace.result")
        self.assertFalse(any(call.args[1] == "marketplace.execute" for call in self.bridge.call_args_list))

    def test_the_watchdog_fails_dead_native_jobs_and_leaves_live_ones_alone(self):
        repo = JobRepo(self.db)
        dead = repo.create(self.conv.id, self.rev.id, LISTING, status="dispatched", current_step="native_mercari_save_draft")
        dead.updated_at = utcnow() - timedelta(seconds=10)
        live = repo.create(self.conv.id, self.rev.id, LISTING, status="dispatched", current_step="native_depop_publish")
        live.updated_at = utcnow() - timedelta(minutes=30)
        self.db.commit()
        MarketplaceListingRepo(self.db).save(self.conv.id, "mercari", {"state": "saving", "job_id": dead.id})
        claim_api_job(live.id)
        try:
            self.assertEqual(fail_stalled_jobs(self.db), [dead.id])
            self.assertEqual(live.status, "dispatched")
        finally:
            release_api_job(live.id)
        self.assertEqual(self.record("mercari")["state"], "unknown")
        self.assertFalse(repo.get_dispatchable())

    def test_reconnect_keeps_a_native_action_running_in_this_process(self):
        repo = JobRepo(self.db)
        job = repo.create(self.conv.id, self.rev.id, LISTING, status="dispatched", current_step="native_mercari_publish")
        claim_api_job(job.id)
        try:
            repo.requeue_interrupted()
            self.assertEqual(job.status, "dispatched")
        finally:
            release_api_job(job.id)


class MigrationFromNotesTest(unittest.TestCase):
    def test_records_move_out_of_notes(self):
        import importlib.util
        from pathlib import Path

        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        import vendoo_studio

        path = next((Path(vendoo_studio.__file__).parent / "migrations" / "versions").glob("292cc5d3b9a5_*.py"))
        spec = importlib.util.spec_from_file_location("migration_292cc5d3b9a5", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite://", poolclass=StaticPool)
        Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in ("conversations",)])
        db = sessionmaker(bind=engine)()
        conv = ConversationRepo(db).create(title="Old item")
        other = ConversationRepo(db).create(title="Untouched")
        conv.notes = merge_notes(None, {"brand": "Levi", "nativeMarketplaceDrafts": {
            "ebay": {"state": "published", "job_id": "j1", "ebay_sku": "arabc", "ebay_offer_id": "1", "ebay_inventory_written": True,
                     "ebay_image_urls": ["https://i.ebayimg.com/a.jpg"], "listing_url": "https://www.ebay.com/itm/123456789012"},
            "etsy": {"state": "draft", "transport": "etsy_api", "etsy_image_ids": {"p1": "100"}, "etsy_photo_ids": ["p1"],
                     "etsy_photos_complete": True, "draft_url": "https://www.etsy.com/your/shops/me/listing-editor/edit/1"},
            "sellwild": {"state": "draft", "storage": "local", "sellwild_category_id": 272, "local_draft_id": "abc"},
            "mercari": {"state": "unknown", "job_id": "j2", "error": "lost"}, "vinted": {"state": "draft"}}})
        other.notes = merge_notes(None, {"brand": "Lee"})
        db.commit()
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
        db.expire_all()
        # Inspect the historical migration's table, not today's ORM model:
        # newer releases can add columns in later revisions.
        from sqlalchemy import MetaData, Table, select

        table = Table("marketplace_listings", MetaData(), autoload_with=engine, resolve_fks=False)
        records = {row["marketplace"]: dict(row) for row in db.execute(
            select(table).where(table.c.conversation_id == conv.id)).mappings()}
        self.assertEqual(set(records), {"ebay", "etsy", "sellwild", "mercari"})
        self.assertEqual(records["ebay"]["ebay_images"], [{"photo_id": None, "checksum": None, "url": "https://i.ebayimg.com/a.jpg"}])
        self.assertTrue(records["ebay"]["ebay_inventory_written"])
        self.assertEqual(records["ebay"]["operation_id"], "j1")
        self.assertEqual(records["etsy"]["etsy_image_ids"], {"p1": "100"})
        self.assertNotIn("transport", records["etsy"])
        self.assertEqual(records["sellwild"]["sellwild_category_id"], 272)
        self.assertEqual((records["mercari"]["state"], records["mercari"]["error_code"]), ("unknown", "uncertain"))
        self.assertEqual(parse_notes(ConversationRepo(db).get(conv.id).notes), {"brand": "Levi"})
        self.assertEqual(parse_notes(ConversationRepo(db).get(other.id).notes), {"brand": "Lee"})
        db.close()
