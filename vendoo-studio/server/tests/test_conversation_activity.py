from __future__ import annotations

import asyncio
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.diagnostics import DiagnosticRun, FieldObservation  # noqa: F401
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import activity


class ActivityRegistryTest(unittest.IsolatedAsyncioTestCase):
    """Chat is only "done" once nothing registered for the listing is still running."""

    def tearDown(self):
        activity.reset()

    async def test_task_is_listed_until_it_finishes(self):
        gate = asyncio.Event()
        task = activity.track_task("c1", "Filling discovered fields…", asyncio.create_task(gate.wait()))
        self.assertEqual(activity.running("c1"), ["Filling discovered fields…"])
        gate.set()
        await task
        await asyncio.sleep(0)
        self.assertEqual(activity.running("c1"), [])

    async def test_cancel_stops_the_task_and_clears_the_listing(self):
        task = activity.track_task("c1", "Saving listing…", asyncio.create_task(asyncio.sleep(60)))
        inline = activity.begin("c1", "Answering…")
        activity.cancel("c1")
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(inline.cancelled)
        self.assertEqual(activity.running("c1"), [])
        self.assertEqual(activity.running("other"), [])


class ConversationActivityRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = ConversationRepo(self.db).create(title="Nike tee")

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        activity.reset()
        self.db.close()

    def activity(self) -> dict:
        response = self.client.get(f"/api/conversations/{self.conv.id}/activity")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def add_job(self, status: str) -> Job:
        revision = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Nike tee"}, "generate")
        return JobRepo(self.db).create(self.conv.id, revision.id, revision.listing_json, status=status)

    def test_idle_listing_reports_done_and_the_latest_message(self):
        message = ConversationRepo(self.db).add_message(self.conv.id, "assistant", "Listing saved.")
        body = self.activity()
        self.assertFalse(body["busy"])
        self.assertEqual(body["items"], [])
        self.assertEqual(body["message_count"], 1)
        self.assertEqual(body["last_message_id"], message.id)

    def test_background_work_keeps_the_listing_busy(self):
        activity.begin(self.conv.id, "Filling discovered fields…")
        body = self.activity()
        self.assertTrue(body["busy"])
        self.assertEqual(body["items"], ["Filling discovered fields…"])

    def test_an_active_vendoo_job_keeps_the_listing_busy(self):
        self.add_job("dispatched")
        self.assertTrue(self.activity()["busy"])

    def test_finished_jobs_do_not(self):
        self.add_job("completed")
        self.assertFalse(self.activity()["busy"])

    def test_stop_ends_background_work_and_jobs(self):
        work = activity.begin(self.conv.id, "Answering…")
        job = self.add_job("queued")

        response = self.client.post(f"/api/conversations/{self.conv.id}/stop")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(work.cancelled)
        self.db.expire_all()
        self.assertEqual(JobRepo(self.db).get(job.id).status, "cancelled")
        self.assertFalse(self.activity()["busy"])


if __name__ == "__main__":
    unittest.main()
