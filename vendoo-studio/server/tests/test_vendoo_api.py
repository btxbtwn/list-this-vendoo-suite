from __future__ import annotations

import unittest

from vendoo_studio.services.vendoo_api import (
    CURRENT_ITEM_VERSION,
    diff_roundtrip,
    encode_field,
    import_payload,
    observe_item_schema,
    vendoo_item_from_listing,
    wrap_item,
)
from vendoo_studio.services.vendoo_import import listing_from_vendoo


# Shaped like what GET /api/item/{id} returns: coded values carrying a label.
PROBED_ITEMS = [
    {
        "generalDetails": {
            "title": "Levi's 501",
            "condition": {"value": "v_pre_owned_good", "displayName": "Pre-Owned - Good"},
            "primaryColor": {"value": "v_blue", "displayName": "Blue"},
            "brand": "Levi's",
        }
    },
    {
        "generalDetails": {
            "condition": {"value": "v_new_with_tags", "displayName": "New With Tags/Box"},
            "primaryColor": {"value": "v_black", "displayName": "Black"},
            "secondaryColor": {"value": "v_white", "displayName": "White"},
        }
    },
]


class ObserveSchemaTest(unittest.TestCase):
    def test_learns_label_to_code_pairs(self):
        schema = observe_item_schema(PROBED_ITEMS)
        self.assertEqual(schema["item_count"], 2)
        condition = schema["fields"]["condition"]
        self.assertEqual(condition["shape"], "object")
        self.assertEqual(condition["labels"]["pre owned good"], "v_pre_owned_good")
        self.assertEqual(condition["labels"]["new with tags box"], "v_new_with_tags")

    def test_bare_code_teaches_its_own_label(self):
        schema = observe_item_schema([{"generalDetails": {"condition": "v_pre_owned_fair"}}])
        value, resolved = encode_field(schema, "condition", "Pre Owned Fair")
        self.assertTrue(resolved)
        self.assertEqual(value, "v_pre_owned_fair")

    def test_ignores_non_dict_items(self):
        self.assertEqual(observe_item_schema(["nope", None])["item_count"], 0)


class EncodeFieldTest(unittest.TestCase):
    def setUp(self):
        self.schema = observe_item_schema(PROBED_ITEMS)

    def test_encodes_known_label_punctuation_insensitively(self):
        value, resolved = encode_field(self.schema, "condition", "pre owned good")
        self.assertTrue(resolved)
        self.assertEqual(value, {"value": "v_pre_owned_good", "displayName": "pre owned good"})

    def test_unknown_label_is_flagged_not_invented(self):
        value, resolved = encode_field(self.schema, "condition", "Salvage")
        self.assertFalse(resolved)
        self.assertEqual(value, "Salvage")

    def test_empty_label_is_resolved_as_nothing(self):
        self.assertEqual(encode_field(self.schema, "condition", None), (None, True))


class SerializeListingTest(unittest.TestCase):
    def setUp(self):
        self.schema = observe_item_schema(PROBED_ITEMS)
        self.listing = {
            "title": "Levi's 501 Straight Jeans",
            "description": "Classic fit.",
            "price": 48.0,
            "quantity": 1,
            "brand": "Levi's",
            "condition": "Pre-Owned - Good",
            "primaryColor": "Blue",
            "category_path": "Clothing > Men > Jeans",
            "size": "32x34",
            "sizeType": "Regular",
            "tags": ["denim", "vintage"],
            "weight_lb": 1,
            "weight_oz": 8,
            "package_dimensions_in": "13x10x3",
            "ebay_specifics": {"department": "Men", "fit": "Straight", "pattern": None},
        }

    def test_builds_general_details(self):
        item, unresolved = vendoo_item_from_listing(self.listing, self.schema)
        general = item["generalDetails"]
        self.assertEqual(general["title"], "Levi's 501 Straight Jeans")
        self.assertEqual(general["price"], 48.0)
        self.assertEqual(general["condition"]["value"], "v_pre_owned_good")
        self.assertEqual(general["primaryColor"]["value"], "v_blue")
        self.assertEqual(general["size"], {"option": "32x34", "scale": "Regular"})
        self.assertEqual(general["weight"], {"pounds": 1, "ounces": 8})
        self.assertEqual(general["dimensions"], {"length": 13.0, "width": 10.0, "height": 3.0})
        self.assertEqual(general["tags"], ["denim", "vintage"])
        # sizeType was never observed, so it is reported rather than assumed.
        self.assertEqual([entry["field"] for entry in unresolved], ["sizeType"])

    def test_drops_empty_specifics_but_keeps_the_rest(self):
        item, _ = vendoo_item_from_listing(self.listing, self.schema)
        self.assertEqual(item["listings"]["ebay"], {"department": "Men", "fit": "Straight"})

    def test_category_id_preferred_over_display_path(self):
        listing = {**self.listing, "category_id": "cat_123"}
        item, _ = vendoo_item_from_listing(listing, self.schema)
        self.assertEqual(
            item["generalDetails"]["categoryV2"],
            {"id": "cat_123", "displayPath": ["Clothing", "Men", "Jeans"]},
        )

    def test_falls_back_to_path_when_category_unresolved(self):
        item, _ = vendoo_item_from_listing(self.listing, self.schema)
        self.assertEqual(item["generalDetails"]["categoryV2"], "Clothing > Men > Jeans")

    def test_images_land_under_general_details(self):
        """Vendoo's own importer sets generalDetails.images, not a top-level key."""
        item, _ = vendoo_item_from_listing(
            self.listing, self.schema, images=["https://cdn/a.jpg"]
        )
        self.assertEqual(item["generalDetails"]["images"], [{"url": "https://cdn/a.jpg"}])
        self.assertNotIn("images", item)

    def test_uploaded_image_objects_pass_through_untouched(self):
        uploaded = [{"url": "https://vendoo/a.jpg", "id": "img_1"}]
        item, _ = vendoo_item_from_listing(self.listing, self.schema, images=uploaded)
        self.assertEqual(item["generalDetails"]["images"], uploaded)

    def test_survives_a_bare_listing_with_no_schema(self):
        item, unresolved = vendoo_item_from_listing({"title": "Thing", "price": 5})
        self.assertEqual(item["generalDetails"]["title"], "Thing")
        self.assertEqual(item["generalDetails"]["quantity"], 1)
        self.assertEqual(unresolved, [])


