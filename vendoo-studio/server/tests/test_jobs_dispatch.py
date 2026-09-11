from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import JobRepo
from vendoo_studio.routes.extension import ExtensionManager, dispatch_queued_jobs, handshake_extension


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
            listing_snapshot={"title": "Nike tee", "description": "Soft tee", "price": 24},
            status="queued",
        )
        db.add(self.job)
        db.commit()
        db.refresh(self.job)
        self.job_id = self.job.id
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
        with patch("vendoo_studio.routes.extension.SessionLocal", self.Session), patch(
            "vendoo_studio.routes.extension.extension_manager", manager
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
        with patch("vendoo_studio.routes.extension.SessionLocal", self.Session), patch(
            "vendoo_studio.routes.extension.extension_manager", manager
        ):
            await dispatch_queued_jobs()

        job = self._job()
        self.assertEqual(job.status, "dispatched")
        self.assertEqual(socket.sent[0]["type"], "job.start")
        self.assertEqual(socket.sent[0]["payload"]["job_id"], self.job_id)
        self.assertFalse(socket.sent[0]["payload"]["options"]["publish"])


class ExtensionHandshakeTest(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_reloads_when_files_changed(self):
        socket = FakeSocket()
        with patch("vendoo_studio.routes.extension.install_bundled_extension", return_value=True), patch(
            "vendoo_studio.routes.extension.pending_extension_reload_token", return_value=None
        ), patch(
            "vendoo_studio.routes.extension.mark_extension_reload_pending", return_value="abc123"
        ):
            accepted = await handshake_extension(socket, None)

        self.assertFalse(accepted)
        self.assertEqual(socket.sent[0]["type"], "extension.reload")
        self.assertEqual(socket.sent[0]["payload"]["generation"], "abc123")

    async def test_handshake_reloads_until_generation_matches(self):
        socket = FakeSocket()
        with patch("vendoo_studio.routes.extension.install_bundled_extension", return_value=False), patch(
            "vendoo_studio.routes.extension.pending_extension_reload_token", return_value="abc123"
        ):
            accepted = await handshake_extension(socket, None)

        self.assertFalse(accepted)
        self.assertEqual(socket.sent[0]["type"], "extension.reload")
        self.assertEqual(socket.sent[0]["payload"]["generation"], "abc123")

    async def test_handshake_accepts_matching_reload_generation(self):
        socket = FakeSocket()
        with patch("vendoo_studio.routes.extension.install_bundled_extension", return_value=False), patch(
            "vendoo_studio.routes.extension.pending_extension_reload_token", return_value="abc123"
        ), patch(
            "vendoo_studio.routes.extension.clear_extension_reload_pending"
        ) as clear:
            accepted = await handshake_extension(socket, "abc123")

        self.assertTrue(accepted)
        self.assertEqual(socket.sent[0]["type"], "connection.accepted")
        clear.assert_called_once()


if __name__ == "__main__":
    unittest.main()
