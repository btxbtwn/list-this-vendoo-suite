"""The job watchdog fails dead and silent jobs, frees the slot, and resumes a dead send once."""

import asyncio
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import update
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base, make_engine
from vendoo_studio.models.job import ABANDONED_SEND, AUTO_RETRY_EVENT, Job, JobEvent
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.extension_connection import ExtensionManager, dispatch_queued_jobs
from vendoo_studio.services import job_watchdog
from vendoo_studio.services.api_job_lock import claim_api_job, release_api_job
from vendoo_studio.services.browser_bridge import BrowserBridgeError
from vendoo_studio.services.job_watchdog import STALL_AFTER, STALLED_JOB, fail_stalled_jobs


class _ConnectedManager(ExtensionManager):
    """A real wait registry with Chrome reported as connected."""

    connected = True


def _sessions(test):
    # The watchdog and dispatcher open sessions on worker threads. StaticPool
    # would hand them the test session's live SQLite connection, allowing
    # concurrent cursor/transaction use and occasionally crashing the worker.
    directory = TemporaryDirectory(prefix="watchdog-test-")
    test.addCleanup(directory.cleanup)
    engine = make_engine(f"sqlite:///{Path(directory.name) / 'watchdog.db'}")
    test.addCleanup(engine.dispose)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


class FailStalledJobsTest(unittest.TestCase):
    def setUp(self):
        self.db = _sessions(self)()
        self.manager = _ConnectedManager()
        p = patch("vendoo_studio.services.extension_connection.extension_manager", self.manager)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.db.close)
        self.live: list[str] = []
        self.addCleanup(lambda: [release_api_job(job_id) for job_id in self.live])

    def job(self, *, status="dispatched", step="vendoo_api_fields", live=False):
        repo = ConversationRepo(self.db)
        conv = repo.create(title="Tee")
        rev = ListingRepo(self.db).save_revision(conv.id, {"title": "Tee"}, source="model")
        job = JobRepo(self.db).create(conv.id, rev.id, {"title": "Tee"}, status=status, current_step=step)
        if live:
            claim_api_job(job.id)
            self.live.append(job.id)
        return job

    def later(self, after: timedelta) -> datetime:
        return datetime.now(UTC) + after

    def status(self, job):
        self.db.expire_all()
        return JobRepo(self.db).get(job.id)

    def test_a_silent_live_send_is_failed_and_its_listing_freed(self):
        job = self.job(live=True)
        ConversationRepo(self.db).update_status(job.conversation_id, "listing")
        failed = fail_stalled_jobs(self.db, now=self.later(STALL_AFTER + timedelta(minutes=1)))
        self.assertEqual(failed, [job.id])
        row = self.status(job)
        self.assertEqual((row.status, row.last_error), ("failed", STALLED_JOB))
        self.assertEqual(row.current_step, "vendoo_api_fields")
        event = JobRepo(self.db).latest_event(job.id, "watchdog_failed")
        self.assertEqual(event.payload["reason"], "silent")
        # The listing drops the busy label and shows the failure.
        ConversationRepo(self.db).reconcile_job_statuses()
        self.assertEqual(ConversationRepo(self.db).get(job.conversation_id).status, "failed")

    def test_a_live_send_with_recent_progress_is_untouched(self):
        job = self.job(live=True)
        now = self.later(STALL_AFTER + timedelta(minutes=5))
        event = JobRepo(self.db).add_event(job.id, "vendoo_api_timing", payload={})
        self.db.execute(update(JobEvent).where(JobEvent.id == event.id).values(created_at=now - timedelta(minutes=2)))
        self.db.commit()
        self.assertEqual(fail_stalled_jobs(self.db, now=now), [])
        self.assertEqual(self.status(job).status, "dispatched")

    def test_a_live_send_inside_the_threshold_is_untouched(self):
        job = self.job(live=True)
        self.assertEqual(fail_stalled_jobs(self.db, now=self.later(STALL_AFTER - timedelta(seconds=30))), [])
        self.assertEqual(self.status(job).status, "dispatched")

    def test_a_send_no_process_is_running_is_resumed_once_after_the_grace(self):
        job = self.job()
        self.assertEqual(fail_stalled_jobs(self.db, now=self.later(timedelta(seconds=1))), [])
        self.assertEqual(fail_stalled_jobs(self.db, now=self.later(timedelta(seconds=30))), [job.id])
        row = self.status(job)
        self.assertEqual((row.status, row.current_step, row.last_error), ("queued", "vendoo_api_queued", None))
        self.assertEqual(JobRepo(self.db).latest_event(job.id, "watchdog_failed").payload["reason"], "dead")
        self.assertEqual(JobRepo(self.db).latest_event(job.id, AUTO_RETRY_EVENT).payload["reason"], ABANDONED_SEND)

    def test_a_resumed_send_that_dies_again_stays_failed(self):
        job = self.job()
        fail_stalled_jobs(self.db, now=self.later(timedelta(seconds=30)))
        JobRepo(self.db).update_status(job.id, "dispatched", "vendoo_api_photos")
        self.assertEqual(fail_stalled_jobs(self.db, now=self.later(timedelta(seconds=30))), [job.id])
        row = self.status(job)
        self.assertEqual((row.status, row.last_error), ("failed", ABANDONED_SEND))

    def test_an_extension_fill_is_failed_only_once_it_goes_silent(self):
        # Form fills are driven by Chrome, not a worker here; only silence counts.
        job = self.job(step="filling_fields")
        self.assertEqual(fail_stalled_jobs(self.db, now=self.later(timedelta(minutes=5))), [])
        self.assertEqual(fail_stalled_jobs(self.db, now=self.later(STALL_AFTER + timedelta(minutes=1))), [job.id])
        self.assertEqual(self.status(job).last_error, STALLED_JOB)

    def test_waiting_and_finished_jobs_are_never_touched(self):
        jobs = [
            self.job(status="queued", step="vendoo_api_queued"),
            self.job(status="awaiting_extension", step="awaiting_extension"),
            self.job(status="completed", step="vendoo_api_created"),
            self.job(status="cancelled", step=None),
        ]
        self.assertEqual(fail_stalled_jobs(self.db, now=self.later(timedelta(days=2))), [])
        self.assertEqual(
            [self.status(job).status for job in jobs],
            ["queued", "awaiting_extension", "completed", "cancelled"],
        )

    def test_a_job_without_timestamps_counts_as_silent(self):
        job = self.job(live=True)
        self.db.execute(update(Job).where(Job.id == job.id).values(updated_at=None))
        self.db.commit()
        self.assertEqual(fail_stalled_jobs(self.db), [job.id])


