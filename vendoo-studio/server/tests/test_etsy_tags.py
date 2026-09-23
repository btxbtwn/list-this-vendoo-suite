from __future__ import annotations

import unittest

from vendoo_studio.models.etsy_fields import sanitize_etsy_tag, sanitize_etsy_tags
from vendoo_studio.services.vendoo_api import build_vendoo_item


class EtsyTagSanitizeTests(unittest.TestCase):
    def test_strips_invalid_characters(self):
        self.assertEqual(sanitize_etsy_tag("#y2k"), "y2k")
        self.assertEqual(sanitize_etsy_tag("pop/art"), "pop art")
        self.assertEqual(sanitize_etsy_tag("50% cotton"), "50 cotton")
        self.assertEqual(sanitize_etsy_tag("rock & roll"), "rock roll")
        self.assertEqual(sanitize_etsy_tag("graphic_tee"), "graphic tee")

    def test_keeps_allowed_punctuation(self):
        self.assertEqual(sanitize_etsy_tag("women's tee"), "women's tee")
        self.assertEqual(sanitize_etsy_tag("t-shirt"), "t-shirt")
        self.assertEqual(sanitize_etsy_tag("artist's gift"), "artist's gift")

    def test_normalizes_smart_punctuation(self):
        self.assertEqual(sanitize_etsy_tag("women\u2019s tee"), "women's tee")
        self.assertEqual(sanitize_etsy_tag("mid\u2013century"), "mid-century")

    def test_strips_leading_hyphen_or_apostrophe(self):
        self.assertEqual(sanitize_etsy_tag("-vintage"), "vintage")
        self.assertEqual(sanitize_etsy_tag("'sale"), "sale")

    def test_list_limits_and_dedupes(self):
        tags = sanitize_etsy_tags([
            "#streetwear",
            "streetwear",
            "a tag far longer than twenty",
            "graphic tee",
            *([f"tag{i}" for i in range(20)]),
        ])
        self.assertEqual(tags[0], "streetwear")
        self.assertNotIn("a tag far longer than twenty", tags)
        self.assertEqual(len(tags), 13)
        self.assertEqual(len({t.casefold() for t in tags}), 13)

    def test_build_vendoo_item_sanitizes_etsy_tags(self):
        item, _ = build_vendoo_item({
            "title": "Tee",
            "tags": ["#y2k", "pop/art", "women's tee", "graphic_tee!!!"],
        }, None)
        etsy = item["listings"]["etsy"]["marketplaceSpecifics"]
        self.assertEqual(
            etsy["tags"],
            ["y2k", "pop art", "women's tee", "graphic tee"],
        )
        # General tags stay as authored — only the Etsy copy is scrubbed.
        self.assertEqual(
            item["generalDetails"]["tags"],
            ["#y2k", "pop/art", "women's tee", "graphic_tee!!!"],
        )


if __name__ == "__main__":
    unittest.main()
