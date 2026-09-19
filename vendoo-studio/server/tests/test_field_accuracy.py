from __future__ import annotations

import unittest
from pathlib import Path

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


class ExtensionRegistryScopeTest(unittest.TestCase):
    def test_registry_selectors_are_scoped_to_current_marketplace(self):
        source = VENDOO_JS.read_text()
        start = source.index("  function resolveWithRegistry")
        body = source[start:source.index("\n  }\n", start)]
        self.assertIn("currentFillMarketplace", body)
        self.assertIn("key === scoped", body)
