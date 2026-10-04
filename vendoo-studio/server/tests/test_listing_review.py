from copy import deepcopy
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import send_review
from vendoo_studio.services.vendoo_api import build_vendoo_item
from vendoo_studio.services.vendoo_import import merge_notes
from vendoo_studio.services.vendoo_send import record_photo_progress


LISTING = {
    "title": "Levi's M Vintage Shirt Blue Regular", "brand": "Levi's", "size": "M",
    "price": 30, "description": "Blue cotton shirt.", "condition": "Pre-Owned - Good",
    "category_path": "Women > Clothing > Tops > Shirts", "weight_oz": 8,
    "package_dimensions_in": "13x10x3", "labels": [],
}


class ListingReviewTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.conv = ConversationRepo(self.db).create(title="Review fixture")
        self.old = ListingRepo(self.db).save_revision(self.conv.id, {**LISTING, "price": 40}, source="model")
        self.current = ListingRepo(self.db).save_revision(self.conv.id, LISTING, source="model", parent_revision_id=self.old.id)
        ConversationRepo(self.db).add_photo(self.conv.id, "fixture.jpg", "fixture.jpg", "image/jpeg", 10)
        self.remote, _ = build_vendoo_item({**LISTING, "price": 40}, images=[{"id": "remote-photo", "version": 3}])
        self.remote["_studio_update_time"] = "version-1"
        self.ops = []

        async def run_ops(_job, ops, **_kwargs):
            self.ops.extend(ops)
            self.assertTrue(all(op["op"] == "get_item" for op in ops), "Preview must only read Vendoo")
            return {"ok": True, "results": [{"op": "get_item", "ok": True, "item": deepcopy(self.remote)}]}

        async def prepare(_job, listing, **_kwargs):
            return deepcopy(listing), {}, None, [], []

        self.patches = [
            patch("vendoo_studio.services.vendoo_create.run_ops", run_ops),
            patch("vendoo_studio.services.vendoo_create.prepare_listing_fields_for_vendoo", prepare),
            patch("vendoo_studio.routes.extension.schedule_advance_job_queue"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        app.dependency_overrides.clear()
        send_review._reviews.clear()
        self.db.close()
        self.engine.dispose()

    def preview(self, bound=False):
        if bound:
            self.conv.notes = merge_notes(self.conv.notes, {"vendooItemId": "draft-1"})
            self.db.commit()
        response = self.client.post("/api/jobs/send-preview", json={"conversation_id": self.conv.id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def approve(self, preview):
        return self.client.post("/api/jobs/send", json={"conversation_id": self.conv.id, "review_id": preview["review_id"]})

    def test_preview_reads_actual_update_and_preserves_photos(self):
        preview = self.preview(bound=True)
        price = next(row for row in preview["changes"] if row["field"] == "generalDetails.price")
        self.assertEqual((price["before"], price["after"]), ("40", "30"))
        self.assertEqual((preview["photo_action"], preview["photo_count"]), ("keep", 1))
        self.assertTrue(all("dateLastModified" not in row["field"] for row in preview["changes"]))
        self.assertEqual(len(JobRepo(self.db).list_by_conversation(self.conv.id)), 0)
        self.assertEqual(len(ListingRepo(self.db).get_revisions(self.conv.id)), 2)

    def test_preview_reads_draft_while_preparing_fields(self):
        import asyncio

        started = asyncio.Event()

        async def prepare(_job, listing, **_kwargs):
            started.set()
            return deepcopy(listing), {}, None, [], []

        async def blocking_run_ops(_job, ops, **_kwargs):
            # Answers only once field preparation is under way.
            await asyncio.wait_for(started.wait(), 1)
            return {"ok": True, "results": [{"op": "get_item", "ok": True, "item": deepcopy(self.remote)}]}

        with patch("vendoo_studio.services.vendoo_create.run_ops", blocking_run_ops), \
                patch("vendoo_studio.services.vendoo_create.prepare_listing_fields_for_vendoo", prepare):
            preview = self.preview(bound=True)
        self.assertEqual(preview["mode"], "update")

    def test_create_preview_uploads_only_after_approval_and_persists_review(self):
        preview = self.preview()
        self.assertEqual((preview["photo_action"], preview["photo_count"]), ("upload", 1))
        self.assertEqual(self.ops, [])
        response = self.approve(preview)
        self.assertEqual(response.status_code, 202, response.text)
        job = JobRepo(self.db).get(response.json()["id"])
        review = JobRepo(self.db).latest_event(job.id, "vendoo_review")
        self.assertEqual(review.payload["snapshot"]["price"], 30)
        self.assertEqual(job.approved_revision_id, self.current.id)
        # A later form edit must not silently change the queued approval.
        result = self.client.put(f"/api/conversations/{self.conv.id}/listing", json={"listing": {**LISTING, "price": 20}})
        self.assertEqual(result.status_code, 200, result.text)
        self.db.refresh(job)
        self.assertEqual(job.listing_snapshot["price"], 30)

    def test_stale_revision_notes_photo_order_and_missing_preview_rejected(self):
        for change in ("revision", "notes", "photos"):
            preview = self.preview()
            if change == "revision":
                ListingRepo(self.db).save_revision(self.conv.id, {**LISTING, "price": 20}, source="user_form")
            elif change == "notes":
                self.conv.notes = merge_notes(self.conv.notes, {"sku": "NEW-SKU"})
                self.db.commit()
            else:
                ConversationRepo(self.db).add_photo(self.conv.id, "b.jpg", "b.jpg", "image/jpeg", 10)
            response = self.approve(preview)
            self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.approve({"review_id": "unknown"}).status_code, 409)
        self.assertEqual(self.client.post("/api/jobs/send", json={"conversation_id": self.conv.id}).status_code, 422)
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])

    def test_expired_preview_rejected(self):
        preview = self.preview()
        created, review = send_review._reviews[preview["review_id"]]
        send_review._reviews[preview["review_id"]] = (created - send_review.REVIEW_TTL_SECONDS, review)
        self.assertEqual(self.approve(preview).status_code, 409)

    def test_history_detail_ownership_restore_and_undo(self):
        base = f"/api/conversations/{self.conv.id}/revisions"
        self.assertEqual(self.client.get(f"{base}/{self.old.id}").json()["listing"]["price"], 40)
        other = ConversationRepo(self.db).create(title="Other")
        self.assertEqual(self.client.get(f"/api/conversations/{other.id}/revisions/{self.old.id}").status_code, 404)
        response = self.client.post(f"{base}/{self.old.id}/restore", json={"expected_revision_id": self.current.id})
        self.assertEqual(response.status_code, 200, response.text)
        restored_id = response.json()["revision_id"]
        restored = ListingRepo(self.db).get_revision(restored_id)
        self.assertEqual((restored.source, restored.listing_json["price"], restored.parent_revision_id), ("restore", 40, self.current.id))
        response = self.client.post(f"{base}/{self.current.id}/restore", json={"expected_revision_id": restored_id})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(ListingRepo(self.db).get_revisions(self.conv.id)[0].listing_json["price"], 30)
        self.assertEqual(self.ops, [])

    def test_restore_rejects_stale_and_busy_listing(self):
        url = f"/api/conversations/{self.conv.id}/revisions/{self.old.id}/restore"
        self.assertEqual(self.client.post(url, json={"expected_revision_id": self.old.id}).status_code, 409)
        self.approve(self.preview())
        self.assertEqual(self.client.post(url, json={"expected_revision_id": self.current.id}).status_code, 409)
        self.assertEqual(ListingRepo(self.db).get_current(self.conv.id).current_revision_id, self.current.id)

    def test_progress_is_measured_bounded_and_ignores_late_messages(self):
        job_id = self.approve(self.preview()).json()["id"]
        repo = JobRepo(self.db)
        repo.update_status(job_id, "dispatched", "vendoo_api_photos")
        repo.add_event(job_id, "vendoo_api_started")
        for count in (0, 2, 1, 3):
            record_photo_progress(self.db, job_id, {"completed": count, "total": 8})
        record_photo_progress(self.db, job_id, {"completed": 99, "total": 8})
        response = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(response["send_progress"], {"completed": 3, "total": 8})
        self.assertIsNotNone(response["started_at"])
        events = [e for e in repo.get_events(job_id) if e.event_type == "vendoo_api_progress"]
        self.assertEqual(len(events), 1)
        repo.update_status(job_id, "completed", "vendoo_api_created")
        record_photo_progress(self.db, job_id, {"completed": 8, "total": 8})
        self.assertEqual(repo.latest_event(job_id, "vendoo_api_progress").payload["completed"], 3)


class ReviewedPreparationTest(unittest.IsolatedAsyncioTestCase):
    async def test_remote_edit_stops_update_before_any_write(self):
        from types import SimpleNamespace
        from fastapi import HTTPException
        from vendoo_studio.routes.vendoo_api import _save_claimed_draft
        from unittest.mock import MagicMock

        db, repo = MagicMock(), MagicMock()
        job = SimpleNamespace(id="job", status="dispatched", conversation_id="conv")
        repo.latest_event.return_value = SimpleNamespace(payload={"expected_version": "old-version"})
        repo.get.return_value = job
        reply = {"ok": True, "results": [{"op": "get_item", "item": {"_studio_update_time": "new-version"}}]}
        with patch("vendoo_studio.services.vendoo_create.run_ops", AsyncMock(return_value=reply)) as ops:
            with self.assertRaises(HTTPException) as caught:
                await _save_claimed_draft(db, None, "conv", "draft", [], {}, None, "", job, repo)
            self.assertIn("changed after your preview", str(caught.exception.detail))
            self.assertEqual(ops.await_count, 1)

    async def test_reviewed_fields_are_not_regenerated_after_approval(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from vendoo_studio.services.vendoo_create import prepare_listing_for_vendoo

        payload = {"snapshot": {"price": 30}, "specifics": {}, "schema": None, "unresolved": [], "unfilled": []}
        repo = MagicMock()
        repo.latest_event.return_value = SimpleNamespace(payload=payload)
        with patch("vendoo_studio.services.vendoo_send.job_repo", return_value=repo), \
             patch("vendoo_studio.services.vendoo_create.prepare_listing_fields_for_vendoo", AsyncMock()) as prepare:
            listing, *_ = await prepare_listing_for_vendoo(SimpleNamespace(id="job"), {"price": 20})
        self.assertEqual(listing["price"], 30)
        prepare.assert_not_awaited()
