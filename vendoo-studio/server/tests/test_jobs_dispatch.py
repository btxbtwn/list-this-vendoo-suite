from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import ABANDONED_SEND, AUTO_RETRY_EVENT, RECONNECTED_SEND, Job
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import JobRepo
from vendoo_studio.services.api_job_lock import api_job_is_live, claim_api_job, release_api_job
from vendoo_studio.services.extension_connection import (
    ExtensionManager,
    _resume_interrupted_sends,
    dispatch_queued_jobs,
    dispatch_search_categories,
    extension_status,
    handshake_extension,
)
from datetime import UTC


class FakeSocket:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError("websocket closed")
        self.sent.append(message)

    async def close(self):
        self.closed = True


class ExtensionManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_send_clears_stale_connection(self):
        manager = ExtensionManager()
        manager.connection = FakeSocket(fail=True)
        manager.paired = True

        sent = await manager.send_message({"type": "job.start"})

        self.assertFalse(sent)
        self.assertIsNone(manager.connection)
        self.assertFalse(manager.paired)

    async def test_successful_send_keeps_connection(self):
        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True

        sent = await manager.send_message({"type": "job.start", "job_id": "abc"})

        self.assertTrue(sent)
        self.assertIs(manager.connection, socket)
        self.assertEqual(socket.sent[0]["type"], "job.start")


class JobRepoActiveTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.conv = Conversation(title="Nike tee")
        self.db.add(self.conv)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _job(self, status: str) -> Job:
        job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={"title": "Nike tee"},
            status=status,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def test_get_active_includes_dispatched_jobs(self):
        dispatched = self._job("dispatched")
        self._job("completed")
        active = JobRepo(self.db).get_active()
        self.assertEqual([job.id for job in active], [dispatched.id])

    def test_get_running_only_includes_dispatched(self):
        queued = self._job("queued")
        dispatched = self._job("dispatched")
        running = JobRepo(self.db).get_running()
        self.assertEqual([job.id for job in running], [dispatched.id])
        self.assertNotIn(queued.id, [job.id for job in running])

    def test_get_dispatchable_excludes_dispatched_jobs(self):
        queued = self._job("queued")
        self._job("dispatched")
        dispatchable = JobRepo(self.db).get_dispatchable()
        self.assertEqual([job.id for job in dispatchable], [queued.id])

    def test_requeue_interrupted_resets_dispatched_jobs(self):
        job = self._job("dispatched")
        job.current_step = "filling_general"
        self.db.commit()
        requeued = JobRepo(self.db).requeue_interrupted()
        self.assertEqual(len(requeued), 1)
        self.assertEqual(requeued[0].id, job.id)
        self.assertEqual(requeued[0].status, "queued")

    def test_requeue_interrupted_fails_api_create_without_form_fill(self):
        job = self._job("dispatched")
        job.current_step = "vendoo_api_fields"
        self.db.commit()

        recovered = JobRepo(self.db).requeue_interrupted()

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].status, "failed")
        self.assertEqual(recovered[0].current_step, "vendoo_api_fields")
        self.assertIn("Send to Vendoo again", recovered[0].last_error)

    def test_requeue_interrupted_fails_leftover_fill_without_restarting_job(self):
        job = self._job("dispatched")
        job.current_step = "filling_fields"
        self.db.commit()

        recovered = JobRepo(self.db).requeue_interrupted()

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].status, "failed")
        self.assertEqual(recovered[0].current_step, "filling_fields")
        self.assertIn("Retry the leftover fill", recovered[0].last_error)

    def _interrupted(self, error: str = RECONNECTED_SEND, step: str = "vendoo_api_photos") -> Job:
        job = self._job("failed")
        job.current_step = step
        job.last_error = error
        self.db.commit()
        return job

    def test_interrupted_send_is_queued_again_once(self):
        job = self._interrupted()
        repo = JobRepo(self.db)
        self.assertTrue(repo.requeue_interrupted_send(job.id))
        self.db.refresh(job)
        self.assertEqual((job.status, job.current_step, job.last_error), ("queued", "vendoo_api_queued", None))
        self.assertEqual(repo.latest_event(job.id, AUTO_RETRY_EVENT).step, "vendoo_api_photos")
        # Cut off again: it stays failed and the seller decides.
        repo.update_status(job.id, "failed", "vendoo_api_photos", error=ABANDONED_SEND)
        self.assertFalse(repo.requeue_interrupted_send(job.id))
        self.db.refresh(job)
        self.assertEqual(job.status, "failed")

    def test_refused_or_form_fill_jobs_are_not_queued_again(self):
        repo = JobRepo(self.db)
        refused = self._interrupted(error="Vendoo rejected the item")
        form_fill = self._interrupted(step="filling_general")
        running = self._job("dispatched")
        running.current_step = "vendoo_api_photos"
        self.db.commit()
        for job in (refused, form_fill, running):
            self.assertFalse(repo.requeue_interrupted_send(job.id))

    def test_reconnect_resumes_a_send_with_no_worker(self):
        job = self._job("dispatched")
        job.current_step = "vendoo_api_photos"
        self.db.commit()
        repo = JobRepo(self.db)
        _resume_interrupted_sends(repo, repo.requeue_interrupted())
        self.db.refresh(job)
        self.assertEqual(job.status, "queued")

    def test_reconnect_stops_a_live_worker_and_leaves_the_resume_to_its_exit(self):
        job = self._job("dispatched")
        job.current_step = "vendoo_api_photos"
        self.db.commit()
        manager = ExtensionManager()
        repo = JobRepo(self.db)
        claim_api_job(job.id)
        self.addCleanup(release_api_job, job.id)
        with patch("vendoo_studio.services.extension_connection.extension_manager", manager), \
             patch.object(manager, "cancel_waits_for_job") as cancel:
            _resume_interrupted_sends(repo, repo.requeue_interrupted())
        cancel.assert_called_once_with(job.id)
        self.db.refresh(job)
        self.assertEqual((job.status, job.last_error), ("failed", RECONNECTED_SEND))

    def test_worker_exit_resumes_a_send_whose_request_closed(self):
        from vendoo_studio.routes.vendoo_api import _finish_api_send

        job = self._job("dispatched")
        job.current_step = "vendoo_api_photos"
        self.db.commit()
        claim_api_job(job.id)
        with patch("vendoo_studio.services.extension_connection.schedule_advance_job_queue"):
            _finish_api_send(self.db, job.id)
        self.db.refresh(job)
        self.assertEqual(job.status, "queued")
        self.assertFalse(api_job_is_live(job.id))
        self.assertEqual(JobRepo(self.db).latest_event(job.id, AUTO_RETRY_EVENT).payload["reason"], ABANDONED_SEND)

    def test_add_event_persists_without_refresh(self):
        job = self._job("dispatched")
        event = JobRepo(self.db).add_event(job.id, "cancelled")
        self.assertEqual(event.event_type, "cancelled")
        self.assertEqual(JobRepo(self.db).get_events(job.id)[-1].id, event.id)

    def test_cancel_leftover_jobs_clears_dispatched_jobs(self):
        from vendoo_studio.routes.updates import _cancel_leftover_jobs

        job = self._job("dispatched")
        cancelled = _cancel_leftover_jobs(self.db)
        self.assertEqual(cancelled, [job.id])
        self.db.refresh(job)
        self.assertEqual(job.status, "cancelled")


class DispatchQueuedJobsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        db = self.Session()
        self.conv = Conversation(title="Nike tee")
        db.add(self.conv)
        db.commit()
        self.job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={
                "title": "Nike tee",
                "description": "Soft tee",
                "price": 24,
                "platforms": ["ebay", "poshmark"],
            },
            status="queued",
        )
        db.add(self.job)
        db.commit()
        db.refresh(self.job)
        self.job_id = self.job.id
        self.conv_id = self.conv.id
        db.close()

    def _job(self) -> Job:
        db = self.Session()
        try:
            return db.query(Job).filter(Job.id == self.job_id).one()
        finally:
            db.close()

    async def test_failed_send_does_not_mark_job_dispatched(self):
        manager = ExtensionManager()
        manager.connection = FakeSocket(fail=True)
        manager.paired = True
        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        job = self._job()
        self.assertEqual(job.status, "awaiting_extension")
        self.assertIsNone(manager.connection)

    async def test_successful_send_marks_job_dispatched(self):
        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True
        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        job = self._job()
        self.assertEqual(job.status, "dispatched")
        self.assertEqual(socket.sent[0]["type"], "job.start")
        self.assertEqual(socket.sent[0]["payload"]["job_id"], self.job_id)
        self.assertFalse(socket.sent[0]["payload"]["options"]["publish"])

    async def test_dispatch_uses_approved_snapshot_platforms(self):
        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True
        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ), patch(
            "vendoo_studio.services.marketplaces.selected_fillable_platforms",
            return_value=["ebay", "poshmark"],
        ) as selected:
            await dispatch_queued_jobs()

        self.assertEqual(socket.sent[0]["payload"]["options"]["platforms"], ["ebay", "poshmark"])
        self.assertFalse(socket.sent[0]["payload"]["options"]["publish"])
        selected.assert_called_once_with(["ebay", "poshmark"])

    async def test_category_search_uses_approved_snapshot_platforms(self):
        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True
        self.job.vendoo_item_id = "draft123"
        self.job.vendoo_url = "https://web.vendoo.co/app/item/draft123"

        with patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ), patch(
            "vendoo_studio.services.marketplaces.selected_fillable_platforms",
            return_value=["ebay", "poshmark"],
        ) as selected:
            sent = await dispatch_search_categories(self.job, "request1", "Women Blouses")

        self.assertTrue(sent)
        payload = socket.sent[0]["payload"]
        self.assertEqual(payload["platforms"], ["ebay", "poshmark"])
        self.assertEqual(payload["vendoo_item_id"], "draft123")
        self.assertEqual(payload["vendoo_url"], "https://web.vendoo.co/app/item/draft123")
        selected.assert_called_once_with(["ebay", "poshmark"])

    async def test_dispatch_does_not_reuse_new_route_id(self):
        db = self.Session()
        job = db.query(Job).filter(Job.id == self.job_id).one()
        job.vendoo_item_id = "new"
        job.vendoo_url = "https://web.vendoo.co/app/item/new?marketplace=general"
        db.commit()
        db.close()

        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True
        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        options = socket.sent[0]["payload"]["options"]
        self.assertFalse(options["reuseExistingItem"])
        self.assertIsNone(options["vendoo_item_id"])
        self.assertIsNone(options["vendoo_url"])

    async def test_dispatch_reuses_existing_vendoo_item(self):
        db = self.Session()
        job = db.query(Job).filter(Job.id == self.job_id).one()
        job.vendoo_item_id = "abc123"
        job.vendoo_url = "https://web.vendoo.co/app/item/abc123"
        db.commit()
        db.close()

        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True
        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        options = socket.sent[0]["payload"]["options"]
        self.assertTrue(options["reuseExistingItem"])
        self.assertFalse(options["skipPhotos"])
        self.assertFalse(options["clearBeforeFill"])
        self.assertEqual(options["vendoo_item_id"], "abc123")
        self.assertEqual(socket.sent[0]["payload"]["vendoo_item_id"], "abc123")
        self.assertFalse(options["publish"])

    async def test_dispatch_includes_resume_from_latest_retry(self):
        db = self.Session()
        job = db.query(Job).filter(Job.id == self.job_id).one()
        job.vendoo_item_id = "abc123"
        job.vendoo_url = "https://web.vendoo.co/app/item/abc123"
        db.commit()
        JobRepo(db).add_event(job.id, "retried", "filling_etsy", {"resume_from": "filling_etsy"})
        db.close()

        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True
        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        options = socket.sent[0]["payload"]["options"]
        self.assertEqual(options["resumeFrom"], "filling_etsy")
        self.assertTrue(options["reuseExistingItem"])

    async def test_dispatch_skips_when_another_job_is_running(self):
        db = self.Session()
        running = Job(
            conversation_id=self.conv_id,
            approved_revision_id="rev2",
            listing_snapshot={"title": "Other", "platforms": ["ebay"]},
            status="dispatched",
        )
        db.add(running)
        db.commit()
        db.close()

        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True
        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        self.assertEqual(socket.sent, [])
        job = self._job()
        self.assertEqual(job.status, "queued")

    async def test_dispatch_starts_next_queued_after_running_clears(self):
        from datetime import datetime, timedelta

        db = self.Session()
        base = datetime.now(UTC).replace(tzinfo=None)
        earlier = Job(
            conversation_id=self.conv_id,
            approved_revision_id="rev0",
            listing_snapshot={"title": "Earlier", "platforms": ["ebay"]},
            status="queued",
            created_at=base,
        )
        later = db.query(Job).filter(Job.id == self.job_id).one()
        later.created_at = base + timedelta(seconds=5)
        db.add(earlier)
        db.commit()
        earlier_id = earlier.id
        db.close()

        manager = ExtensionManager()
        socket = FakeSocket()
        manager.connection = socket
        manager.paired = True
        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        self.assertEqual(socket.sent[0]["payload"]["job_id"], earlier_id)
        db = self.Session()
        first = db.query(Job).filter(Job.id == earlier_id).one()
        second = db.query(Job).filter(Job.id == self.job_id).one()
        self.assertEqual(first.status, "dispatched")
        self.assertEqual(second.status, "queued")
        first.status = "completed"
        db.commit()
        db.close()

        with patch("vendoo_studio.services.extension_connection.SessionLocal", self.Session), patch(
            "vendoo_studio.services.extension_connection.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        self.assertEqual(socket.sent[1]["payload"]["job_id"], self.job_id)
        self.assertEqual(self._job().status, "dispatched")


class ExtensionHandshakeTest(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_accepts_without_reloading_tabs(self):
        socket = FakeSocket()
        with patch("vendoo_studio.services.extension_connection.install_bundled_extension", return_value=True), patch(
            "vendoo_studio.services.extension_connection.extension_reload_token_if_needed", return_value=None
        ), patch("vendoo_studio.services.extension_connection.clear_extension_reload_pending") as clear:
            accepted = await handshake_extension(socket, None)

        self.assertTrue(accepted)
        self.assertEqual(socket.sent[0]["type"], "connection.accepted")
        clear.assert_called_once()

    async def test_handshake_reloads_once_when_chrome_is_behind(self):
        socket = FakeSocket()
        with patch("vendoo_studio.services.extension_connection.install_bundled_extension", return_value=True), patch(
            "vendoo_studio.services.extension_connection.extension_reload_token_if_needed", return_value="gen-1"
        ) as reload_token, patch("vendoo_studio.services.extension_connection.clear_extension_reload_pending") as clear:
            accepted = await handshake_extension(socket, None, "0.2.15")

        self.assertFalse(accepted)
        reload_token.assert_called_once_with("0.2.15", None, None)
        self.assertEqual(socket.sent[0]["type"], "extension.reload")
        self.assertEqual(socket.sent[0]["payload"]["generation"], "gen-1")
        clear.assert_not_called()

    async def test_handshake_accepts_after_reload_generation_matches(self):
        socket = FakeSocket()
        with patch("vendoo_studio.services.extension_connection.install_bundled_extension", return_value=True), patch(
            "vendoo_studio.services.extension_connection.extension_reload_token_if_needed", return_value=None
        ), patch("vendoo_studio.services.extension_connection.clear_extension_reload_pending") as clear:
            accepted = await handshake_extension(socket, "gen-1", "0.2.15")

        self.assertTrue(accepted)
        self.assertEqual(socket.sent[0]["type"], "connection.accepted")
        clear.assert_called_once()


class ExtensionStatusRouteTest(unittest.TestCase):
    def test_status_includes_build_fields(self):
        manager = ExtensionManager()
        manager.version = "0.2.5"
        manager.reload_generation = None
        with patch("vendoo_studio.services.extension_connection.extension_manager", manager), patch(
            "vendoo_studio.services.extension_connection.extension_build_status",
            return_value={
                "expected_version": "0.2.6",
                "version": "0.2.5",
                "up_to_date": False,
                "reload_pending": False,
                "files_in_sync": True,
            },
        ) as build:
            payload = extension_status()

        build.assert_called_once_with("0.2.5", None, None)
        self.assertFalse(payload["connected"])
        self.assertFalse(payload["up_to_date"])
        self.assertEqual(payload["expected_version"], "0.2.6")
        self.assertEqual(payload["version"], "0.2.5")


class PrepareListingSnapshotRetryTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = Conversation(title="Casa tee")
        self.db.add(self.conv)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_retry_keeps_refined_mens_category_over_stale_override(self):
        import json

        from vendoo_studio.services.job_snapshot import prepare_listing_snapshot
        from vendoo_studio.services.registry import MEN_TSHIRT_PATH

        self.conv.notes = json.dumps({
            "categoryOverride": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
        })
        self.db.commit()
        snapshot = prepare_listing_snapshot(
            self.db,
            self.conv,
            {
                "title": "Casa San Bord M Graphic T-Shirt",
                "department": "Men",
                "category_path": MEN_TSHIRT_PATH,
                "ebay_specifics": {"department": "Men", "type": "T-Shirt"},
            },
            prefer_listing_category=True,
        )
        self.assertEqual(snapshot["category_path"], MEN_TSHIRT_PATH)
        self.assertNotIn("Women", snapshot["category_path"])

    def test_item_details_labels_cog_and_notes_reach_vendoo_form(self):
        import json

        from vendoo_studio.services.job_snapshot import prepare_listing_snapshot
        from vendoo_studio.services.vendoo_item_build import build_vendoo_item

        self.conv.notes = json.dumps({
            "vendooLabels": "A19, To List",
            "sku": "KEEP-ME-SKU",
            "cog": "3.50",
            "sellerNotes": "Bin 4, small hole on hem",
            "poshmarkOriginalPrice": "80",
        })
        self.db.commit()
        snapshot = prepare_listing_snapshot(
            self.db,
            self.conv,
            {"title": "Tee", "sku": "NEW-SLUG", "cost": 9, "internal_notes": "stale"},
        )
        self.assertEqual(snapshot["labels"], ["A19", "To List"])
        self.assertEqual(snapshot["sku"], "KEEP-ME-SKU")
        self.assertEqual(snapshot["cost"], 3.5)
        self.assertEqual(snapshot["internal_notes"], "Bin 4, small hole on hem")
        self.assertEqual(snapshot["poshmark_specifics"]["originalPrice"], 0)

        item, _ = build_vendoo_item(snapshot, None, images=[], user_id="u", item_id="i")
        self.assertEqual(item["listings"]["poshmark"]["marketplaceSpecifics"]["originalPrice"], "0")
        general = item["generalDetails"]
        self.assertEqual(item["labels"], ["A19", "To List"])
        self.assertEqual(general["sku"], "KEEP-ME-SKU")
        self.assertEqual(general["cost"], "3.5")
        self.assertEqual(general["notes"], "Bin 4, small hole on hem")

    def test_blank_item_details_keep_listing_cost_and_notes(self):
        from vendoo_studio.services.job_snapshot import prepare_listing_snapshot

        snapshot = prepare_listing_snapshot(
            self.db, self.conv, {"title": "Tee", "cost": 9, "internal_notes": "Bin 2"},
        )
        self.assertEqual(snapshot["cost"], 9)
        self.assertEqual(snapshot["internal_notes"], "Bin 2")


class ResumeStepForRetryTest(unittest.TestCase):
    def test_failed_marketplace_step_resumes_with_draft(self):
        from types import SimpleNamespace

        from vendoo_studio.services.job_snapshot import resume_step_for_retry

        job = SimpleNamespace(
            status="failed",
            current_step="filling_etsy",
            vendoo_item_id="abc123",
            vendoo_url="https://web.vendoo.co/app/item/abc123",
        )
        self.assertEqual(resume_step_for_retry(job), "filling_etsy")

    def test_completed_or_restart_does_not_resume(self):
        from types import SimpleNamespace

        from vendoo_studio.services.job_snapshot import resume_step_for_retry

        job = SimpleNamespace(
            status="completed",
            current_step="filling_etsy",
            vendoo_item_id="abc123",
            vendoo_url="https://web.vendoo.co/app/item/abc123",
        )
        self.assertIsNone(resume_step_for_retry(job))

    def test_marketplace_failure_without_draft_does_not_resume(self):
        from types import SimpleNamespace

        from vendoo_studio.services.job_snapshot import resume_step_for_retry

        job = SimpleNamespace(
            status="failed",
            current_step="filling_etsy",
            vendoo_item_id=None,
            vendoo_url=None,
        )
        self.assertIsNone(resume_step_for_retry(job))

    def test_failed_marketplace_audit_resumes_from_audit(self):
        from types import SimpleNamespace

        from vendoo_studio.services.job_snapshot import resume_step_for_retry

        job = SimpleNamespace(
            status="failed",
            current_step="auditing_mercari",
            vendoo_item_id="abc123",
            vendoo_url="https://web.vendoo.co/app/item/abc123",
        )
        self.assertEqual(resume_step_for_retry(job), "auditing_mercari")

        depop = SimpleNamespace(
            status="failed",
            current_step="auditing_depop",
            vendoo_item_id="abc123",
            vendoo_url="https://web.vendoo.co/app/item/abc123",
        )
        self.assertEqual(resume_step_for_retry(depop), "auditing_depop")



class QueuedSendInterruptedTest(unittest.IsolatedAsyncioTestCase):
    """A queued send cut off by a reconnect goes back in the queue, not to failed."""

    async def test_run_send_leaves_a_resumed_send_queued(self):
        from fastapi import HTTPException

        from vendoo_studio.routes.vendoo_api import _finish_api_send
        from vendoo_studio.services.send_queue import run_send

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        conv = Conversation(title="Nike tee")
        db.add(conv)
        db.commit()
        job = Job(conversation_id=conv.id, approved_revision_id="rev1", listing_snapshot={"title": "Nike tee"},
                  status="dispatched", current_step="vendoo_api_create")
        db.add(job)
        db.commit()
        job_id = job.id
        db.close()
        claim_api_job(job_id)

        async def cut_off(db, conv, conv_id, revisions, snapshot, photos, provider, evidence, job, repo):
            # What a Chrome reconnect does to a live send, then its own exit.
            repo.update_status(job.id, "failed", job.current_step, error=RECONNECTED_SEND)
            _finish_api_send(db, job.id)
            raise HTTPException(409, "Send was cancelled.")

        with patch("vendoo_studio.services.send_queue.SessionLocal", Session), \
             patch("vendoo_studio.routes.vendoo_api._create_claimed_draft", cut_off), \
             patch("vendoo_studio.services.listing_provider.provider_is_configured", return_value=False), \
             patch("vendoo_studio.services.extension_connection.schedule_advance_job_queue"):
            await run_send(job_id)

        check = Session()
        row = check.query(Job).filter(Job.id == job_id).one()
        self.assertEqual((row.status, row.current_step, row.last_error), ("queued", "vendoo_api_queued", None))
        check.close()

if __name__ == "__main__":
    unittest.main()
