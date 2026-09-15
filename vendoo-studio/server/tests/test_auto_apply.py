from __future__ import annotations

import unittest

from vendoo_studio.services.auto_apply import build_apply_patches


class AutoApplyPatchTest(unittest.TestCase):
    def test_build_apply_patches_for_empty_vendoo_fields(self):
        listing = {
            "title": "Paisley top",
            "tags": ["paisley", "long sleeve top"],
            "ebay_specifics": {"department": "Women", "type": "Blouse"},
        }
        item = {
            "generalDetails": {
                "title": "",
                "tags": [],
            },
            "listings": {
                "ebay": {
                    "categorySpecifics": {
                        "department": "",
                        "type": "",
                    },
                },
            },
        }
        report = {"by_marketplace": {}}

        patches = build_apply_patches(listing, item, report)
        labels = {(patch["marketplace"], patch["field"]) for patch in patches}

        self.assertIn(("general", "Title"), labels)
        self.assertIn(("general", "Tags"), labels)
        self.assertIn(("ebay", "Department"), labels)
        self.assertIn(("ebay", "Type"), labels)

    def test_build_apply_patches_skips_already_filled_vendoo_fields(self):
        listing = {"title": "New title", "tags": ["one"]}
        item = {
            "generalDetails": {
                "title": "Already set",
                "tags": [],
            },
        }
        patches = build_apply_patches(listing, item, {"by_marketplace": {}})
        labels = {patch["field"] for patch in patches}
        self.assertNotIn("Title", labels)
        self.assertIn("Tags", labels)


if __name__ == "__main__":
    unittest.main()
