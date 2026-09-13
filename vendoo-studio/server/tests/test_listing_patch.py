from __future__ import annotations

import unittest

from vendoo_studio.services.listing_patch import apply_json_patch


class ApplyJsonPatchTest(unittest.TestCase):
    def test_replaces_list_indexes_and_display_name_keys(self):
        listing = {
            "department": "Women",
            "category_path": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
            "ebay_specifics": {
                "department": "Women",
                "type": "T-Shirt",
                "Primary Store Category": "Women's Clothing",
                "Secondary Store Category": "T-Shirts",
            },
            "etsy_specifics": {"section": "", "tags": ["women's tee"]},
            "poshmark_specifics": {"styleTags": ["Graphic Tee", "Casual", "Cotton"]},
            "mercari_specifics": {"Brand": "Casa San Bord"},
        }
        updated = apply_json_patch(listing, [
            {"op": "replace", "path": "/department", "value": "Men"},
            {"op": "replace", "path": "/category_path", "value": "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts"},
            {"op": "replace", "path": "/ebay_specifics/department", "value": "Men"},
            {"op": "replace", "path": "/ebay_specifics/primaryStoreCategory", "value": "Men's Clothing"},
            {"op": "replace", "path": "/ebay_specifics/secondaryStoreCategory", "value": "T-Shirts"},
            {"op": "replace", "path": "/etsy_specifics/section", "value": "Men's T-Shirts"},
            {"op": "replace", "path": "/poshmark_specifics/styleTags/0", "value": "Casual"},
            {"op": "replace", "path": "/poshmark_specifics/styleTags/1", "value": "Streetwear"},
            {"op": "replace", "path": "/poshmark_specifics/styleTags/2", "value": "Embroidered"},
            {"op": "replace", "path": "/mercari_specifics/brand", "value": "Casa San Bord"},
        ])

        self.assertEqual(updated["department"], "Men")
        self.assertEqual(updated["ebay_specifics"]["department"], "Men")
        self.assertEqual(updated["ebay_specifics"]["Primary Store Category"], "Men's Clothing")
        self.assertNotIn("primaryStoreCategory", updated["ebay_specifics"])
        self.assertEqual(updated["poshmark_specifics"]["styleTags"], ["Casual", "Streetwear", "Embroidered"])
        self.assertEqual(updated["mercari_specifics"]["Brand"], "Casa San Bord")
        self.assertNotIn("brand", updated["mercari_specifics"])
        self.assertEqual(listing["poshmark_specifics"]["styleTags"][0], "Graphic Tee")

    def test_appends_and_removes_list_items(self):
        listing = {"tags": ["a", "b"]}
        updated = apply_json_patch(listing, [
            {"op": "add", "path": "/tags/-", "value": "c"},
            {"op": "remove", "path": "/tags/0"},
        ])
        self.assertEqual(updated["tags"], ["b", "c"])

    def test_extracts_patch_from_prose_and_skips_bad_ops(self):
        from vendoo_studio.services.listing_patch import extract_json_patch, summarize_json_patch

        text = (
            "This is a men's T-shirt, not women's.\n\n"
            "```json\n"
            '[{"op":"replace","path":"/department","value":"Men"},'
            '{"op":"replace","path":"/poshmark_specifics/styleTags/0","value":"Casual"}]\n'
            "```"
        )
        ops = extract_json_patch(text)
        self.assertEqual(ops[0]["value"], "Men")
        summary = summarize_json_patch(ops)
        self.assertIn("Department: Men", summary)
        self.assertIn("Style tags: Casual", summary)

        updated = apply_json_patch(
            {"department": "Women", "tags": ["a"]},
            [
                {"op": "replace", "path": "/tags/not-an-index", "value": "x"},
                {"op": "replace", "path": "/department", "value": "Men"},
            ],
        )
        self.assertEqual(updated["department"], "Men")
        self.assertEqual(updated["tags"], ["a"])


if __name__ == "__main__":
    unittest.main()