class WrapItemTest(unittest.TestCase):
    def test_matches_vendoo_new_item_factory(self):
        item, _ = vendoo_item_from_listing({"title": "Thing", "labels": ["shelf-a"]})
        wrapped = wrap_item(item, user_id="uid-1")
        self.assertEqual(wrapped["origin"], "vendoo")
        self.assertEqual(wrapped["version"], CURRENT_ITEM_VERSION)
        self.assertEqual(wrapped["status"], {"notSaved": True})
        self.assertEqual(wrapped["type"], "item")
        self.assertEqual(wrapped["userID"], "uid-1")
        self.assertEqual(wrapped["itemID"], "")
        self.assertEqual(wrapped["labels"], ["shelf-a"])
        self.assertEqual(wrapped["generalDetails"]["title"], "Thing")
        self.assertEqual(wrapped["listings"], {})

    def test_labels_sit_on_the_item_not_general_details(self):
        item, _ = vendoo_item_from_listing({"title": "T", "labels": ["a", "b"]})
        self.assertEqual(item["labels"], ["a", "b"])
        self.assertNotIn("labels", item["generalDetails"])


class RoundTripTest(unittest.TestCase):
    """The serializer must survive a trip through Studio's own reader."""

    def test_import_reads_back_what_we_wrote(self):
        schema = observe_item_schema(PROBED_ITEMS)
        listing = {
            "title": "Levi's 501",
            "description": "Classic fit.",
            "price": 48.0,
            "quantity": 2,
            "brand": "Levi's",
            "condition": "Pre-Owned - Good",
            "primaryColor": "Blue",
            "tags": ["denim"],
        }
        item, _ = vendoo_item_from_listing(listing, schema)
        back = listing_from_vendoo(item, None)

        self.assertEqual(back["title"], "Levi's 501")
        self.assertEqual(back["price"], 48.0)
        self.assertEqual(back["quantity"], 2)
        self.assertEqual(back["brand"], "Levi's")
        self.assertEqual(back["condition"], "Pre-Owned - Good")
        self.assertEqual(back["primaryColor"], "Blue")
        self.assertEqual(back["tags"], ["denim"])


class DiffRoundTripTest(unittest.TestCase):
    def test_clean_when_vendoo_stored_what_we_sent(self):
        sent = {"generalDetails": {"title": "A", "price": 10}}
        stored = {"generalDetails": {"title": "A", "price": 10.0, "quantity": 1}}
        self.assertEqual(diff_roundtrip(sent, stored), [])

    def test_matches_across_coded_and_labelled_forms(self):
        sent = {"generalDetails": {"condition": {"value": "v_x", "displayName": "Pre-Owned - Good"}}}
        stored = {"generalDetails": {"condition": {"displayName": "pre owned good"}}}
        self.assertEqual(diff_roundtrip(sent, stored), [])

    def test_reports_a_field_vendoo_changed(self):
        sent = {"generalDetails": {"title": "A", "price": 10}}
        stored = {"generalDetails": {"title": "A", "price": 12}}
        diff = diff_roundtrip(sent, stored)
        self.assertEqual([entry["field"] for entry in diff], ["price"])

    def test_reports_a_field_vendoo_dropped(self):
        sent = {"generalDetails": {"sku": "ABC"}}
        diff = diff_roundtrip(sent, {"generalDetails": {}})
        self.assertEqual(diff[0]["field"], "sku")
        self.assertIsNone(diff[0]["stored"])


class ImportPayloadTest(unittest.TestCase):
    def test_shapes_the_request_body(self):
        body = import_payload([{"generalDetails": {}}], marketplace_user_id="uid-1")
        self.assertEqual(body["marketplaceId"], "vendoo")
        self.assertEqual(body["marketplaceUserId"], "uid-1")
        self.assertEqual(len(body["items"]), 1)


if __name__ == "__main__":
    unittest.main()
