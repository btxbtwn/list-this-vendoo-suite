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
from vendoo_studio.services.listing_completion import (
    MAX_CATEGORY_REPAIRS,
    MAX_READBACK_RETRIES,
    MAX_REPAIR_ROUNDS,
    categories_match,
    complete_job,
    review_fields,
    store_verification,
)
from vendoo_studio.services.fill_log import listing_value_for_field, write_values_into_listing
from vendoo_studio.services.schema_probe import SCHEMA_PROBE_FLAG, prepare_generation_schema


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

    async def test_unknown_fact_is_blocked_without_asking(self):
        self.review()
        await self.run_completion({"fields": [{"marketplace": "ebay", "field": "Material", "value": "Cotton"}],
                                   "questions": ["What material is listed on the tag?"]})
        self.assertEqual(self.job.current_step, "completion_blocked")
        self.assertNotEqual(self.job.status, "completed")
        self.assertIn("Could not resolve", self.job.last_error or "")
        self.assertNotIn("?", self.job.last_error or "")
        self.dispatch.assert_not_awaited()

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

    async def test_unresolved_gap_does_not_duplicate_blocked_message(self):
        reason_prefix = "Could not resolve from photos and notes"
        ConversationRepo(self.db).add_message(
            self.conv.id, "system", f"{reason_prefix}: ebay / Material. Review Fill Log, edit the listing if needed, then resume verification.",
        )
        self.review()
        await self.run_completion({"questions": ["What material is listed on the tag?"]})
        self.assertEqual(self.job.current_step, "completion_blocked")
        messages = [m.text for m in ConversationRepo(self.db).get_messages(self.conv.id)]
        self.assertEqual(sum(1 for text in messages if reason_prefix in (text or "")), 1)
        self.dispatch.assert_not_awaited()

    async def test_answer_resumes_and_only_patches_gap(self):
        self.review()
        await self.run_completion({"questions": ["What material?"]})
        ConversationRepo(self.db).add_message(self.conv.id, "user", "It is linen.")
        await self.run_completion({"fields": [
            {"marketplace": "ebay", "field": "Material", "value": "Linen", "evidence": "linen"},
            {"marketplace": "general", "field": "Title", "value": "Changed", "evidence": "linen"},
        ]})
        self.assertEqual(len(self.dispatch.await_args.args[1]), 1)
        self.assertEqual(self.job.listing_snapshot["title"], "Tee")

    async def test_new_conditional_field_prevents_completion(self):
        self.verification["schema"]["ebay"]["fields"][0]["value"] = "Cotton"
        self.verification["schema"]["ebay"]["fields"].append({"label": "Fabric type", "value": ""})
        self.review()
        await self.run_completion({"questions": ["What fabric type?"]})
        self.assertEqual(self.job.current_step, "completion_blocked")

    async def test_identical_failed_attempt_is_not_repeated(self):
        self.listing["ebay_specifics"]["Material"] = "Cotton"
        ListingRepo(self.db).save_revision(self.conv.id, self.listing, source="user")
        self.review()
        result = {"fields": [{"marketplace": "ebay", "field": "Material", "value": "Cotton"}]}
        await self.run_completion(result)
        self.review()
        await self.run_completion(result)
        self.assertEqual(self.dispatch.await_count, 1)
        self.assertEqual(self.job.current_step, "completion_blocked")

    async def test_empty_or_partial_readback_retries_then_pauses(self):
        del self.verification["schema"]["ebay"]
        self.review()
        with patch("vendoo_studio.services.listing_completion.READBACK_RETRY_DELAY_SECONDS", 0):
            await self.run_completion({})
        self.assertEqual(self.job.current_step, "verifying_draft")
        self.assertEqual(self.job.status, "dispatched")
        self.dispatch.assert_awaited_once()
        kwargs = self.dispatch.await_args.kwargs
        self.assertTrue(kwargs.get("reload"))
        self.assertIn("ebay", kwargs.get("platforms") or [])
        self.assertTrue(any(
            event.event_type == "completion_readback_retry"
            for event in JobRepo(self.db).get_events(self.job.id)
        ))

        for _ in range(MAX_READBACK_RETRIES - 1):
            self.review()
            with patch("vendoo_studio.services.listing_completion.READBACK_RETRY_DELAY_SECONDS", 0):
                await complete_job(self.db, self.job.id)
            self.db.refresh(self.job)

        self.review()
        with patch("vendoo_studio.services.listing_completion.READBACK_RETRY_DELAY_SECONDS", 0):
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

    async def test_required_field_cannot_be_exempted(self):
        ConversationRepo(self.db).add_message(self.conv.id, "user", "It has no material tag.")
        self.review()
        await self.run_completion({"not_applicable": [{"marketplace": "ebay", "field": "Material",
            "reason": "No tag", "evidence": "no material tag"}]})
        self.assertEqual(self.job.current_step, "completion_blocked")

    async def test_optional_exemption_requires_evidence(self):
        self.verification["schema"]["ebay"]["fields"] = [{"label": "Sleeve length", "value": "", "required": False}]
        ConversationRepo(self.db).add_message(self.conv.id, "user", "This top is sleeveless.")
        self.review()
        await self.run_completion({"not_applicable": [{"marketplace": "ebay", "field": "Sleeve length",
            "reason": "No sleeves to measure", "evidence": "sleeveless"}]})
        self.assertEqual(self.job.current_step, "verified_complete")
        self.dispatch.assert_not_awaited()

    async def test_invalid_closed_option_never_dispatches(self):
        field = self.verification["schema"]["ebay"]["fields"][0]
        field.update(options=[{"label": "Wool", "value": "wool-id"}], options_complete=True)
        ConversationRepo(self.db).add_message(self.conv.id, "user", "The tag says cotton.")
        self.review()
        await self.run_completion({"fields": [{"marketplace": "ebay", "field": "Material", "value": "Cotton", "evidence": "cotton"}]})
        self.dispatch.assert_not_awaited()
        self.assertEqual(self.job.current_step, "completion_blocked")

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

    async def test_round_limit_preserves_unresolved_fields(self):
        for _ in range(MAX_REPAIR_ROUNDS):
            JobRepo(self.db).add_event(self.job.id, "completion_attempt", None, {"fields": []})
        self.review()
        await self.run_completion({})
        self.assertEqual(self.job.current_step, "completion_blocked")
        self.assertIn("Material", self.job.last_error)

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
        provider = Provider({})
        with self.assertRaisesRegex(RuntimeError, "Connect Chrome"):
            await prepare_generation_schema(self.db, self.conv.id, provider, "Cotton tee", "")
        self.assertEqual(provider.messages, [])

    async def test_generation_waits_for_schema_result(self):
        import asyncio
        self.job.status = "completed"
        self.db.commit()
        waiter = asyncio.get_running_loop().create_future()
        self.manager.register_wait.return_value = waiter

        async def discover():
            probe = JobRepo(self.db).list_by_conversation(self.conv.id)[0]
            JobRepo(self.db).add_event(probe.id, "step_completed", "discovering_schema", {"schema": self.verification["schema"]})
            probe.status = "completed"
            probe.current_step = "schema_probe_done"
            self.db.commit()
            waiter.set_result({"ok": True})

        with patch("vendoo_studio.routes.extension.dispatch_queued_jobs", side_effect=discover), \
             patch("vendoo_studio.services.marketplaces.selected_fillable_platforms", return_value=["ebay"]), \
             patch("vendoo_studio.services.category_selection.select_categories", new=AsyncMock(
                 return_value={"general": "Clothing > Tops", "ebay": "Clothing > Shirts"})):
            seed = await prepare_generation_schema(self.db, self.conv.id, Provider({}), "Cotton tee", "")
        self.assertEqual(seed["category_path"], "Clothing > Tops")
        self.manager.cancel_wait.assert_called_once()
