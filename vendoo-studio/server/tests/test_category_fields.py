from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services import category_fields
from vendoo_studio.services.vendoo_specifics import normalize_specifics

RAW = {
    "Season": {
        "id": "Season", "display": "Season",
        "rules": {"fieldOptions": {"minValues": 0, "maxValues": 100, "selectionMode": "SelectionOnly"}},
        "options": {"0": {"id": "Spring", "display": "Spring"}, "1": {"id": "Fall", "display": "Fall"}},
    },
    "condition": {
        "id": "condition", "display": "Condition",
        "rules": {"fieldOptions": {"minValues": 1, "maxValues": 1, "selectionMode": "SelectionOnly"}},
        "options": {"0": {"id": "3000", "display": "Pre-owned - Good"}},
    },
    "Size": {
        "id": "Size", "display": "Size",
        "rules": {"fieldOptions": {"minValues": 1, "maxValues": 1, "selectionMode": "FreeText"}},
        "options": {},
    },
}


class CategoryFieldsCacheTest(unittest.TestCase):
    marketplace = "ebay"
    category_id = "test-53159"

    def tearDown(self):
        from vendoo_studio.database import SessionLocal
        from vendoo_studio.models.catalog import CategoryFieldSchema

        with SessionLocal() as db:
            db.query(CategoryFieldSchema).filter_by(
                marketplace=self.marketplace, category_id=self.category_id
            ).delete()
            db.commit()

    def test_round_trips_through_the_cache(self):
        self.assertIsNone(category_fields.load_fields(self.marketplace, self.category_id))
        specs = normalize_specifics(RAW)
        category_fields.save_fields(self.marketplace, self.category_id, specs)

        loaded = category_fields.load_fields(self.marketplace, self.category_id)
        self.assertEqual(sorted(loaded), ["Season", "Size", "condition"])
        self.assertTrue(loaded["Season"].multi)
        self.assertTrue(loaded["condition"].required)
        self.assertFalse(loaded["Size"].selection_only)
        self.assertEqual(loaded["condition"].options, {"3000": "Pre-owned - Good"})

    def test_saving_again_replaces_the_row(self):
        category_fields.save_fields(self.marketplace, self.category_id, normalize_specifics(RAW))
        category_fields.save_fields(
            self.marketplace, self.category_id,
            normalize_specifics({"Size": RAW["Size"]}),
        )
        loaded = category_fields.load_fields(self.marketplace, self.category_id)
        self.assertEqual(sorted(loaded), ["Size"])

    def test_fields_route_serves_the_cache(self):
        category_fields.save_fields(self.marketplace, self.category_id, normalize_specifics(RAW))
        client = TestClient(app)
        res = client.get("/api/catalog/fields", params={
            "marketplace": self.marketplace, "category_id": self.category_id,
        })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(sorted(body["required"]), ["Size", "condition"])
        season = next(row for row in body["fields"] if row["key"] == "Season")
        self.assertTrue(season["multi"])
        self.assertEqual(season["options"], {"Spring": "Spring", "Fall": "Fall"})

    def test_uncached_category_is_a_404(self):
        client = TestClient(app)
        res = client.get("/api/catalog/fields", params={
            "marketplace": "ebay", "category_id": "never-fetched",
        })
        self.assertEqual(res.status_code, 404)


class MercariSpecificsTest(unittest.TestCase):
    """Mercari's schema comes from a static file, keyed flat as {cat}_Size."""

    MASTER = {
        "version": "v1.15",
        "categorySizeGroup": {"12": 1, "99": 7},
        "itemSizes": [
            {"id": 4, "name": "M (8-10)", "itemSizeGroupId": 1, "itemSizeSubGroupId": 11, "displayOrder": 50},
            {"id": 293, "name": "M (8-10)", "itemSizeGroupId": 1, "itemSizeSubGroupId": 12, "displayOrder": 50},
            {"id": 353, "name": "M (7-9)", "itemSizeGroupId": 1, "itemSizeSubGroupId": 15, "displayOrder": 50},
            {"id": 2, "name": "XS (0-2)", "itemSizeGroupId": 1, "itemSizeSubGroupId": 11, "displayOrder": 10},
            {"id": 900, "name": "Other group", "itemSizeGroupId": 2, "itemSizeSubGroupId": 11},
        ],
    }

    def test_collapses_duplicate_labels_to_the_primary_sub_group(self):
        from vendoo_studio.services.vendoo_specifics import mercari_specifics

        specs = mercari_specifics(self.MASTER, "12")
        self.assertEqual(list(specs), ["Size"])
        # 293 duplicates 4's label exactly, so only the lower sub-group's id
        # survives; the juniors label is a different choice and stays.
        self.assertEqual(specs["Size"].options, {
            "2": "XS (0-2)", "4": "M (8-10)", "353": "M (7-9)",
        })

    def test_resolves_a_qualified_size_and_reports_a_bare_one(self):
        from vendoo_studio.services.vendoo_specifics import encode_specific, mercari_specifics

        size = mercari_specifics(self.MASTER, "12")["Size"]
        self.assertEqual(encode_specific(size, "M (8-10)"), ("4", True))
        self.assertEqual(encode_specific(size, "M (7-9)"), ("353", True))
        # "M" fits both standard and juniors, so it is reported, not guessed.
        self.assertEqual(encode_specific(size, "M"), ("", False))

    def test_a_category_without_a_size_group_has_no_size(self):
        from vendoo_studio.services.vendoo_specifics import mercari_specifics

        self.assertEqual(mercari_specifics(self.MASTER, "404"), {})
        # a group with no rows is empty too, not a stub field
        self.assertEqual(mercari_specifics(self.MASTER, "99"), {})

    def test_size_lands_on_the_flat_key_vendoo_reads(self):
        from vendoo_studio.services.vendoo_api import build_vendoo_item
        from vendoo_studio.services.vendoo_specifics import mercari_specifics

        item, unresolved = build_vendoo_item(
            {
                "title": "Top",
                "size": "M (8-10)",
                "marketplace_category_ids": {"mercari": "12"},
                "marketplace_categories": {"mercari": "Women > Tops"},
            },
            specifics={"mercari": mercari_specifics(self.MASTER, "12")},
        )
        stored = item["listings"]["mercari"]["categorySpecifics"]
        self.assertEqual(stored["12_Size"], "4")
        # flat: no scale companion, unlike Poshmark and Etsy
        self.assertNotIn("12_Size_scale", stored)
        self.assertEqual([r for r in unresolved if "mercari" in r["field"]], [])


if __name__ == "__main__":
    unittest.main()