class SweepTest(unittest.IsolatedAsyncioTestCase):
    async def test_worker_session_does_not_reuse_a_live_connection(self):
        sessions = _sessions(self)
        with sessions() as db:
            connection = db.connection().connection.driver_connection

            def worker_connection():
                with sessions() as worker:
                    return worker.connection().connection.driver_connection

            other = await asyncio.to_thread(worker_connection)
            self.assertIsNot(connection, other)

    async def test_database_work_runs_off_the_loop_and_waits_are_cancelled_on_it(self):
        sessions = _sessions(self)
        db = sessions()
        self.addCleanup(db.close)
        manager = _ConnectedManager()
        conv = ConversationRepo(db).create(title="Tee")
        rev = ListingRepo(db).save_revision(conv.id, {"title": "Tee"}, source="model")
        job = JobRepo(db).create(conv.id, rev.id, {}, status="dispatched", current_step="vendoo_api_photos")
        claim_api_job(job.id)
        self.addCleanup(release_api_job, job.id)
        mine = manager.register_wait("mine", job.id)
        other = manager.register_wait("other", "another-job")
        loop_thread = threading.get_ident()
        db_threads = []
        real = job_watchdog.fail_stalled_jobs

        def fail(session, **kwargs):
            db_threads.append(threading.get_ident())
            return real(session, now=datetime.now(UTC) + STALL_AFTER + timedelta(minutes=1))

        with patch("vendoo_studio.database.SessionLocal", sessions), \
             patch("vendoo_studio.services.extension_connection.extension_manager", manager), \
             patch("vendoo_studio.services.extension_connection.dispatch_queued_jobs", AsyncMock()) as dispatch, \
             patch("vendoo_studio.services.native_marketplaces.reconcile", AsyncMock(return_value=0)) as reconcile, \
             patch.object(job_watchdog, "fail_stalled_jobs", fail):
            self.assertEqual(await job_watchdog.sweep(), [job.id])
        # The stalled job's result is read before the next one starts.
        reconcile.assert_awaited_once_with(chrome=True)
        self.assertEqual(len(db_threads), 1)
        self.assertNotEqual(db_threads[0], loop_thread)
        self.assertTrue(mine.cancelled())
        self.assertFalse(other.done())
        dispatch.assert_awaited_once()
        other.cancel()


