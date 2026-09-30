import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.routes.jobs import EnsureDraftJobRequest, enqueue_send, cancel_job, get_queue
from vendoo_studio.routes.extension import dispatch_queued_jobs
from vendoo_studio.services.vendoo_create import VendooCreateError


class SendQueueTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine)
        self.db = self.sessions()
        self.tasks = []
        self.patches = [
            patch("vendoo_studio.routes.extension.SessionLocal", self.sessions),
            patch("vendoo_studio.services.send_queue.SessionLocal", self.sessions),
            patch("vendoo_studio.routes.extension.schedule_advance_job_queue"),
            patch("vendoo_studio.routes.extension.extension_manager", MagicMock(connected=True)),
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
        for p in reversed(self.patches):
            p.stop()
        self.db.close()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    def listing(self, title):
        repo = ConversationRepo(self.db)
        conv = repo.create(title=title)
        ListingRepo(self.db).save_revision(conv.id, {"title": title, "price": 30}, source="model")
        repo.add_photo(conv.id, "a.jpg", "a.jpg", "image/jpeg", 10)
        return conv

    async def enqueue(self, conv):
        return await enqueue_send(EnsureDraftJobRequest(conversation_id=conv.id), self.db)

    async def test_fifo_snapshots_and_failure_advance(self):
        first, second = self.listing("First"), self.listing("Second")
        a, b = await self.enqueue(first), await self.enqueue(second)
        ListingRepo(self.db).save_revision(second.id, {"title": "Later edit"}, source="user")
        seen = []
        started, finish = asyncio.Event(), asyncio.Event()

        async def create(job, snapshot, photos, **kwargs):
            seen.append(snapshot["title"])
            if snapshot["title"] == "First":
                started.set()
                await finish.wait()
                raise VendooCreateError("Test failure")
            return {
                "item_id": "draft-2", "url": "https://web.vendoo.co/app/item/draft-2",
                "unresolved": [], "diff": [], "stored": {"generalDetails": {"title": "Second"}},
            }

        with patch("vendoo_studio.services.vendoo_create.create_item", create):
            await dispatch_queued_jobs()
            await started.wait()
            await dispatch_queued_jobs()
            self.assertEqual(len(self.tasks), 1)
            finish.set()
            await self.tasks[0]
            await dispatch_queued_jobs()
            await self.tasks[1]
        self.db.expire_all()
        self.assertEqual(seen, ["First", "Second"])
        self.assertEqual(JobRepo(self.db).get(a.id).status, "failed")
        self.assertEqual(JobRepo(self.db).get(b.id).status, "completed")
        self.assertEqual(ListingRepo(self.db).get_revisions(second.id)[0].listing_json["title"], "Later edit")
        from vendoo_studio.services.vendoo_watch import studio_has_unpushed_edits

        self.assertTrue(studio_has_unpushed_edits(self.db, second.id))

    async def test_duplicate_rejected_and_waiting_send_cancelled(self):
        conv = self.listing("Waiting")
        job = await self.enqueue(conv)
        with self.assertRaises(HTTPException) as caught:
            await self.enqueue(conv)
        self.assertEqual(caught.exception.status_code, 409)
        with patch("vendoo_studio.routes.extension.extension_manager.send_message", AsyncMock()):
            await cancel_job(job.id, self.db)
        await dispatch_queued_jobs()
        self.assertEqual(self.tasks, [])
        self.assertEqual(JobRepo(self.db).get(job.id).status, "cancelled")

    async def test_disconnected_send_stays_queued_and_feed_includes_generation(self):
        conv = self.listing("Generating")
        job = await self.enqueue(conv)
        with patch("vendoo_studio.routes.extension.extension_manager", MagicMock(connected=False)):
            await dispatch_queued_jobs()
        self.assertEqual(self.tasks, [])
        self.assertEqual(JobRepo(self.db).get(job.id).status, "queued")
        from vendoo_studio.services.streaming import GenerationRun
        run = GenerationRun()
        run.last_status = "Reading photos"
        with patch("vendoo_studio.services.streaming.active_generations", return_value={conv.id: run}), \
             patch("vendoo_studio.services.streaming.active_generation", return_value=run):
            feed = await get_queue(self.db)
            with self.assertRaises(HTTPException):
                await self.enqueue(self.listing("Busy"))
        self.assertEqual(feed["work"][0]["detail"], "Reading photos")
        self.assertEqual(feed["jobs"][0].id, job.id)

    async def test_background_worker_automatically_advances_to_bound_update(self):
        from vendoo_studio.services.vendoo_import import merge_notes

        first, second = self.listing("Create"), self.listing("Update")
        second.notes = merge_notes(second.notes, {"vendooItemId": "existing-draft"})
        self.db.commit()
        done = asyncio.Event()
        seen = []

        async def create(job, snapshot, photos, **kwargs):
            seen.append("create")
            return {"item_id": "new-draft", "url": "https://web.vendoo.co/app/item/new-draft", "unresolved": [], "diff": []}

        async def save(db, conv, conv_id, item_id, revisions, snapshot, provider, evidence, job, repo):
            seen.append((item_id, snapshot["title"]))
            repo.update_status(job.id, "completed", "vendoo_api_saved")
            done.set()

        with patch("vendoo_studio.routes.extension.schedule_advance_job_queue", side_effect=lambda: asyncio.create_task(dispatch_queued_jobs())), \
             patch("vendoo_studio.services.vendoo_create.create_item", create), \
             patch("vendoo_studio.routes.vendoo_api._save_claimed_draft", save):
            await self.enqueue(first)
            await self.enqueue(second)
            await asyncio.wait_for(done.wait(), timeout=3)
            await asyncio.gather(*self.tasks)
        self.assertEqual(seen, ["create", ("existing-draft", "Update")])
