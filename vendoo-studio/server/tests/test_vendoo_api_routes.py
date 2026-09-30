from __future__ import annotations

import asyncio
import json
import unittest
from concurrent.futures import CancelledError
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import update

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.job import Job
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
    def test_create_remembers_preparation_for_the_next_update(self):
        prepared = {**LISTING, "category_id": "tops", "_vendoo_preparation": {"field_signature": "prepared"}}
        create = AsyncMock(return_value={**CREATED, "prepared_listing": prepared})
        with patch("vendoo_studio.services.vendoo_create.create_item", create):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 200, res.text)
        revision = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        self.assertEqual(revision.listing_json, prepared)
        self.assertEqual(revision.source, "vendoo_prepare")

    def test_create_preparation_does_not_replace_an_edit_made_during_send(self):
        edited = {**LISTING, "description": "Newer edit"}

        async def create(*args, **kwargs):
            ListingRepo(self.db).save_revision(self.conv.id, edited, source="manual")
            return {**CREATED, "prepared_listing": {**LISTING, "_vendoo_preparation": {}}}

        with patch("vendoo_studio.services.vendoo_create.create_item", create):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(ListingRepo(self.db).get_revisions(self.conv.id)[0].listing_json, edited)

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
        self.assertIn("Levi's 501", res.json()["detail"])

    def _age(self, job, *, minutes: int = 10) -> None:
        self.db.execute(
            update(Job).where(Job.id == job.id).values(
                updated_at=datetime.now(UTC) - timedelta(minutes=minutes),
            )
        )
        self.db.commit()
        self.db.expire_all()

    def test_a_dead_send_does_not_count_as_another_job(self):
        other = ConversationRepo(self.db).create(title="Other")
        rev = ListingRepo(self.db).save_revision(other.id, LISTING, source="model")
        stale = JobRepo(self.db).create(
            other.id, rev.id, {**LISTING, "title": "Old tee"},
            status="dispatched", current_step="vendoo_api_fields",
        )
        self._age(stale)

        async def fake_create(job, listing, photos, *, provider=None, evidence=""):
            return CREATED

        with patch("vendoo_studio.services.vendoo_create.create_item", fake_create):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 200, res.text)
        self.db.expire_all()
        self.assertEqual(JobRepo(self.db).get(stale.id).status, "failed")

    def test_this_listings_live_send_is_not_reported_as_another_job(self):
        from vendoo_studio.services.api_job_lock import claim_api_job, release_api_job

        rev = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        job = JobRepo(self.db).create(
            self.conv.id, rev.id, LISTING, status="dispatched", current_step="vendoo_api_fields",
        )
        claim_api_job(job.id)
        try:
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        finally:
            release_api_job(job.id)
        self.assertEqual(res.status_code, 409)
        self.assertIn("already queued or sending", res.json()["detail"])
        self.assertNotIn("another Vendoo job", res.json()["detail"])

    def test_a_send_that_just_started_still_blocks_a_second_one(self):
        rev = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        JobRepo(self.db).create(
            self.conv.id, rev.id, LISTING, status="dispatched", current_step="vendoo_api_fields",
        )
        res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.assertEqual(res.status_code, 409)
        self.assertIn("already queued or sending", res.json()["detail"])

    def test_job_list_drops_a_dead_send_so_the_card_can_clear(self):
        rev = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        stale = JobRepo(self.db).create(
            self.conv.id, rev.id, LISTING, status="dispatched", current_step="vendoo_api_fields",
        )
        self._age(stale)
        res = self.client.get("/api/jobs", params={"conversation_id": self.conv.id})
        self.assertEqual(res.status_code, 200, res.text)
        match = next(row for row in res.json() if row["id"] == stale.id)
        self.assertEqual(match["status"], "failed")

    def test_a_cancelled_send_does_not_stay_dispatched(self):
        async def fake_create(job, listing, photos, *, provider=None, evidence=""):
            raise asyncio.CancelledError()

        with patch("vendoo_studio.services.vendoo_create.create_item", fake_create):
            with self.assertRaises(CancelledError):
                self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/create")
        self.db.expire_all()
        jobs = JobRepo(self.db).list_by_conversation(self.conv.id)
        self.assertEqual([job.status for job in jobs], ["failed"])