class QueueAfterStallTest(unittest.IsolatedAsyncioTestCase):
    """One job at a time: a stalled send frees the slot for the next approved one."""

    def setUp(self):
        self.sessions = _sessions(self)
        self.db = self.sessions()
        self.tasks = []
        self.manager = _ConnectedManager()
        self.patches = [
            patch("vendoo_studio.database.SessionLocal", self.sessions),
            patch("vendoo_studio.services.extension_connection.SessionLocal", self.sessions),
            patch("vendoo_studio.services.send_queue.SessionLocal", self.sessions),
            patch("vendoo_studio.services.extension_connection.schedule_advance_job_queue"),
            patch("vendoo_studio.services.extension_connection.extension_manager", self.manager),
            patch("vendoo_studio.services.streaming.spawn", self.spawn),
            patch("vendoo_studio.services.listing_provider.provider_is_configured", return_value=False),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    async def asyncTearDown(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.db.close()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    async def enqueue(self, title):
        from vendoo_studio.routes.jobs import SendJobRequest, enqueue_send
        from vendoo_studio.services.send_review import remember_review, review_inputs

        repo = ConversationRepo(self.db)
        conv = repo.create(title=title)
        ListingRepo(self.db).save_revision(conv.id, {"title": title, "price": 30}, source="model")
        repo.add_photo(conv.id, "a.jpg", "a.jpg", "image/jpeg", 10)
        inputs, fingerprint = review_inputs(self.db, conv.id)
        review_id = remember_review(inputs, fingerprint, {
            "snapshot": inputs["snapshot"], "specifics": {}, "schema": None,
            "unresolved": [], "unfilled": [], "expected_version": None,
        })
        return await enqueue_send(SendJobRequest(conversation_id=conv.id, review_id=review_id), self.db)

    def silence(self, job_id: str) -> None:
        quiet = datetime.now(UTC) - STALL_AFTER - timedelta(minutes=1)
        self.db.execute(update(Job).where(Job.id == job_id).values(updated_at=quiet))
        self.db.execute(update(JobEvent).where(JobEvent.job_id == job_id).values(created_at=quiet))
        self.db.commit()

    async def test_stalled_send_fails_and_the_next_queued_send_runs_once(self):
        seen = []
        hung = asyncio.Event()

        async def create(job, snapshot, photos, **kwargs):
            seen.append(snapshot["title"])
            if snapshot["title"] == "First":
                hung.set()
                try:
                    # Chrome never answers, as in browser_bridge.request.
                    await self.manager.register_wait("never", job.id)
                except asyncio.CancelledError as exc:
                    raise BrowserBridgeError("Send was cancelled.") from exc
            return {
                "item_id": "draft-2", "url": "https://web.vendoo.co/app/item/draft-2",
                "unresolved": [], "diff": [], "stored": {"generalDetails": {"title": "Second"}},
            }

        with patch("vendoo_studio.services.vendoo_create.create_item", create):
            a, b = await self.enqueue("First"), await self.enqueue("Second")
            await dispatch_queued_jobs()
            await asyncio.wait_for(hung.wait(), timeout=3)
            # The second send waits its turn while the first holds the slot.
            self.assertEqual(await job_watchdog.sweep(), [])
            self.assertEqual(len(self.tasks), 1)
            self.assertEqual(JobRepo(self.db).get(b.id).status, "queued")

            self.silence(a.id)
            self.assertEqual(await job_watchdog.sweep(), [a.id])
            # The second send starts only once the first has failed, so wait for both.
            async def both_ran():
                while len(self.tasks) < 2:
                    await asyncio.sleep(0.01)
                await asyncio.gather(*self.tasks)

            await asyncio.wait_for(both_ran(), timeout=3)
            # Nothing else is stuck: a further pass fails nothing and starts nothing.
            self.assertEqual(await job_watchdog.sweep(), [])

        self.db.expire_all()
        first, second = JobRepo(self.db).get(a.id), JobRepo(self.db).get(b.id)
        self.assertEqual((first.status, first.last_error), ("failed", STALLED_JOB))
        self.assertEqual(second.status, "completed")
        # The stalled send is never retried.
        self.assertEqual(seen, ["First", "Second"])
        self.assertEqual(len(self.tasks), 2)
        ConversationRepo(self.db).reconcile_job_statuses()
        self.assertEqual(ConversationRepo(self.db).get(first.conversation_id).status, "failed")


class WatchdogLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_runs_a_pass_on_start_and_keeps_going_after_an_error(self):
        calls = []

        async def sweep():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database locked")
            return []

        with patch.object(job_watchdog, "sweep", sweep), \
             patch.object(job_watchdog, "SWEEP_INTERVAL_SEC", 0), \
             patch.object(job_watchdog, "log", MagicMock()):
            task = job_watchdog.start_job_watchdog()
            self.assertIs(job_watchdog.start_job_watchdog(), task)
            while len(calls) < 3:
                await asyncio.sleep(0)
            job_watchdog.stop_job_watchdog()
            with self.assertRaises(asyncio.CancelledError):
                await task
