"""Known-option inference across marketplace apparel chip fields."""

from __future__ import annotations

import unittest

from vendoo_studio.models.depop_fields import ensure_depop_category_optionals, infer_depop_occasions
from vendoo_studio.models.ebay_fields import ensure_ebay_category_optionals
from vendoo_studio.models.etsy_fields import ensure_etsy_category_optionals
from vendoo_studio.models.listing_values import DNA_VALUE, dropdown_field_options, infer_known_option
from vendoo_studio.models.validation import ensure_poshmark_style_tags


class KnownOptionInferenceTest(unittest.TestCase):
    def test_dropdown_field_options_loads_etsy_clothing_style(self):
        options = dropdown_field_options("etsy", "clothingStyle")
        self.assertIn("Streetwear", options)

    def test_infer_known_option_picks_floral(self):
        options = dropdown_field_options("ebay", "Pattern", "pattern")
        hit = infer_known_option(
            "Pink floral peasant blouse",
            options,
            cues={"Floral": (r"\\bfloral\\b",)},
            fallback="Solid",
        )
        self.assertEqual(hit, "Floral")

    def test_ebay_floral_blouse_infers_pattern_and_fit(self):
        listing = {
            "title": "Notations XL Floral Blouse Pink Relaxed",
            "description": "Floral peasant blouse, relaxed fit",
            "ebay_specifics": {
                "type": "Blouse", "department": "Women", "size": "XL",
                "brand": "Notations", "sizeType": "Regular",
            },
        }
        self.assertTrue(ensure_ebay_category_optionals(listing))
        ebay = listing["ebay_specifics"]
        self.assertEqual(ebay["pattern"], "Floral")
        self.assertEqual(ebay["fit"], "Relaxed")
        self.assertEqual(ebay["handmade"], "No")

    def test_etsy_streetwear_tee_infers_clothing_style(self):
        listing = {
            "title": "Nike Graphic Tee Streetwear",
            "description": "Streetwear skate graphic tee",
            "ebay_specifics": {"type": "T-Shirt"},
            "etsy_specifics": {
                "who_made": "Another company or person",
                "what_is": "A finished product",
                "when_made": "2010 - 2019 (Recently)",
            },
        }
        self.assertTrue(ensure_etsy_category_optionals(listing))
        self.assertEqual(listing["etsy_specifics"]["clothingStyle"], "Streetwear")

    def test_etsy_holiday_cue_picks_chip(self):
        listing = {
            "title": "Ugly Christmas Sweater",
            "description": "Festive christmas holiday knit",
            "ebay_specifics": {"type": "Sweater"},
            "etsy_specifics": {
                "who_made": "Another company or person",
                "what_is": "A finished product",
                "when_made": "2010 - 2019 (Recently)",
            },
        }
        self.assertTrue(ensure_etsy_category_optionals(listing))
        self.assertEqual(listing["etsy_specifics"]["holiday"], "Christmas")
        self.assertEqual(listing["etsy_specifics"]["occasion"], DNA_VALUE)

    def test_etsy_wedding_occasion_picks_chip(self):
        listing = {
            "title": "Wedding Guest Dress",
            "description": "Formal wedding gown",
            "ebay_specifics": {"type": "Dress"},
            "etsy_specifics": {
                "who_made": "Another company or person",
                "what_is": "A finished product",
                "when_made": "2010 - 2019 (Recently)",
            },
        }
        self.assertTrue(ensure_etsy_category_optionals(listing))
        self.assertEqual(listing["etsy_specifics"]["occasion"], "Wedding")

    def test_depop_occasions_vary_by_cues(self):
        workout = {
            "title": "Nike Running Leggings Gym",
            "description": "Athletic workout activewear for training",
            "ebay_specifics": {"type": "Leggings", "occasion": "Activewear"},
            "depop_specifics": {"source": "Preloved", "style": ["Sportswear"]},
        }
        occasions = infer_depop_occasions(workout)
        self.assertIn("Workout", occasions)
        self.assertNotEqual(occasions, ["Casual", "Going out", "Vacation"])
        self.assertTrue(ensure_depop_category_optionals(workout))
        self.assertIn("Workout", workout["depop_specifics"]["occasion"])

        tee = {
            "title": "Jerzees M Soft Cotton Graphic Tee",
            "description": "Casual everyday t-shirt",
            "ebay_specifics": {"type": "T-Shirt", "occasion": "Casual"},
            "depop_specifics": {},
        }
        tee_occ = infer_depop_occasions(tee)
        self.assertEqual(tee_occ[0], "Casual")
        self.assertNotEqual(tee_occ, ["Casual", "Going out", "Vacation"])

        empty = {
            "title": "Item", "description": "x",
            "ebay_specifics": {}, "depop_specifics": {},
        }
        self.assertEqual(infer_depop_occasions(empty), ["Casual", "Going out", "Vacation"])

    def test_poshmark_style_tags_use_inferred_styles(self):
        listing = {
            "title": "Nike Graphic Tee Streetwear Skate",
            "description": "Oversized hoodie street style skateboard",
            "ebay_specifics": {"type": "T-Shirt"},
            "depop_specifics": {"style": ["Streetwear", "Casual", "Skater"]},
            "poshmark_specifics": {},
        }
        self.assertTrue(ensure_poshmark_style_tags(listing))
        tags = listing["poshmark_specifics"]["styleTags"]
        self.assertEqual(len(tags), 3)
        self.assertIn("Streetwear", tags)
        self.assertNotEqual(tags, ["Casual", "Retro", "Vintage"])


if __name__ == "__main__":
    unittest.main()