class PullRouteTest(_RouteTest):
    """Pull must refresh the job draft so thread marketplace status stays current."""

    def test_pull_overwrites_stale_draft_cache(self):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "itm1"})
        self.db.commit()
        rev = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        job = JobRepo(self.db).create(
            self.conv.id, rev.id, LISTING, vendoo_item_id="itm1", status="completed",
        )
        JobRepo(self.db).save_vendoo_draft(
            job.id,
            item={"itemID": "itm1", "listings": {"ebay": {"status": {"notListed": True}}}},
            item_id="itm1",
            source="stale",
        )
        fresh = {
            "itemID": "itm1",
            "dateLastModified": 9000,
            "generalDetails": {"title": "Levi's 501"},
            "listings": {"ebay": {"status": {"listed": True}}},
        }

        async def fake_run_ops(job, ops, **_kwargs):
            return {"ok": True, "results": [{"op": "get_item", "ok": True, "item": fresh}]}

        with patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/pull")
        self.assertEqual(res.status_code, 200, res.text)
        cached = JobRepo(self.db).get_vendoo_draft(job.id)
        self.assertEqual(cached["source"], "vendoo_pull")
        self.assertEqual(cached["item"]["listings"]["ebay"]["status"], {"listed": True})


class ListRouteTest(_RouteTest):
    """Publishing is seller-triggered. The rails matter more than the call."""

    def bind(self):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "itm1"})
        self.db.commit()

    def test_refuses_without_confirmation(self):
        self.bind()
        res = self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-api/list",
            json={"marketplaces": ["ebay"]},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Confirm", res.json()["detail"])

    def test_refuses_without_a_named_marketplace(self):
        self.bind()
        res = self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-api/list",
            json={"marketplaces": [], "confirm": True},
        )
        # Never publish everywhere by omission.
        self.assertEqual(res.status_code, 422)

    def test_refuses_when_no_draft_exists(self):
        res = self.client.post(
            f"/api/conversations/{self.conv.id}/vendoo-api/list",
            json={"marketplaces": ["ebay"], "confirm": True},
        )
        self.assertEqual(res.status_code, 409)

    def test_confirmed_list_sends_only_the_named_marketplaces(self):
        self.bind()
        sent = {}

        async def fake_run_ops(job, ops, **_kwargs):
            sent.update(ops[0])
            return {"ok": True, "results": [{"op": "list_item", "ok": True, "result": {"queued": True}}]}

        with patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops):
            res = self.client.post(
                f"/api/conversations/{self.conv.id}/vendoo-api/list",
                json={"marketplaces": ["eBay", " poshmark "], "confirm": True},
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(sent["op"], "list_item")
        self.assertEqual(sent["marketplaces"], ["ebay", "poshmark"])
        self.assertEqual(res.json()["action"], "list")

    def test_delist_uses_the_delist_op(self):
        self.bind()
        sent = {}

        async def fake_run_ops(job, ops, **_kwargs):
            sent.update(ops[0])
            return {"ok": True, "results": [{"op": "delist_item", "ok": True, "result": {}}]}

        with patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops):
            res = self.client.post(
                f"/api/conversations/{self.conv.id}/vendoo-api/delist",
                json={"marketplaces": ["ebay"], "confirm": True},
            )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(sent["op"], "delist_item")


class DeleteRouteTest(_RouteTest):
    """Deleting cannot be undone, so the rails matter more than the call."""

    def test_refuses_without_confirmation(self):
        res = self.client.post("/api/vendoo-api/delete", json={"item_ids": ["junk1"]})
        self.assertEqual(res.status_code, 400)

    def test_refuses_an_empty_list(self):
        res = self.client.post("/api/vendoo-api/delete", json={"item_ids": [], "confirm": True})
        self.assertEqual(res.status_code, 422)

    def test_never_deletes_an_item_a_conversation_points_at(self):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "keepme"})
        self.db.commit()
        sent = []

        async def fake_run_ops(job, ops, **_kwargs):
            sent.extend(op["item_id"] for op in ops)
            return {"ok": True, "results": [
                {"op": "delete_item", "ok": True, "deleted": op["item_id"]} for op in ops
            ]}

        with patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops):
            res = self.client.post(
                "/api/vendoo-api/delete",
                json={"item_ids": ["keepme", "junk1"], "confirm": True},
            )
        body = res.json()
        self.assertEqual(sent, ["junk1"])
        self.assertEqual(body["deleted"], ["junk1"])
        self.assertEqual(body["refused"], ["keepme"])


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


