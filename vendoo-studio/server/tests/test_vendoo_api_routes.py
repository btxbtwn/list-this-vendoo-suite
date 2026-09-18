from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.vendoo_create import VendooCreateError
from vendoo_studio.services.vendoo_import import merge_notes, vendoo_binding

LISTING = {"title": "Levi's 501", "description": "Classic fit.", "price": 48, "condition": "Pre-Owned - Good"}
CREATED = {
    "item_id": "NEWid1234567890abcde",
    "url": "https://web.vendoo.co/app/item/NEWid1234567890abcde",
    "unresolved": [{"field": "primaryColor", "value": "Chartreuse"}],
    "diff": [],
    "stored": {"itemID": "NEWid1234567890abcde", "generalDetails": {"title": "Levi's 501"}},
    "results": [],
}


class _RouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

        def override():
            yield self.db

        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)
        repo = ConversationRepo(self.db)
        self.conv = repo.create(title="Jeans")
        ListingRepo(self.db).save_revision(self.conv.id, LISTING, source="model")
        repo.add_photo(self.conv.id, "a.jpg", "a.jpg", "image/jpeg", 10, width=1600, height=1200)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()


class CreateRouteTest(_RouteTest):
    def test_passes_the_stored_photo_analysis_as_evidence(self):
        """The vision pass already ran; create reuses it instead of re-paying."""
        analysis = (
            "Photo analysis:\n- brand: Carol Rose\n- size: M\n"
            "- color: Red\n- material: Polyester\n- condition: Pre-Owned - Good"
        )
        ConversationRepo(self.db).add_message(
            self.conv.id, "system", analysis, provider="system", model="",
        )
        seen: dict = {}

        async def fake_create(job, listing, photos, *, provider=None, evidence=""):
            seen["evidence"] = evidence
            return CREATED

        with patch("vendoo_studio.services.vendoo_create.create_item", fake_create), \
             patch("vendoo_studio.routes.extension.dispatch_queued_jobs", AsyncMock()):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(seen["evidence"], analysis)

    def test_creates_item_binds_conversation_and_never_queues_the_form_filler(self):
        dispatch = AsyncMock()
        seen: dict = {}

        async def fake_create(job, listing, photos, *, provider=None, evidence=""):
            seen.update(
                status=job.status, title=listing["title"], photos=len(photos),
                evidence=evidence,
            )
            return CREATED

        with patch("vendoo_studio.services.vendoo_create.create_item", fake_create), \
             patch("vendoo_studio.routes.extension.dispatch_queued_jobs", dispatch):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["item_id"], CREATED["item_id"])
        self.assertEqual(body["unresolved"], CREATED["unresolved"])
        dispatch.assert_not_called()

        # Held in "dispatched" while it runs so the Send queue skips it.
        self.assertEqual(
            seen,
            {"status": "dispatched", "title": "Levi's 501", "photos": 1, "evidence": ""},
        )

        self.db.expire_all()
        job = JobRepo(self.db).get(body["job_id"])
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.current_step, "vendoo_api_created")
        self.assertEqual(job.vendoo_item_id, CREATED["item_id"])
        self.assertEqual(vendoo_binding(ConversationRepo(self.db).get(self.conv.id).notes)["vendooItemId"], CREATED["item_id"])
        self.assertEqual(JobRepo(self.db).get_vendoo_draft(job.id)["source"], "api")

    def test_failure_marks_job_failed_and_leaves_conversation_unbound(self):
        with patch("vendoo_studio.services.vendoo_create.create_item",
                   AsyncMock(side_effect=VendooCreateError("Vendoo createItem returned 400: bad item"))):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 502)
        self.assertIn("bad item", res.json()["detail"])
        self.db.expire_all()
        jobs = JobRepo(self.db).list_by_conversation(self.conv.id)
        self.assertEqual([j.status for j in jobs], ["failed"])
        self.assertEqual(vendoo_binding(ConversationRepo(self.db).get(self.conv.id).notes), {})

    def test_refuses_already_bound_listing(self):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "old1"})
        self.db.commit()
        res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 409)
        self.assertIn("old1", res.json()["detail"])

    def test_refuses_without_photos_or_listing(self):
        bare = ConversationRepo(self.db).create(title="Empty")
        self.assertEqual(self.client.post(f"/api/conversations/{bare.id}/vendoo-api/create").status_code, 400)
        ListingRepo(self.db).save_revision(bare.id, LISTING, source="model")
        res = self.client.post(f"/api/conversations/{bare.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 400)
        self.assertIn("photo", res.json()["detail"])

    def test_refuses_while_chrome_is_busy(self):
        other = ConversationRepo(self.db).create(title="Other")
        rev = ListingRepo(self.db).save_revision(other.id, LISTING, source="model")
        JobRepo(self.db).create(other.id, rev.id, LISTING, status="dispatched")
        res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 409)
        self.assertIn("busy", res.json()["detail"])


class ProbeRouteTest(_RouteTest):
    def test_defaults_to_every_known_item(self):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "known1"})
        self.db.commit()
        probe = AsyncMock(return_value={
            "schema": {"fields": {"condition": {}}, "item_count": 3}, "learned_from": 1, "failures": [],
        })
        with patch("vendoo_studio.services.vendoo_create.probe_schema", probe):
            res = self.client.post("/api/vendoo-api/probe", json={})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"ok": True, "learned_from": 1, "item_count": 3, "fields": ["condition"], "failures": []})
        self.assertEqual(probe.call_args.args[1], ["known1"])

    def test_explicit_ids_and_nothing_to_learn(self):
        probe = AsyncMock(return_value={"schema": {"fields": {}, "item_count": 0}, "learned_from": 0, "failures": []})
        with patch("vendoo_studio.services.vendoo_create.probe_schema", probe):
            self.client.post("/api/vendoo-api/probe", json={"item_ids": ["a", "b"]})
        self.assertEqual(probe.call_args.args[1], ["a", "b"])
        self.assertEqual(self.client.post("/api/vendoo-api/probe", json={}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
