from __future__ import annotations

import unittest
from unittest import mock

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


class DropdownOptionsRouteTest(unittest.TestCase):
    def test_serves_skill_scrape_with_mercari_shipping(self):
        client = TestClient(app)
        res = client.get("/api/catalog/dropdown-options")
        self.assertEqual(res.status_code, 200)
        forms = res.json()["forms"]
        self.assertIn("Streetwear", forms["depop"]["style"])
        self.assertIn("Another company or person", forms["etsy"]["whoMade"])
        self.assertTrue(
            any("Ground Advantage" in label for label in forms["mercari"]["shippingLabel"])
        )
        self.assertIn("FixedPriceItem", forms["ebay"]["pricingFormat"])


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


class SchemaFeedsTheGapFillerTest(unittest.TestCase):
    """The cached schema is what the gap filler asks the model to fill."""

    def test_offers_every_empty_schema_field_with_its_options(self):
        from vendoo_studio.services import listing_field_gaps
        from vendoo_studio.services.vendoo_specifics import normalize_specifics

        specs = normalize_specifics({
            "Season": {"id": "Season", "display": "Season", "options": {
                "0": {"id": "Spring", "display": "Spring"},
                "1": {"id": "Winter", "display": "Winter"},
            }, "rules": {"fieldOptions": {"minValues": 0, "maxValues": 2,
                                          "selectionMode": "SelectionOnly"}}},
            "Department": {"id": "Department", "display": "Department", "options": {
                "0": {"id": "Women", "display": "Women"},
            }, "rules": {"fieldOptions": {"minValues": 1, "maxValues": 1,
                                          "selectionMode": "SelectionOnly"}}},
        })
        listing = {
            "category_path": "Clothing > Tops",
            "marketplace_category_ids": {"ebay": "53159"},
            "ebay_specifics": {"department": "Women"},
        }

        class NoRows:
            def query(self, *_a, **_k): return self
            def filter_by(self, *_a, **_k): return self
            def all(self): return []

        with mock.patch.object(listing_field_gaps, "load_fields", return_value=specs), \
                mock.patch.object(listing_field_gaps, "RegistryService") as registry:
            registry.return_value._repo.list_fields.return_value = []
            gaps = listing_field_gaps.collect_empty_discovered_fields(NoRows(), listing)

        by_field = {row["field"]: row for row in gaps if row["marketplace"] == "ebay"}
        # Department is already answered in the listing, so it is not a gap.
        self.assertNotIn("Department", by_field)
        # Season is empty, and the model is handed the exact values it may use.
        self.assertIn("Season", by_field)
        self.assertEqual(by_field["Season"]["options"], ["Spring", "Winter"])