class SaveRouteTest(_RouteTest):
    """Update Vendoo writes the form; the live listings stay as they were."""

    def bind(self):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "itm1"})
        self.db.commit()

    def test_prepared_listing_uses_no_ai_on_save_or_copy_edit(self):
        from vendoo_studio.services.job_snapshot import prepare_listing_snapshot
        from vendoo_studio.services.vendoo_create import prepare_listing_fields_for_vendoo
        from vendoo_studio.services.vendoo_specifics import FieldSpec

        self.bind()
        listing = {**LISTING, "category_path": "Clothing > Tops", "category_id": "tops",
                   "marketplace_category_ids": {"ebay": "shirts"}}
        fields = {"ebay": {"Season": FieldSpec("Season")}}
        model = AsyncMock(return_value=[])

        async def ops(_job, calls, **kwargs):
            self.assertTrue(all(call["op"] in {"get_item", "update_item"} for call in calls))
            return {"ok": True, "results": [{"op": calls[0]["op"], "ok": True, "item": {
                "itemID": "itm1", "generalDetails": {"images": []},
            }}]}

        with patch("vendoo_studio.services.vendoo_create.fetch_listing_specifics", AsyncMock(return_value=fields)), \
             patch("vendoo_studio.services.vendoo_create._mappable_marketplaces", return_value=()), \
             patch("vendoo_studio.services.vendoo_create.run_ops", ops), \
             patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", model), \
             patch("vendoo_studio.services.listing_provider.get_listing_provider", return_value=object()), \
             patch("vendoo_studio.services.listing_provider.provider_is_configured", return_value=True):
            snapshot = prepare_listing_snapshot(self.db, self.conv, listing)
            prepared = asyncio.run(prepare_listing_fields_for_vendoo(None, snapshot, provider=object()))[0]
            ListingRepo(self.db).save_revision(self.conv.id, prepared, source="vendoo_prepare")
            self.assertEqual(model.await_count, 1)
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/save")
            self.assertEqual(res.status_code, 200, res.text)
            edited = {**ListingRepo(self.db).get_revisions(self.conv.id)[0].listing_json,
                      "price": 40, "description": "Seller's revised copy"}
            ListingRepo(self.db).save_revision(self.conv.id, edited, source="manual")
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/save")
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(model.await_count, 1)

    def test_save_remembers_preparation_and_keeps_display_labels(self):
        self.bind()
        self.conv.notes = merge_notes(self.conv.notes, {"vendooLabels": "To List"})
        self.db.commit()

        async def prepare(_job, listing, **kwargs):
            return {**listing, "labels": ["resolvedId"], "_vendoo_preparation": {"field_signature": "prepared"}}, {}, None, [], []

        async def ops(_job, calls, **kwargs):
            return {"ok": True, "results": [{"op": calls[0]["op"], "ok": True, "item": {
                "itemID": "itm1", "generalDetails": {"images": []},
            }}]}

        with patch("vendoo_studio.services.vendoo_create.prepare_listing_for_vendoo", prepare), \
             patch("vendoo_studio.services.vendoo_create.run_ops", ops):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/save")
        self.assertEqual(res.status_code, 200, res.text)
        listing = ListingRepo(self.db).get_revisions(self.conv.id)[0].listing_json
        self.assertEqual(listing["labels"], ["To List"])
        self.assertEqual(listing["_vendoo_preparation"]["field_signature"], "prepared")

    def save(self, item):
        async def fake_run_ops(job, ops, **_kwargs):
            if ops[0]["op"] == "get_item":
                return {"ok": True, "results": [{"op": "get_item", "item": item}]}
            return {"ok": True, "results": [{"op": "update_item", "ok": True}]}

        async def fake_prepare(job, listing, **kwargs):
            return listing, {}, None, [], []

        with (
            patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops),
            patch("vendoo_studio.services.vendoo_create.prepare_listing_for_vendoo", fake_prepare),
            patch(
                "vendoo_studio.services.vendoo_api.build_vendoo_item",
                lambda *a, **k: ({"generalDetails": {"title": "Levi's 501"}}, []),
            ),
        ):
            return self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/save")

    def test_general_form_is_written_before_the_marketplace_forms(self):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {"vendooItemId": "itm1"})
        self.db.commit()
        current = {
            "itemID": "itm1",
            "userID": "u1",
            "generalDetails": {"title": "Old", "images": ["a.jpg"]},
            "listings": {"ebay": {"marketplaceID": "ebay", "overrides": {"title": "Old"}}},
        }
        writes: list[list[str]] = []

        async def fake_run_ops(job, ops, **_kwargs):
            for op in ops:
                if op["op"] == "get_item":
                    return {"ok": True, "results": [{"op": "get_item", "ok": True, "item": current}]}
                if op["op"] == "update_item":
                    writes.append(sorted(op["updates"]))
            return {"ok": True, "results": []}

        async def fake_prepare(job, listing, *, provider=None, evidence="", mark=None):
            return listing, {}, None, [], []

        with patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops), \
             patch("vendoo_studio.services.vendoo_create.prepare_listing_for_vendoo", fake_prepare):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/save")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(len(writes), 2)
        self.assertTrue(all(path.startswith("generalDetails") or "." not in path for path in writes[0]))
        self.assertTrue(all(path.startswith("listings.") for path in writes[1]))
        self.assertIn("generalDetails.title", writes[0])
        self.assertIn("listings.ebay.overrides.title", writes[1])

    def test_the_write_stamps_last_saved_like_vendoos_own_save(self):
        """Vendoo's "Last Saved" reads the item's dateLastModified."""
        self.bind()
        updates: dict = {}

        async def fake_run_ops(job, ops, **_kwargs):
            if ops[0]["op"] == "get_item":
                return {"ok": True, "results": [{"op": "get_item", "item": {
                    "itemID": "itm1", "dateLastModified": 1000, "generalDetails": {"title": "Old"},
                }}]}
            updates.update(ops[0]["updates"])
            return {"ok": True, "results": [{"op": "update_item", "ok": True}]}

        async def fake_prepare(job, listing, **kwargs):
            return listing, {}, None, [], []

        with (
            patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops),
            patch("vendoo_studio.services.vendoo_create.prepare_listing_for_vendoo", fake_prepare),
            patch(
                "vendoo_studio.services.vendoo_api.build_vendoo_item",
                lambda *a, **k: ({"generalDetails": {"title": "New"}}, []),
            ),
        ):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/save")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertGreater(updates["dateLastModified"], 1000)
        self.assertEqual(res.json()["updated"], ["generalDetails.title"])
        notes = json.loads(ConversationRepo(self.db).get(self.conv.id).notes)
        self.assertEqual(notes["vendooSyncedAt"], str(updates["dateLastModified"]))

    def test_save_runs_as_a_dispatched_job_the_editor_can_poll(self):
        """Update must leave a job trail like first Send, or the button stays idle."""
        self.bind()
        steps: list[str] = []

        async def fake_prepare(job, listing, **kwargs):
            mark = kwargs.get("mark")
            if mark:
                mark("vendoo_api_specifics")
                mark("vendoo_api_fields")
                steps.extend(["vendoo_api_specifics", "vendoo_api_fields"])
            return listing, {}, None, [], []

        async def fake_run_ops(job, ops, **_kwargs):
            if ops[0]["op"] == "get_item":
                return {
                    "ok": True,
                    "results": [{
                        "op": "get_item",
                        "item": {"itemID": "itm1", "generalDetails": {"title": "Old"}},
                    }],
                }
            return {"ok": True, "results": [{"op": "update_item", "ok": True}]}

        with (
            patch("vendoo_studio.services.vendoo_create.run_ops", fake_run_ops),
            patch("vendoo_studio.services.vendoo_create.prepare_listing_for_vendoo", fake_prepare),
            patch(
                "vendoo_studio.services.vendoo_api.build_vendoo_item",
                lambda *a, **k: ({"generalDetails": {"title": "New"}}, []),
            ),
        ):
            res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/save")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(steps, ["vendoo_api_specifics", "vendoo_api_fields"])
        jobs = JobRepo(self.db).list_by_conversation(self.conv.id)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, "completed")
        self.assertEqual(jobs[0].current_step, "vendoo_api_saved")
        self.assertEqual(jobs[0].vendoo_item_id, "itm1")

    def test_names_the_live_marketplaces_to_relist(self):
        self.bind()
        res = self.save({
            "itemID": "itm1",
            "generalDetails": {"title": "Old title"},
            "listings": {
                "ebay": {"status": {"listed": True}},
                "poshmark": {"status": {"listed": True}},
                "mercari": {"status": {"listed": False}},
            },
        })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["updated"])
        self.assertEqual(body["relist_needed"], ["ebay", "poshmark"])
        # The stamp is what dates the badge: a marketplace listed before it is
        # still carrying the copy from before this write.
        conv = ConversationRepo(self.db).get(self.conv.id)
        self.assertTrue(json.loads(conv.notes)["vendooFormUpdatedAt"])

    def test_a_sold_listing_is_not_asked_to_relist(self):
        self.bind()
        res = self.save({
            "itemID": "itm1",
            "generalDetails": {"title": "Old title"},
            "listings": {
                "ebay": {"status": {"listed": True, "sold": True}},
                "depop": {"status": {"listed": True}},
            },
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["relist_needed"], ["depop"])

    def test_remembers_the_marketplaces_across_the_delist(self):
        """Delist Item clears the live flags; the reminder must outlive them."""
        self.bind()
        self.save({
            "itemID": "itm1",
            "generalDetails": {"title": "Old title"},
            "listings": {"ebay": {"status": {"listed": True}}, "depop": {"status": {"listed": True}}},
        })
        notes = json.loads(ConversationRepo(self.db).get(self.conv.id).notes)
        self.assertEqual(notes["vendooRelistPending"], ["depop", "ebay"])

    def test_a_second_write_keeps_the_marketplaces_already_owed(self):
        """Editing again mid-delist must not forget what is still down."""
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {
            "vendooItemId": "itm1", "vendooRelistPending": ["poshmark"],
        })
        self.db.commit()
        self.save({
            "itemID": "itm1",
            "generalDetails": {"title": "Old title"},
            "listings": {"ebay": {"status": {"listed": True}}},
        })
        notes = json.loads(ConversationRepo(self.db).get(self.conv.id).notes)
        self.assertEqual(notes["vendooRelistPending"], ["ebay", "poshmark"])

    def test_the_write_leaves_studio_level_with_vendoo(self):
        """Otherwise the next sync reads our own write as Vendoo moving.

        That would pull the write back over the seller's next edit, and the
        "unsent edits" chip never clears.
        """
        self.bind()
        revision_id = ListingRepo(self.db).get_revisions(self.conv.id)[0].id
        res = self.save({
            "itemID": "itm1",
            "dateLastModified": 1000,
            "generalDetails": {"title": "Old title"},
            "listings": {"ebay": {"status": {"listed": True}}},
        })
        self.assertEqual(res.status_code, 200, res.text)
        notes = json.loads(ConversationRepo(self.db).get(self.conv.id).notes)
        self.assertEqual(notes["vendooSyncedRevision"], revision_id)
        # Stamped from the write, not from the item as it was read.
        self.assertNotEqual(notes["vendooSyncedAt"], "1000")

    def test_relist_done_drops_the_reminder(self):
        conv = ConversationRepo(self.db).get(self.conv.id)
        conv.notes = merge_notes(conv.notes, {
            "vendooItemId": "itm1",
            "vendooFormUpdatedAt": "2026-09-18T00:00:00+00:00",
            "vendooRelistPending": ["ebay"],
        })
        self.db.commit()
        res = self.client.post(f"/api/conversations/{self.conv.id}/vendoo-api/relist-done")
        self.assertEqual(res.status_code, 200, res.text)
        notes = json.loads(ConversationRepo(self.db).get(self.conv.id).notes)
        # Both stamps go, or the live listings alone would re-derive the badge.
        self.assertEqual(notes["vendooRelistPending"], [])
        self.assertEqual(notes["vendooFormUpdatedAt"], "")

    def test_nothing_to_write_leaves_the_stamp_alone(self):
        """No write means no new copy waiting on a relist."""
        self.bind()
        res = self.save({
            "itemID": "itm1",
            "generalDetails": {"title": "Levi's 501"},
            "listings": {
                "ebay": {"status": {"listed": True}, "overrides": {"title": "Levi's 501"}},
            },
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["updated"], [])
        self.assertEqual(res.json()["relist_needed"], [])
        conv = ConversationRepo(self.db).get(self.conv.id)
        self.assertNotIn("vendooFormUpdatedAt", json.loads(conv.notes or "{}"))


if __name__ == "__main__":
    unittest.main()
