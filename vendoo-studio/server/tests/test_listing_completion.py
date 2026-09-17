from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategoryNode, CategorySchema
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.category_catalog import remember_schema
from vendoo_studio.services.completion_readback import MAX_CATEGORY_REPAIRS, MAX_READBACK_RETRIES, categories_match
from vendoo_studio.services.listing_completion import MAX_REPAIR_ROUNDS, complete_job, store_verification
from vendoo_studio.services.completion_gaps import adopt_observed_draft_values, deterministic_gap_patches, drop_noop_gaps, gap_already_has_value, prefer_listing_over_observed, prior_fill_covers_empty_gap, review_fields
from vendoo_studio.services.fill_log import listing_value_for_field, write_values_into_listing
from vendoo_studio.services.schema_probe import SCHEMA_PROBE_FLAG, prepare_generation_schema
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401


class Provider:
    def __init__(self, result):
        self.result = result
        self.messages = []

    async def chat(self, messages, stream=True):
        self.messages = messages
        yield json.dumps(self.result)


class CompletionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.conv = ConversationRepo(self.db).create(title="Tee")
        self.listing = {"title": "Tee", "category_path": "Clothing > Tops", "platforms": ["ebay"], "ebay_specifics": {}}
        self.revision = ListingRepo(self.db).save_revision(self.conv.id, self.listing, source="model")
        self.job = JobRepo(self.db).create(conv_id=self.conv.id, approved_revision_id=self.revision.id,
            listing_snapshot=self.listing, status="dispatched", vendoo_item_id="saved-123")
        self.verification = {"readback": True, "verified": True, "schema": {
            "general": {"category": {"path": "Clothing > Tops"}, "fields": [{"label": "Title", "value": "Tee", "required": True}]},
            "ebay": {"category": {"path": "Clothing > Shirts"}, "fields": [{"label": "Material", "value": "", "required": True, "selector": "#material"}]},
        }}
        self.manager_patch = patch("vendoo_studio.routes.extension.extension_manager")
        self.manager = self.manager_patch.start()
        self.manager.connected = True
        self.dispatch_patch = patch("vendoo_studio.routes.extension.dispatch_fill_fields", new_callable=AsyncMock)
        self.dispatch = self.dispatch_patch.start()
        self.dispatch.return_value = True

    def tearDown(self):
        self.dispatch_patch.stop()
        self.manager_patch.stop()
        self.db.close()
        self.engine.dispose()

    def review(self):
        store_verification(self.db, self.job, self.verification)

    async def run_completion(self, result):
        provider = Provider(result)
        with patch("vendoo_studio.services.listing_completion.get_listing_provider", return_value=provider):
            await complete_job(self.db, self.job.id)
        self.db.refresh(self.job)
        return provider

    async def test_repair_then_readback_completes(self):
        ConversationRepo(self.db).add_message(self.conv.id, "user", "The tag says 100% cotton.")
        self.review()
        await self.run_completion({"fields": [{"marketplace": "ebay", "field": "Material", "value": "Cotton", "evidence": "100% cotton"}]})
        self.assertEqual(self.job.current_step, "filling_fields")
        self.assertEqual(self.job.status, "dispatched")
        self.assertEqual(self.dispatch.await_args.args[1][0]["value"], "Cotton")
        self.assertEqual(self.dispatch.await_args.args[1][0]["selector"], "#material")
        self.verification["schema"]["ebay"]["fields"][0]["value"] = "Cotton"
        self.review()
        await self.run_completion({})
        self.assertEqual(self.job.current_step, "verified_complete")
        self.assertEqual(self.job.status, "completed")
        self.assertEqual(self.dispatch.await_count, 1)

    async def test_unknown_fact_is_marked_no_evidence_without_asking(self):
        self.review()
        await self.run_completion({"fields": [{"marketplace": "ebay", "field": "Material", "value": "Cotton"}],
                                   "questions": ["What material is listed on the tag?"]})
        self.assertEqual(self.job.current_step, "verified_complete")
        self.assertEqual(self.job.status, "completed")
        self.assertIsNone(self.job.last_error)
        self.dispatch.assert_not_awaited()
        event = JobRepo(self.db).latest_event(self.job.id, "completion_no_evidence")
        self.assertIsNotNone(event)
        fields = (event.payload or {}).get("fields") or []
        self.assertEqual(fields[0]["field"], "Material")
        self.assertEqual(fields[0]["reason"], "No evidence")
        self.assertNotIn("?", " ".join(str(field.get("reason") or "") for field in fields))

    async def test_model_no_evidence_completes_required_gap(self):
        self.review()
        await self.run_completion({
            "no_evidence": [{"marketplace": "ebay", "field": "Material", "reason": "Tag not visible"}],
        })
        self.assertEqual(self.job.current_step, "verified_complete")
        self.assertEqual(self.job.status, "completed")
        self.dispatch.assert_not_awaited()
        event = JobRepo(self.db).latest_event(self.job.id, "completion_no_evidence")
        self.assertEqual((event.payload or {}).get("fields")[0]["reason"], "Tag not visible")

    async def test_optional_does_not_apply_value_is_filled(self):
        self.verification["schema"]["ebay"]["fields"] = [{
            "label": "Character",
            "value": "",
            "required": False,
            "selector": "#character",
            "options": [{"label": "Does Not Apply"}, {"label": "Mickey"}],
            "options_complete": True,
            "error": "Empty field",
        }]
        ConversationRepo(self.db).add_message(self.conv.id, "user", "No character print.")
        self.review()
        await self.run_completion({
            "fields": [{
                "marketplace": "ebay",
                "field": "Character",
                "value": "Does Not Apply",
                "evidence": "No character print",
            }],
        })
        self.assertEqual(self.job.current_step, "filling_fields")
        self.assertEqual(self.dispatch.await_args.args[1][0]["value"], "Does Not Apply")

    async def test_shipping_weight_estimate_is_applied_without_photo_quote(self):
        self.verification["schema"]["general"] = {
            "category": {"path": "Clothing > Tops"},
            "fields": [
                {"label": "Title", "value": "Tee", "required": True},
                {"label": "Weight (oz)", "value": "", "required": True, "selector": "#weightOz"},
            ],
        }
        self.verification["schema"]["ebay"]["fields"][0]["value"] = "Cotton"
        self.review()
        await self.run_completion({
            "fields": [{
                "marketplace": "general",
                "field": "Weight (oz)",
                "value": "10",
                "evidence": "estimated packaged weight for graphic tee",
            }],
            "questions": ["Please confirm the packaged shipping weight in pounds and ounces."],
        })
        self.assertEqual(self.job.current_step, "filling_fields")
        self.assertEqual(self.dispatch.await_args.args[1][0]["value"], "10")
        self.assertEqual(str(self.job.listing_snapshot.get("weight_oz")), "10")

    async def test_shipping_weight_questions_are_not_asked_to_seller(self):
        self.verification["schema"]["general"] = {
            "category": {"path": "Clothing > Tops"},
            "fields": [
                {"label": "Title", "value": "Tee", "required": True},
                {"label": "Weight (oz)", "value": "", "required": True},
            ],
        }
        self.verification["schema"]["ebay"]["fields"][0]["value"] = "Cotton"
        self.review()
        await self.run_completion({
            "questions": ["Please confirm the packaged shipping weight in pounds and ounces."],
        })
        self.assertEqual(self.job.current_step, "completion_blocked")
        self.assertNotEqual(self.job.current_step, "awaiting_answers")
        self.assertNotIn("confirm", (self.job.last_error or "").casefold())
        self.dispatch.assert_not_awaited()

    async def test_unresolved_gap_is_recorded_as_no_evidence_once(self):
        self.review()
        await self.run_completion({"questions": ["What material is listed on the tag?"]})
        self.assertEqual(self.job.current_step, "verified_complete")
        event = JobRepo(self.db).latest_event(self.job.id, "completion_no_evidence")
        self.assertEqual(len((event.payload or {}).get("fields") or []), 1)
        # Second pass keeps the same disposition without another fill attempt.
        await self.run_completion({"questions": ["What material is listed on the tag?"]})
        self.assertEqual(self.job.current_step, "verified_complete")
        self.dispatch.assert_not_awaited()
        events = [e for e in JobRepo(self.db).get_events(self.job.id) if e.event_type == "completion_no_evidence"]
        self.assertGreaterEqual(len(events), 1)

    async def test_answer_resumes_and_only_patches_gap(self):
        self.review()
        await self.run_completion({"no_evidence": [{"marketplace": "ebay", "field": "Material", "reason": "No tag visible"}]})
        self.assertEqual(self.job.current_step, "verified_complete")
        ConversationRepo(self.db).add_message(self.conv.id, "user", "It is linen.")
        # Clear prior no-evidence so a later resume can fill from new seller evidence.
        JobRepo(self.db).add_event(self.job.id, "completion_no_evidence", None, {"fields": []})
        self.job.status = "dispatched"
        self.job.current_step = "verifying_draft"
        self.db.commit()
        self.review()
        await self.run_completion({"fields": [
            {"marketplace": "ebay", "field": "Material", "value": "Linen", "evidence": "linen"},
            {"marketplace": "general", "field": "Title", "value": "Changed", "evidence": "linen"},
        ]})
        self.assertEqual(len(self.dispatch.await_args.args[1]), 1)
        self.assertEqual(self.job.listing_snapshot["title"], "Tee")

    async def test_new_conditional_field_is_marked_no_evidence(self):
        self.verification["schema"]["ebay"]["fields"][0]["value"] = "Cotton"
        self.verification["schema"]["ebay"]["fields"].append({"label": "Fabric type", "value": ""})
        self.review()
        await self.run_completion({"questions": ["What fabric type?"]})
        self.assertEqual(self.job.current_step, "verified_complete")
        event = JobRepo(self.db).latest_event(self.job.id, "completion_no_evidence")
        self.assertEqual((event.payload or {}).get("fields")[0]["field"], "Fabric type")

    async def test_identical_failed_attempt_is_not_repeated(self):
        self.listing["ebay_specifics"]["Material"] = "Cotton"
        ListingRepo(self.db).save_revision(self.conv.id, self.listing, source="user")
        self.review()
        result = {"fields": [{"marketplace": "ebay", "field": "Material", "value": "Cotton"}]}
        await self.run_completion(result)
        self.review()
        await self.run_completion(result)
        self.assertEqual(self.dispatch.await_count, 1)
        self.assertEqual(self.job.current_step, "verified_complete")
        event = JobRepo(self.db).latest_event(self.job.id, "completion_no_evidence")
        self.assertEqual((event.payload or {}).get("fields")[0]["field"], "Material")

    async def test_schedule_completion_runs_follow_up_after_in_flight_task(self):
        import asyncio
        import vendoo_studio.services.listing_completion as completion

        started = asyncio.Event()
        release = asyncio.Event()
        calls = {"n": 0}

        async def slow_complete(db, job_id):
            calls["n"] += 1
            started.set()
            await release.wait()

        with patch.object(completion, "complete_job", side_effect=slow_complete):
            completion.schedule_completion(self.job.id)
            await asyncio.wait_for(started.wait(), timeout=1)
            completion.schedule_completion(self.job.id)
            self.assertIn(self.job.id, completion._pending_completion)
            release.set()
            await asyncio.wait_for(completion._tasks[self.job.id], timeout=1)
            for _ in range(50):
                if calls["n"] >= 2:
                    break
                await asyncio.sleep(0.01)
        self.assertGreaterEqual(calls["n"], 2)
        self.assertNotIn(self.job.id, completion._pending_completion)

    async def test_empty_or_partial_readback_retries_then_pauses(self):
        del self.verification["schema"]["ebay"]
        self.review()
        with patch("vendoo_studio.services.completion_readback.READBACK_RETRY_DELAY_SECONDS", 0):
            await self.run_completion({})
        self.assertEqual(self.job.current_step, "verifying_draft")
        self.assertEqual(self.job.status, "dispatched")
        self.dispatch.assert_awaited_once()
        kwargs = self.dispatch.await_args.kwargs
        # Keep the open draft tab; a full reload races SPA hydration on verify-only retries.
        self.assertFalse(kwargs.get("reload"))
        self.assertIn("ebay", kwargs.get("platforms") or [])
        self.assertTrue(any(
            event.event_type == "completion_readback_retry"
            for event in JobRepo(self.db).get_events(self.job.id)
        ))

        for _ in range(MAX_READBACK_RETRIES - 1):
            self.review()
            with patch("vendoo_studio.services.completion_readback.READBACK_RETRY_DELAY_SECONDS", 0):
                await complete_job(self.db, self.job.id)
            self.db.refresh(self.job)

        self.review()
        with patch("vendoo_studio.services.completion_readback.READBACK_RETRY_DELAY_SECONDS", 0):
            await complete_job(self.db, self.job.id)
        self.db.refresh(self.job)
        self.assertEqual(self.job.current_step, "completion_blocked")
        self.assertIn("automatic retries", self.job.last_error or "")
        self.assertEqual(self.dispatch.await_count, MAX_READBACK_RETRIES)

    async def test_partial_readback_merges_prior_marketplace_schema(self):
        self.review()
        # Later attempt only recovers eBay; general came from the first review.
        store_verification(self.db, self.job, {
            "readback": True,
            "verified": False,
            "schema": {
                "ebay": {
                    "category": {"path": "Clothing > Shirts"},
                    "fields": [{"label": "Material", "value": "Cotton", "required": True}],
                },
            },
        })
        self.verification["schema"]["ebay"]["fields"][0]["value"] = "Cotton"
        await self.run_completion({})
        self.assertEqual(self.job.current_step, "verified_complete")
        self.dispatch.assert_not_awaited()

    async def test_required_field_cannot_be_exempted_as_does_not_apply(self):
        ConversationRepo(self.db).add_message(self.conv.id, "user", "It has no material tag.")
        self.review()
        await self.run_completion({"not_applicable": [{"marketplace": "ebay", "field": "Material",
            "reason": "No tag", "evidence": "no material tag"}]})
        # Required fields cannot be Does Not Apply; they fall through to No evidence.
        self.assertEqual(self.job.current_step, "verified_complete")
        self.assertIsNone(JobRepo(self.db).latest_event(self.job.id, "completion_not_applicable"))
        event = JobRepo(self.db).latest_event(self.job.id, "completion_no_evidence")
        self.assertEqual((event.payload or {}).get("fields")[0]["field"], "Material")

    async def test_optional_exemption_fills_does_not_apply(self):
        self.verification["schema"]["ebay"]["fields"] = [{"label": "Theme", "value": "", "required": False, "selector": "#theme"}]
        ConversationRepo(self.db).add_message(self.conv.id, "user", "No theme print on this plain top.")
        self.review()
        await self.run_completion({"not_applicable": [{"marketplace": "ebay", "field": "Theme",
            "reason": "No theme", "evidence": "No theme print"}]})
        self.assertEqual(self.job.current_step, "filling_fields")
        self.assertEqual(self.dispatch.await_args.args[1][0]["field"], "Theme")
        self.assertEqual(self.dispatch.await_args.args[1][0]["value"], "Does Not Apply")

    async def test_sleeveless_fills_sleeve_length_not_dna(self):
        self.verification["schema"]["ebay"]["fields"] = [{
            "label": "Sleeve length",
            "value": "",
            "required": False,
            "selector": "#sleeve",
            "error": "Empty field",
        }]
        self.job.listing_snapshot = {
            **(self.job.listing_snapshot or {}),
            "title": "Tank Top Sleeveless",
            "ebay_specifics": {
                **((self.job.listing_snapshot or {}).get("ebay_specifics") or {}),
                "type": "Tank",
            },
        }
        ListingRepo(self.db).save_revision(self.conv.id, self.job.listing_snapshot, source="completion")
        self.review()
        await self.run_completion({})
        self.assertEqual(self.job.current_step, "filling_fields")
        self.assertEqual(self.dispatch.await_args.args[1][0]["field"], "Sleeve length")
        self.assertEqual(self.dispatch.await_args.args[1][0]["value"], "Sleeveless")

    async def test_invalid_closed_option_becomes_no_evidence(self):
        field = self.verification["schema"]["ebay"]["fields"][0]
        field.update(options=[{"label": "Wool", "value": "wool-id"}], options_complete=True)
        ConversationRepo(self.db).add_message(self.conv.id, "user", "The tag says cotton.")
        self.review()
        await self.run_completion({"fields": [{"marketplace": "ebay", "field": "Material", "value": "Cotton", "evidence": "cotton"}]})
        self.dispatch.assert_not_awaited()
        self.assertEqual(self.job.current_step, "verified_complete")
        event = JobRepo(self.db).latest_event(self.job.id, "completion_no_evidence")
        self.assertEqual((event.payload or {}).get("fields")[0]["field"], "Material")

    async def test_repair_prompt_strips_bulky_option_objects(self):
        field = self.verification["schema"]["ebay"]["fields"][0]
        field.update(
            options=[{"label": f"Opt {i}", "value": f"id-{i}", "meta": "x" * 200} for i in range(80)],
            options_complete=True,
            selector="#material",
            error="Empty field",
        )
        ConversationRepo(self.db).add_message(self.conv.id, "user", "The tag says 100% cotton.")
        self.review()
        provider = await self.run_completion({
            "fields": [{"marketplace": "ebay", "field": "Material", "value": "Opt 0", "evidence": "100% cotton"}],
        })
        payload = json.loads(provider.messages[-1]["content"])
        gap = payload["gaps"][0]
        self.assertEqual(gap["field"], "Material")
        self.assertNotIn("selector", gap)
        self.assertNotIn("meta", json.dumps(gap))
        self.assertEqual(len(gap["options"]), 40)
        self.assertEqual(gap["options"][0], "Opt 0")
        self.assertNotIn("options_complete", gap)

    async def test_repair_timeout_pauses_with_clear_error(self):
        class SlowProvider:
            async def chat(self, messages, stream=True):
                await asyncio.sleep(3600)
                yield "{}"

        self.review()
        with (
            patch("vendoo_studio.services.listing_completion.get_listing_provider", return_value=SlowProvider()),
            patch("vendoo_studio.services.listing_completion.resolution_timeout_seconds", return_value=0.01),
        ):
            await complete_job(self.db, self.job.id)
        self.db.refresh(self.job)
        self.assertEqual(self.job.current_step, "completion_blocked")
        self.assertIn("timed out", self.job.last_error)
        self.dispatch.assert_not_awaited()

    async def test_model_cannot_request_publishing(self):
        self.verification["schema"]["ebay"]["fields"] = [{"label": "Listing State", "value": ""}]
        self.review()
        ConversationRepo(self.db).add_message(self.conv.id, "user", "Active Listing")
        await self.run_completion({"fields": [{"marketplace": "ebay", "field": "Listing State",
            "value": "Active Listing", "evidence": "Active Listing"}]})
        self.dispatch.assert_not_awaited()

    async def test_round_limit_marks_remaining_as_no_evidence(self):
        for _ in range(MAX_REPAIR_ROUNDS):
            JobRepo(self.db).add_event(self.job.id, "completion_attempt", None, {"fields": []})
        self.review()
        await self.run_completion({})
        self.assertEqual(self.job.current_step, "verified_complete")
        event = JobRepo(self.db).latest_event(self.job.id, "completion_no_evidence")
        self.assertEqual((event.payload or {}).get("fields")[0]["field"], "Material")

    async def test_changed_category_auto_repairs_then_pauses(self):
        ListingRepo(self.db).save_revision(self.conv.id, {**self.listing, "category_path": "Clothing > Dresses"}, source="user")
        self.review()
        await self.run_completion({})
        self.assertEqual(self.job.current_step, "filling_fields")
        self.dispatch.assert_awaited_once()
        patches = self.dispatch.await_args.args[1]
        self.assertEqual(patches[0]["field"], "Category")
        self.assertEqual(patches[0]["value"], "Clothing > Dresses")

        for _ in range(MAX_CATEGORY_REPAIRS - 1):
            self.review()
            await complete_job(self.db, self.job.id)
            self.db.refresh(self.job)
        self.review()
        await complete_job(self.db, self.job.id)
        self.db.refresh(self.job)
        self.assertEqual(self.job.current_step, "completion_blocked")
        self.assertIn("automatic repair", self.job.last_error or "")
        self.assertEqual(self.dispatch.await_count, MAX_CATEGORY_REPAIRS)

    async def test_marketplace_category_mismatch_auto_repairs(self):
        ListingRepo(self.db).save_revision(self.conv.id, {
            **self.listing,
            "marketplace_categories": {"ebay": "Clothing > Dresses"},
        }, source="user")
        self.review()
        await self.run_completion({})
        self.assertEqual(self.job.current_step, "filling_fields")
        patch = self.dispatch.await_args.args[1][0]
        self.assertEqual(patch["marketplace"], "ebay")
        self.assertEqual(patch["field"], "Category")
        self.assertEqual(patch["value"], "Clothing > Dresses")

    def test_category_breadcrumb_separators_and_blouse_leaf_match(self):
        self.assertTrue(categories_match(
            "Women ‣ Tops & Blouses ‣ Blouse",
            "Women > Tops & Blouses > Blouse",
        ))
        self.assertTrue(categories_match(
            "Women > Tops & Blouses > Blouses",
            "Women > Tops & Blouses > Blouse",
        ))
        self.assertFalse(categories_match(
            "Women ‣ Tops & Blouses ‣ T-Shirts",
            "Women > Tops & Blouses > Blouse",
        ))
        self.assertFalse(categories_match("", "Women > Tops & Blouses > Blouse"))

    def test_mapped_marketplace_value_is_not_a_false_gap(self):
        self.verification["schema"]["ebay"]["fields"] = [{"label": "Condition", "value": "Good",
            "expected_input": "Pre-Owned - Good", "expected": "Good", "matches_expected": True}]
        self.assertEqual(review_fields(self.verification, {**self.listing, "condition": "Pre-Owned - Good"}), [])
        # A stale mapping must not conceal a newer seller edit.
        self.assertEqual(len(review_fields(self.verification, {**self.listing, "condition": "New With Tags/Box"})), 1)

    def test_review_fields_ignores_shipping_and_policy_rows(self):
        self.verification["schema"]["etsy"] = {"category": {"path": "Clothing > Tops"}, "fields": [
            {"label": "Shipping Profile", "value": "", "required": True, "selector": "#shipping"},
            {"label": "Return Policy", "value": "", "required": True, "selector": "#returns"},
        ]}
        self.verification["schema"]["depop"] = {"category": {"path": "Women > Tops"}, "fields": [
            {"label": "Parcel Size", "value": "", "required": True, "selector": "#parcel"},
            {"label": "Return Policy", "value": "", "required": True, "selector": "#depop-returns"},
        ]}
        gaps = review_fields(self.verification, self.listing)
        labels = {(gap["marketplace"], gap["field"]) for gap in gaps}
        self.assertNotIn(("etsy", "Shipping Profile"), labels)
        self.assertNotIn(("etsy", "Return Policy"), labels)
        self.assertNotIn(("depop", "Return Policy"), labels)
        self.assertIn(("depop", "Parcel Size"), labels)

    def test_review_fields_skips_when_observed_matches_mapped_display(self):
        self.verification["schema"]["ebay"]["fields"] = [{
            "label": "Condition",
            "value": "Good",
            "expected_input": "Pre-Owned - Good",
            "expected": "Good",
            "matches_expected": True,
        }]
        gaps = review_fields(self.verification, {**self.listing, "condition": "Pre-Owned - Good"})
        self.assertEqual(gaps, [])

    def test_gap_already_has_value_and_prior_fill_skip_noop_refill(self):
        gap = {
            "marketplace": "ebay",
            "field": "Material",
            "expected": "Cotton",
            "mapped_expected": "Cotton",
            "observed": "Cotton",
            "error": "Saved value differs",
        }
        self.assertTrue(gap_already_has_value(gap, "Cotton"))
        self.assertFalse(gap_already_has_value({**gap, "observed": ""}, "Cotton"))

        empty = {
            "marketplace": "ebay",
            "field": "Material",
            "expected": "Cotton",
            "observed": "",
            "error": "Empty field",
        }
        self.db.add(FillLogEntry(
            job_id=self.job.id,
            conversation_id=self.conv.id,
            step="filling_ebay",
            marketplace="ebay",
            field="Material",
            status="filled",
            reason="",
            value_preview="Cotton",
        ))
        self.db.commit()
        self.assertTrue(prior_fill_covers_empty_gap(self.db, self.job, empty, "Cotton"))
        self.assertEqual(drop_noop_gaps(self.db, self.job, [empty, gap], self.listing), [])

        ready, needs = deterministic_gap_patches([gap], self.listing)
        self.assertEqual(ready, [])
        self.assertEqual(needs, [])

    async def test_complete_job_skips_refill_when_fill_log_already_wrote_value(self):
        self.db.add(FillLogEntry(
            job_id=self.job.id,
            conversation_id=self.conv.id,
            step="filling_ebay",
            marketplace="ebay",
            field="Material",
            status="filled",
            reason="",
            value_preview="Cotton",
        ))
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {**self.listing, "ebay_specifics": {"material": "Cotton"}},
            source="model",
        )
        self.job.listing_snapshot = {**self.listing, "ebay_specifics": {"material": "Cotton"}}
        self.db.commit()
        self.review()
        await self.run_completion({})
        self.dispatch.assert_not_awaited()
        self.assertEqual(self.job.status, "completed")
        self.assertEqual(self.job.current_step, "verified_complete")

    def test_adopt_observed_size_unless_user_form_is_newest(self):
        listing = {
            **self.listing,
            "size": "approx 10",
            "ebay_specifics": {"size": "approx 10"},
        }
        verification = {
            "schema": {
                "general": {"fields": [{"label": "Size", "value": "10"}]},
                "ebay": {"fields": [{"label": "Size", "value": "10"}]},
            }
        }
        updated, patches = adopt_observed_draft_values(
            listing, verification, prefer_listing=False,
        )
        self.assertEqual(len(patches), 2)
        self.assertEqual(updated["size"], "10")
        self.assertEqual(updated["ebay_specifics"]["size"], "10")
        self.assertEqual(
            review_fields(verification, updated),
            [],
        )

        kept, none = adopt_observed_draft_values(
            listing, verification, prefer_listing=True,
        )
        self.assertEqual(none, [])
        self.assertEqual(kept["size"], "approx 10")
        self.assertTrue(prefer_listing_over_observed([
            type("Rev", (), {"source": "user_form"})(),
        ]))
        self.assertFalse(prefer_listing_over_observed([
            type("Rev", (), {"source": "model"})(),
        ]))

    async def test_complete_job_adopts_observed_instead_of_refilling(self):
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {**self.listing, "size": "approx 10", "ebay_specifics": {"size": "approx 10"}},
            source="model",
        )
        self.verification = {
            "readback": True,
            "verified": True,
            "schema": {
                "general": {
                    "category": {"path": "Clothing > Tops"},
                    "fields": [
                        {"label": "Title", "value": "Tee", "required": True},
                        {"label": "Size", "value": "10"},
                    ],
                },
                "ebay": {
                    "category": {"path": "Clothing > Shirts"},
                    "fields": [{"label": "Size", "value": "10"}],
                },
            },
        }
        self.review()
        provider = await self.run_completion({})
        self.assertEqual(self.job.status, "completed")
        self.assertEqual(self.job.current_step, "verified_complete")
        self.assertEqual(provider.messages, [])
        latest = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        self.assertEqual(latest.source, "vendoo_observed")
        self.assertEqual(latest.listing_json["size"], "10")
        self.assertEqual(latest.listing_json["ebay_specifics"]["size"], "10")

    async def test_complete_job_keeps_user_form_size_and_refills(self):
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {**self.listing, "size": "12", "ebay_specifics": {"size": "12"}},
            source="user_form",
        )
        self.verification = {
            "readback": True,
            "verified": True,
            "schema": {
                "general": {
                    "category": {"path": "Clothing > Tops"},
                    "fields": [
                        {"label": "Title", "value": "Tee", "required": True},
                        {"label": "Size", "value": "10"},
                    ],
                },
                "ebay": {
                    "category": {"path": "Clothing > Shirts"},
                    "fields": [
                        {"label": "Size", "value": "10"},
                        {"label": "Material", "value": "", "required": True, "selector": "#material"},
                    ],
                },
            },
        }
        self.review()
        await self.run_completion({
            "fields": [
                {"marketplace": "general", "field": "Size", "value": "12", "evidence": "seller form"},
                {"marketplace": "ebay", "field": "Size", "value": "12", "evidence": "seller form"},
                {"marketplace": "ebay", "field": "Material", "value": "Cotton", "evidence": "tag"},
            ]
        })
        self.assertEqual(self.job.current_step, "filling_fields")
        latest = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        self.assertNotEqual(latest.source, "vendoo_observed")
        self.assertEqual(latest.listing_json.get("size"), "12")

    async def test_known_listing_values_skip_model_pass(self):
        ListingRepo(self.db).save_revision(
            self.conv.id,
            {**self.listing, "ebay_specifics": {"material": "Cotton"}},
            source="model",
        )
        self.verification["schema"]["ebay"]["fields"] = [
            {"label": "Material", "value": "", "required": True, "selector": "#material"},
        ]
        self.review()
        provider = await self.run_completion({
            "fields": [{"marketplace": "ebay", "field": "Material", "value": "Silk", "evidence": "wrong"}],
        })
        self.assertEqual(self.job.current_step, "filling_fields")
        self.assertEqual(provider.messages, [])
        self.dispatch.assert_awaited_once()
        patches = self.dispatch.await_args.args[1]
        self.assertEqual(patches, [{
            "marketplace": "ebay",
            "field": "Material",
            "selector": "#material",
            "value": "Cotton",
        }])

    def test_deterministic_gap_patches_split(self):
        ready, needs = deterministic_gap_patches(
            [
                {"marketplace": "ebay", "field": "Material", "expected": "Cotton", "error": "Empty field"},
                {"marketplace": "ebay", "field": "Pattern", "expected": "", "error": "Empty field"},
                {"marketplace": "ebay", "field": "Size", "expected": "approx 10", "error": "Invalid option"},
            ],
            {"size": "10", "ebay_specifics": {"material": "Cotton"}},
        )
        self.assertEqual([patch["field"] for patch in ready], ["Material", "Pattern"])
        self.assertEqual(ready[1]["value"], "Solid")
        self.assertEqual([gap["field"] for gap in needs], ["Size"])

    def test_unlisted_brand_uses_depop_other_and_mercari_no_brand(self):
        gaps = [
            {
                "marketplace": "depop",
                "field": "Brand",
                "error": "Empty field",
                "options": ["Nike", "Adidas", "Other"],
                "options_complete": True,
            },
            {
                "marketplace": "mercari",
                "field": "Brand",
                "error": "Empty field",
                "options": ["Nike", "Adidas"],
                "options_complete": True,
            },
        ]
        ready, needs = deterministic_gap_patches(gaps, {"brand": "Wren & Glory"})
        self.assertEqual(needs, [])
        self.assertEqual(
            [(patch["marketplace"], patch["value"]) for patch in ready],
            [("depop", "Other"), ("mercari", "No Brand/Not sure")],
        )

    def test_listed_brand_is_not_replaced_by_a_fallback(self):
        gaps = [
            {"marketplace": "depop", "field": "Brand", "error": "Empty field",
             "options": ["Nike", "Other"], "options_complete": True},
            # Unknown option list: send the real brand and let the filler decide.
            {"marketplace": "mercari", "field": "Brand", "error": "Empty field"},
        ]
        ready, needs = deterministic_gap_patches(gaps, {"brand": "Nike"})
        self.assertEqual(needs, [])
        self.assertEqual([patch["value"] for patch in ready], ["Nike", "Nike"])

    def test_brand_fallback_on_draft_is_not_a_gap(self):
        self.verification["schema"] = {
            "depop": {"fields": [{"label": "Brand", "value": "Other", "required": True}]},
            "mercari": {"fields": [
                {"label": "Brand", "value": "", "required": True},
                {"label": "No Brand/Not sure", "value": True},
            ]},
        }
        listing = {**self.listing, "brand": "Wren & Glory"}
        self.assertEqual(review_fields(self.verification, listing), [])

        # Mercari's brand stays a gap while the No Brand box is still unchecked.
        self.verification["schema"]["mercari"]["fields"][1]["value"] = False
        gaps = review_fields(self.verification, listing)
        self.assertEqual([(gap["marketplace"], gap["field"]) for gap in gaps], [("mercari", "Brand")])

    def test_depop_other_does_not_hide_a_brand_depop_carries(self):
        self.verification["schema"] = {"depop": {"fields": [{
            "label": "Brand",
            "value": "Other",
            "required": True,
            "options": ["Nike", "Other"],
            "options_complete": True,
        }]}}
        gaps = review_fields(self.verification, {**self.listing, "brand": "Nike"})
        self.assertEqual([gap["field"] for gap in gaps], ["Brand"])

    def test_ebay_must_fill_optional_blocks_silent_no_evidence(self):
        from vendoo_studio.services.listing_completion import marketplace_optional_blocks_silent_skip

        self.assertTrue(marketplace_optional_blocks_silent_skip({
            "marketplace": "ebay",
            "field": "Features",
            "error": "Empty field",
        }))
        self.assertFalse(marketplace_optional_blocks_silent_skip({
            "marketplace": "ebay",
            "field": "Material",
            "error": "Empty field",
        }))
        self.assertFalse(marketplace_optional_blocks_silent_skip({
            "marketplace": "ebay",
            "field": "Theme",
            "error": "Empty field",
        }))
        self.assertTrue(marketplace_optional_blocks_silent_skip({
            "marketplace": "etsy",
            "field": "Clothing style",
            "error": "Empty field",
        }))
        self.assertFalse(marketplace_optional_blocks_silent_skip({
            "marketplace": "etsy",
            "field": "Holiday",
            "error": "Empty field",
        }))
        self.assertTrue(marketplace_optional_blocks_silent_skip({
            "marketplace": "depop",
            "field": "Occasion",
            "error": "Empty field",
        }))
        self.assertFalse(marketplace_optional_blocks_silent_skip({
            "marketplace": "depop",
            "field": "Size Grouping",
            "error": "Empty field",
        }))
        self.assertFalse(marketplace_optional_blocks_silent_skip({
            "marketplace": "depop",
            "field": "Material",
            "error": "Empty field",
        }))

    def test_patch_updates_existing_camel_case_key_and_package_measurements(self):
        result = write_values_into_listing({"ebay_specifics": {"fabricType": ""}, "package_dimensions_in": "13x10x3"}, [
            {"marketplace": "ebay", "field": "Fabric Type", "value": "Jersey"},
            {"marketplace": "general", "field": "Length", "value": "14"},
            {"marketplace": "general", "field": "Weight (oz)", "value": "9"},
        ])
        self.assertEqual(result["ebay_specifics"], {"fabricType": "Jersey"})
        self.assertEqual(result["package_dimensions_in"], "14x10x3")
        self.assertEqual(listing_value_for_field(result, "general", "Weight (oz)"), "9")

    def test_missing_shipping_measurements_stay_unknown(self):
        from vendoo_studio.models.schema import ListingSchema
        listing = ListingSchema(title="Tee", description="Cotton tee", price=12)
        self.assertIsNone(listing.weight_oz)
        self.assertIsNone(listing.package_dimensions_in)

    async def test_probe_never_enters_fill_loop(self):
        self.job.listing_snapshot = {**self.listing, SCHEMA_PROBE_FLAG: True}
        self.db.commit()
        self.review()
        await self.run_completion({})
        self.dispatch.assert_not_awaited()

    async def test_cancelled_job_never_resumes(self):
        self.job.status = "cancelled"
        self.db.commit()
        self.review()
        await self.run_completion({})
        self.assertEqual(self.job.status, "cancelled")
        self.dispatch.assert_not_awaited()

    def test_false_zero_and_rejected_values(self):
        fields = self.verification["schema"]["ebay"]["fields"]
        fields[:] = [{"label": "Handmade", "value": False}, {"label": "Cost", "value": 0},
                     {"label": "Size", "value": "M", "error": "Invalid option"}]
        gaps = review_fields(self.verification, self.listing)
        self.assertEqual([field["field"] for field in gaps], ["Size"])

    def test_catalog_excludes_item_values_and_keeps_parent_paths(self):
        remember_schema(self.db, "Clothing > Tops", self.verification["schema"])
        rows = self.db.query(CategorySchema).all()
        self.assertEqual(len(rows), 2)
        self.assertNotIn("value", rows[0].fields[0])
        self.assertNotIn("selector", rows[1].fields[0])
        node = self.db.query(CategoryNode).filter_by(marketplace="general", path="Clothing > Tops").one()
        self.assertEqual(node.parent_path, "Clothing")

    async def test_generation_requires_chrome_before_full_listing(self):
        self.manager.connected = False
        self.job.status = "completed"
        self.db.commit()
        provider = Provider({})
        with patch("vendoo_studio.services.marketplaces.selected_fillable_platforms", return_value=["ebay"]), \
             patch("vendoo_studio.services.category_selection.select_categories", new=AsyncMock(
                 return_value={"general": "Clothing > Tops", "ebay": "Clothing > Shirts"})), \
             self.assertRaisesRegex(RuntimeError, "Connect Chrome"):
            await prepare_generation_schema(self.db, self.conv.id, provider, "Cotton tee", "")
        self.assertEqual(provider.messages, [])

    async def test_generation_uses_cached_schema_without_chrome(self):
        self.manager.connected = False
        remember_schema(self.db, "Clothing > Tops", self.verification["schema"])
        statuses: list[str] = []
        with patch("vendoo_studio.services.marketplaces.selected_fillable_platforms", return_value=["ebay"]), \
             patch("vendoo_studio.services.category_selection.select_categories", new=AsyncMock(
                 return_value={"general": "Clothing > Tops", "ebay": "Clothing > Other"})):
            seed = await prepare_generation_schema(
                self.db,
                self.conv.id,
                Provider({}),
                "Cotton tee",
                "",
                on_status=statuses.append,
            )
        self.assertEqual(seed["category_path"], "Clothing > Tops")
        # Prefer the marketplace leaf that produced the remembered fields.
        self.assertEqual(seed["marketplace_categories"]["ebay"], "Clothing > Shirts")
        self.assertEqual(seed["_schema_source"], "cache")
        self.assertTrue(any("cached" in message.casefold() for message in statuses))
        self.manager.register_wait.assert_not_called()
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [self.job])

    async def test_generation_defers_schema_probe(self):
        self.job.status = "completed"
        self.db.commit()

        async def discover():
            return True

        with patch("vendoo_studio.routes.extension.dispatch_queued_jobs", side_effect=discover), \
             patch("vendoo_studio.services.marketplaces.selected_fillable_platforms", return_value=["ebay"]), \
             patch("vendoo_studio.services.category_selection.select_categories", new=AsyncMock(
                 return_value={"general": "Clothing > Tops", "ebay": "Clothing > Shirts"})):
            seed = await prepare_generation_schema(self.db, self.conv.id, Provider({}), "Cotton tee", "")
        self.assertEqual(seed["category_path"], "Clothing > Tops")
        self.assertEqual(seed["_schema_source"], "deferred_probe")
        self.assertTrue(seed.get("_schema_probe_job_id"))
        self.manager.register_wait.assert_called()
        self.manager.cancel_wait.assert_not_called()