class DeclineAndFallbackTest(unittest.TestCase):
    """What the model says when a list has no answer for the item."""

    def spec(self, key, options, required=False, display=None):
        return normalize_specifics({key: {
            "id": key, "display": display or key,
            "options": {str(i): {"id": v, "display": v} for i, v in enumerate(options)},
            "rules": {"fieldOptions": {"minValues": 1 if required else 0, "maxValues": 1,
                                       "selectionMode": "SelectionOnly"}},
        }})[key]

    def test_does_not_apply_is_a_decline_not_a_rejection(self):
        from vendoo_studio.services.vendoo_specifics import encode_specific

        occasion = self.spec("Occasion", ["Birthday", "Wedding"])
        # Nothing to store, and nothing worth reporting either.
        self.assertEqual(encode_specific(occasion, "Does Not Apply"), ("", True))
        self.assertEqual(encode_specific(occasion, "N/A"), ("", True))

    def test_a_list_that_offers_it_still_blanks_it(self):
        from vendoo_studio.services.vendoo_specifics import encode_specific

        # eBay renders the phrase verbatim on the form, so even the lists that
        # offer it get the blank. Studio keeps the answer on the listing.
        handmade = self.spec("Handmade", ["Yes", "No", "Does Not Apply"])
        self.assertEqual(encode_specific(handmade, "Does Not Apply"), ("", True))
        self.assertEqual(encode_specific(handmade, "No"), ("No", True))

    def test_free_text_fields_take_the_blank_too(self):
        from vendoo_studio.services.vendoo_specifics import FieldSpec, encode_specific

        upc = FieldSpec("upc", display="UPC")
        self.assertEqual(encode_specific(upc, "Does Not Apply"), ("", True))
        self.assertEqual(encode_specific(upc, "N/A"), ("", True))
        self.assertEqual(encode_specific(upc, "012345678905"), ("012345678905", True))

    def test_a_not_applicable_answer_is_recognised_whole(self):
        from vendoo_studio.services.vendoo_specifics import is_not_applicable

        self.assertTrue(is_not_applicable("Does Not Apply"))
        self.assertTrue(is_not_applicable(["N/A", "does not apply"]))
        self.assertFalse(is_not_applicable(""))
        self.assertFalse(is_not_applicable("No"))
        self.assertFalse(is_not_applicable(["Cotton", "N/A"]))

    def test_a_real_value_the_list_lacks_is_still_reported(self):
        from vendoo_studio.services.vendoo_specifics import encode_specific

        sleeve = self.spec("Sleeve length", ["Long Sleeve", "Sleeveless"])
        self.assertEqual(encode_specific(sleeve, "Short sleeve"), ("", False))

    def test_an_unlisted_brand_falls_back_to_other(self):
        from vendoo_studio.services.vendoo_specifics import encode_specific

        brand = self.spec("brand", ["Nike", "Adidas", "Other"], display="Brand")
        self.assertEqual(encode_specific(brand, "GB Girls"), ("Other", True))

    def test_no_other_option_means_it_is_reported(self):
        from vendoo_studio.services.vendoo_specifics import encode_specific

        brand = self.spec("brand", ["Nike", "Adidas"], display="Brand")
        self.assertEqual(encode_specific(brand, "GB Girls"), ("", False))


