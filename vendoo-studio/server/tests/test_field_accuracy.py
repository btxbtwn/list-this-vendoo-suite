from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategorySchema  # noqa: F401
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import JobRepo, ListingRepo
from vendoo_studio.services import auto_apply
from vendoo_studio.services.fill_log import FULL_OPTION_LIMIT, canonical_option, prompt_options
from vendoo_studio.services.listing_field_gaps import build_missing_fields_request
from vendoo_studio.services.listing_generate import format_photo_analysis

VENDOO_JS = Path(__file__).resolve().parents[3] / "vendoo-extension" / "content-scripts" / "vendoo.js"


class PromptOptionsTest(unittest.TestCase):
    def test_short_lists_pass_through_whole(self):
        options = [f"Style {index}" for index in range(FULL_OPTION_LIMIT)]
        shown, complete = prompt_options(options, "anything")
        self.assertEqual(shown, options)
        self.assertTrue(complete)

    def test_long_lists_keep_relevant_and_fallback_options(self):
        options = [f"Filler {index}" for index in range(150)] + ["Floral Blouse", "Does Not Apply"]
        shown, complete = prompt_options(options, "Zara floral blouse with ruffles")
        self.assertFalse(complete)
        self.assertIn("Floral Blouse", shown)
        self.assertIn("Does Not Apply", shown)
        self.assertLessEqual(len(shown), 26)

    def test_gap_request_shows_full_option_list_and_rejected_value(self):
        options = [f"Option {index}" for index in range(60)]
        text = build_missing_fields_request(
            {"title": "Top"},
            [{"marketplace": "etsy", "field": "Sleeve length", "options": options, "rejected": "Long"}],
        )
        self.assertIn("Option 59", text)
        self.assertIn("Vendoo rejected 'Long'", text)

    def test_canonical_option_matches_case_and_punctuation(self):
        self.assertEqual(canonical_option("long sleeve", ["Long Sleeve", "Short Sleeve"]), "Long Sleeve")
        self.assertEqual(canonical_option("T-Shirt", ["T Shirt"]), "T Shirt")
        self.assertIsNone(canonical_option("Tank", ["Long Sleeve"]))


class TagTextTest(unittest.TestCase):
    def test_photo_analysis_includes_verbatim_tag_text(self):
        text = format_photo_analysis({
            "brand": {"value": "Zara"},
            "tag_text": {"brand_label": "ZARA WOMAN", "size_tag": "EUR M", "care_tag": "100% cotton", "rn_number": ""},
        })
        self.assertIn('- tag text: brand label "ZARA WOMAN"; size tag "EUR M"; care tag "100% cotton"', text)
        self.assertNotIn("RN", text)


class ApplyCoercionTest(unittest.TestCase):
    def test_build_apply_patches_uses_exact_known_option(self):
        listing = {"ebay_specifics": {"sleeveLength": "long sleeve"}}
        item = {"listings": {"ebay": {"categorySpecifics": {"sleeveLength": ""}}}}
        patches = auto_apply.build_apply_patches(
            listing, item, {"by_marketplace": {}},
            lambda marketplace, field: ["Long Sleeve", "Short Sleeve"],
        )
        self.assertEqual(patches[0]["value"], "Long Sleeve")


class RejectedFillRepairTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = Conversation(title="Top")
        self.db.add(self.conv)
        self.db.commit()
        revision = ListingRepo(self.db).save_revision(self.conv.id, {"title": "Top"}, source="model")
        self.job = Job(conversation_id=self.conv.id, approved_revision_id=revision.id, status="completed",
                       current_step="fields_applied", vendoo_item_id="abc", listing_snapshot={"platforms": ["etsy"]})
        self.db.add(self.job)
        self.db.commit()
        self.patches = [{"marketplace": "etsy", "field": "Sleeve length", "value": "Long", "selector": ""}]
        JobRepo(self.db).add_event(self.job.id, "step_completed", "filling_fields", {"fill_log": {"entries": [
            {"marketplace": "etsy", "field": "Sleeve length", "status": "invalid", "value_preview": "Long",
             "options": ["Long sleeve", "Short sleeve"]},
            {"marketplace": "etsy", "field": "Neckline", "status": "filled", "value_preview": "Crew"},
        ]}})

    def test_rejected_fill_is_reasked_and_reapplied_with_exact_option(self):
        ask = AsyncMock(return_value=[{"marketplace": "etsy", "field": "Sleeve length", "value": "long sleeve"}])
        apply = AsyncMock(return_value=(True, None))
        with patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", new=ask), \
                patch.object(auto_apply, "apply_patches", new=apply):
            result = asyncio.run(auto_apply.repair_rejected_fills(
                self.db, self.job, {"title": "Top"}, self.patches, object(),
                evidence="photos", options_for=lambda marketplace, field: [],
            ))
        self.assertEqual(result["repaired"], 1)
        gaps = ask.await_args.kwargs["gaps"]
        self.assertEqual([gap["field"] for gap in gaps], ["Sleeve length"])
        self.assertEqual(gaps[0]["options"], ["Long sleeve", "Short sleeve"])
        repairs = apply.await_args.args[3]
        self.assertEqual(repairs[0]["value"], "Long sleeve")
        self.assertEqual(ListingRepo(self.db).get_revisions(self.conv.id)[0].source, "apply_repair")

    def test_values_outside_the_options_are_not_reapplied(self):
        ask = AsyncMock(return_value=[{"marketplace": "etsy", "field": "Sleeve length", "value": "Three quarter"}])
        apply = AsyncMock(return_value=(True, None))
        with patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", new=ask), \
                patch.object(auto_apply, "apply_patches", new=apply):
            result = asyncio.run(auto_apply.repair_rejected_fills(
                self.db, self.job, {"title": "Top"}, self.patches, object(),
                evidence="", options_for=lambda marketplace, field: [],
            ))
        self.assertEqual(result["repaired"], 0)
        apply.assert_not_awaited()


class ExtensionRegistryScopeTest(unittest.TestCase):
    def test_registry_selectors_are_scoped_to_current_marketplace(self):
        source = VENDOO_JS.read_text()
        start = source.index("  function resolveWithRegistry")
        body = source[start:source.index("\n  }\n", start)]
        self.assertIn("currentFillMarketplace", body)
        self.assertIn("key === scoped", body)