class ListingFieldsRouteTest(unittest.TestCase):
    """The app needs a form per marketplace, not one flat list of fields."""

    def test_groups_by_marketplace_with_values_and_options(self):
        from vendoo_studio.services import category_fields as cf
        from vendoo_studio.services.vendoo_specifics import normalize_specifics

        specs = normalize_specifics({
            "Season": {"id": "Season", "display": "Season", "options": {
                "0": {"id": "Spring", "display": "Spring"}},
                "rules": {"fieldOptions": {"minValues": 0, "maxValues": 2, "selectionMode": "SelectionOnly"}}},
            "Department": {"id": "Department", "display": "Department", "options": {
                "0": {"id": "Girls", "display": "Girls"}},
                "rules": {"fieldOptions": {"minValues": 1, "maxValues": 1, "selectionMode": "SelectionOnly"}}},
        })
        listing = {"ebay_specifics": {"department": "Girls"}}

        with mock.patch.object(cf, "listing_category_ids", return_value={"ebay": "53159"}), \
                mock.patch.object(cf, "load_fields", return_value=specs), \
                mock.patch("vendoo_studio.repositories.queries.ConversationRepo.get", return_value=object()), \
                mock.patch("vendoo_studio.repositories.queries.ListingRepo.get_revisions",
                           return_value=[type("R", (), {"listing_json": listing})()]):
            client = TestClient(app)
            body = client.get("/api/conversations/c1/vendoo-api/fields").json()

        form = body["forms"][0]
        self.assertEqual(form["marketplace"], "ebay")
        self.assertTrue(form["known"])
        labels = [f["label"] for f in form["fields"]]
        # Required first, so what blocks a listing reads at the top.
        self.assertEqual(labels[0], "Department")
        self.assertEqual(form["fields"][0]["value"], "Girls")
        season = next(f for f in form["fields"] if f["label"] == "Season")
        self.assertEqual(season["options"], ["Spring"])
        self.assertTrue(season["multi"])
        # Controls the category schema omits still show, from the form scrape.
        material = next(f for f in form["fields"] if f["label"] == "Material")
        self.assertFalse(material["required"])
        self.assertIn("Acrylic", material["options"])
        self.assertEqual(labels, sorted(set(labels), key=labels.index))

    def test_an_uncached_leaf_is_fetched_from_vendoo_and_stored(self):
        """The cache only fills on create/send, so this listing's own leaf is asked for."""
        from vendoo_studio.services import category_fields as cf
        from vendoo_studio.services import vendoo_create

        raw = {"material": {"id": "material", "display": "Material", "options": {
            "0": {"id": "Silk", "display": "Silk"}},
            "rules": {"fieldOptions": {"minValues": 0, "maxValues": 1, "selectionMode": "SelectionOnly"}}}}
        saved: list[tuple] = []

        async def fake_run_ops(job, ops):
            saved.append(("op", ops[0]["marketplace_id"], ops[0]["category_id"]))
            return {"results": [{"op": "category_specifics", "ok": True, "specifics": raw}]}

        listing = {"depop_specifics": {"material": "Chiffon"}}
        with mock.patch.object(cf, "listing_category_ids", return_value={"depop": "77"}), \
                mock.patch.object(cf, "load_fields", return_value=None), \
                mock.patch.object(vendoo_create, "run_ops", fake_run_ops), \
                mock.patch("vendoo_studio.routes.extension.ExtensionManager.connected",
                           new_callable=mock.PropertyMock, return_value=True), \
                mock.patch("vendoo_studio.services.category_fields.save_fields",
                           side_effect=lambda *a: saved.append(("saved", a[0], a[1]))), \
                mock.patch("vendoo_studio.repositories.queries.ConversationRepo.get", return_value=object()), \
                mock.patch("vendoo_studio.repositories.queries.ListingRepo.get_revisions",
                           return_value=[type("R", (), {"listing_json": listing})()]):
            body = TestClient(app).get("/api/conversations/c1/vendoo-api/fields").json()

        form = body["forms"][0]
        self.assertTrue(form["known"])
        material = next(f for f in form["fields"] if f["label"] == "Material")
        self.assertEqual(material["value"], "Chiffon")
        self.assertEqual(material["options"], ["Silk"])
        self.assertIn(("op", "depop", "77"), saved)
        self.assertIn(("saved", "depop", "77"), saved)

    def test_a_value_no_form_names_still_gets_a_row(self):
        """Otherwise a rejected leftover key is invisible and cannot be cleared."""
        from vendoo_studio.services import category_fields as cf

        specs = normalize_specifics({"Season": {"id": "Season", "display": "Season", "options": {
            "0": {"id": "Spring", "display": "Spring"}},
            "rules": {"fieldOptions": {"minValues": 0, "maxValues": 1, "selectionMode": "SelectionOnly"}}}})
        listing = {"ebay_specifics": {"Fabric Weight": "Lightweight", "categoryPath": "a/b"}}

        with mock.patch.object(cf, "listing_category_ids", return_value={"ebay": "53159"}), \
                mock.patch.object(cf, "load_fields", return_value=specs), \
                mock.patch("vendoo_studio.repositories.queries.ConversationRepo.get", return_value=object()), \
                mock.patch("vendoo_studio.repositories.queries.ListingRepo.get_revisions",
                           return_value=[type("R", (), {"listing_json": listing})()]):
            body = TestClient(app).get("/api/conversations/c1/vendoo-api/fields").json()

        labels = {f["label"]: f for f in body["forms"][0]["fields"]}
        self.assertEqual(labels["Fabric Weight"]["value"], "Lightweight")
        # Studio's own bookkeeping keys are not form fields.
        self.assertNotIn("Category Path", labels)

    def test_a_category_with_no_cached_schema_is_marked_unknown(self):
        from vendoo_studio.services import category_fields as cf

        with mock.patch.object(cf, "listing_category_ids", return_value={"vinted": "9"}), \
                mock.patch.object(cf, "load_fields", return_value=None), \
                mock.patch("vendoo_studio.repositories.queries.ConversationRepo.get", return_value=object()), \
                mock.patch("vendoo_studio.repositories.queries.ListingRepo.get_revisions", return_value=[]):
            body = TestClient(app).get("/api/conversations/c1/vendoo-api/fields").json()
        self.assertEqual(body["forms"][0]["known"], False)
        self.assertEqual(body["forms"][0]["fields"], [])


if __name__ == "__main__":
    unittest.main()
