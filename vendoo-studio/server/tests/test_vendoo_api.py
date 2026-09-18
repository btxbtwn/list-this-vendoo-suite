from __future__ import annotations

import unittest

from vendoo_studio.services.vendoo_api import (
    ALL_MARKETPLACES,
    CURRENT_ITEM_VERSION,
    build_vendoo_item,
    create_item_payload,
    default_listing_section,
    diff_roundtrip,
    encode_field,
    observe_item_schema,
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

IMAGES = [{"version": 3, "id": "images/u1/a.jpg", "originalMaxDimension": 1600}]

LISTING = {
    "title": "Levi's 501 Straight Jeans",
    "description": "Classic fit.",
    "price": 48.0,
    "cost": 20,
    "quantity": 1,
    "brand": "Levi's",
    "condition": "Pre-Owned - Good",
    "primaryColor": "Blue",
    "category_path": "Clothing > Men > Jeans",
    "size": "32x34",
    "sizeType": "Regular",
    "sku": "LV-501",
    "tags": ["denim", "vintage"],
    "labels": ["shelf-a"],
    "weight_lb": 1,
    "weight_oz": 8,
    "package_dimensions_in": "13x10x3",
    "internal_notes": "bin 4",
    "ebay_specifics": {"department": "Men", "fit": "Straight", "pattern": None, "shippingService": "USPSGround"},
    "poshmark_specifics": {"categoryPath": ["Men", "Jeans", "Straight"], "originalPrice": 90},
    "mercari_specifics": {"categoryPath": ["Men", "Jeans"], "shippingLabel": "USPS Ground Advantage", "smartPricing": True},
    "depop_specifics": {"style": ["Streetwear"], "source": "Preloved"},
    "etsy_specifics": {"who_made": "someone_else", "materials": ["denim"], "category_specifics": {"Pattern": "Solid"}},
}


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
        self.assertEqual(encode_field(schema, "condition", "Pre Owned Fair"), ("v_pre_owned_fair", True))

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
        self.assertEqual(encode_field(self.schema, "condition", "Salvage"), ("Salvage", False))

    def test_empty_label_is_resolved_as_nothing(self):
        self.assertEqual(encode_field(self.schema, "condition", None), (None, True))


class DefaultSectionTest(unittest.TestCase):
    def test_matches_vendoo_factory_shape(self):
        section = default_listing_section("poshmark")
        self.assertEqual(section["marketplaceID"], "poshmark")
        self.assertEqual(section["type"], "listing")
        self.assertEqual(section["status"], {"notListed": True})
        self.assertEqual(section["overrides"]["quantity"], "1")
        self.assertEqual(section["overrides"]["weight"], {"pounds": "0", "ounces": "0"})
        self.assertEqual(section["marketplaceSpecifics"], {"originalPrice": ""})
        self.assertEqual(section["sales"], [])

    def test_ebay_and_etsy_defaults(self):
        self.assertEqual(default_listing_section("ebay")["marketplaceSpecifics"]["pricingFormat"], "FixedPriceItem")
        self.assertEqual(default_listing_section("etsy")["marketplaceSpecifics"]["quantity"], 1)
        self.assertEqual(default_listing_section("depop")["overrides"], {"quantity": "1"})
        self.assertIn("listedID", default_listing_section("shopify"))


class BuildItemTest(unittest.TestCase):
    def setUp(self):
        self.schema = observe_item_schema(PROBED_ITEMS)
        self.item, self.unresolved = build_vendoo_item(
            LISTING, self.schema, images=IMAGES, user_id="u1", item_id="abc123"
        )

    def test_envelope_matches_new_item_factory(self):
        item = self.item
        self.assertEqual(item["origin"], "vendoo")
        self.assertEqual(item["version"], CURRENT_ITEM_VERSION)
        self.assertEqual(item["status"], {"notSaved": True})
        self.assertEqual(item["type"], "item")
        self.assertEqual(item["userID"], "u1")
        self.assertEqual(item["itemID"], "abc123")
        self.assertEqual(item["labels"], ["shelf-a"])
        self.assertEqual(set(item["listings"]), set(ALL_MARKETPLACES))

    def test_general_details_stored_as_form_strings(self):
        general = self.item["generalDetails"]
        self.assertEqual(general["title"], "Levi's 501 Straight Jeans")
        self.assertEqual(general["price"], "48")
        self.assertEqual(general["cost"], "20")
        self.assertEqual(general["quantity"], "1")
        self.assertEqual(general["brand"], "Levi's")
        self.assertEqual(general["sku"], "LV-501")
        self.assertEqual(general["notes"], "bin 4")
        self.assertEqual(general["tags"], ["denim", "vintage"])
        self.assertEqual(general["condition"]["value"], "v_pre_owned_good")
        self.assertEqual(general["primaryColor"]["value"], "v_blue")
        self.assertEqual(general["secondaryColor"], "")
        self.assertEqual(general["weight"], {"pounds": "1", "ounces": "8"})
        self.assertEqual(general["dimensions"], {"length": "13", "width": "10", "height": "3"})
        self.assertEqual(general["size"]["option"], {"label": "32x34", "value": "32x34"})
        self.assertEqual(general["size"]["scale"], {"label": "Regular", "value": "Regular"})
        self.assertEqual(general["images"], IMAGES)
        self.assertEqual(general["category"], "Clothing > Men > Jeans")
        self.assertNotIn("labels", general)

    def test_category_id_becomes_category_v2(self):
        item, _ = build_vendoo_item({**LISTING, "category_id": "cat_1"}, self.schema)
        self.assertEqual(item["generalDetails"]["categoryV2"], {"id": "cat_1", "displayPath": ["Clothing", "Men", "Jeans"]})
        self.assertEqual(item["generalDetails"]["category"], "")

    def test_marketplace_sections_are_filled_from_specifics(self):
        listings = self.item["listings"]
        ebay = listings["ebay"]
        self.assertEqual(ebay["marketplaceSpecifics"]["shippingService"], "USPSGround")
        self.assertEqual(ebay["categorySpecifics"], {"department": "Men", "fit": "Straight"})
        self.assertEqual(ebay["overrides"]["weight"], {"pounds": "1", "ounces": "8"})
        self.assertEqual(ebay["overrides"]["dimensions"]["length"], "13")

        posh = listings["poshmark"]
        self.assertEqual(posh["overrides"]["categoryV2"], {"displayPath": ["Men", "Jeans", "Straight"]})
        self.assertEqual(posh["marketplaceSpecifics"]["originalPrice"], "90")

        mercari = listings["mercari"]
        self.assertEqual(mercari["overrides"]["categoryV2"]["displayPath"], ["Men", "Jeans"])
        self.assertTrue(mercari["marketplaceSpecifics"]["smartPricing"])
        self.assertEqual(mercari["categorySpecifics"]["shippingLabel"], "USPS Ground Advantage")

        depop = listings["depop"]
        self.assertEqual(depop["marketplaceSpecifics"]["style"], ["Streetwear"])
        self.assertEqual(depop["marketplaceSpecifics"]["source"], ["Preloved"])

        etsy = listings["etsy"]
        self.assertEqual(etsy["marketplaceSpecifics"]["whoMade"], "someone_else")
        self.assertEqual(etsy["marketplaceSpecifics"]["materials"], ["denim"])
        self.assertEqual(etsy["categorySpecifics"], {"Pattern": "Solid"})

        self.assertEqual(listings["grailed"]["marketplaceSpecifics"], {})

    def test_unresolved_labels_are_reported_not_invented(self):
        item, unresolved = build_vendoo_item({**LISTING, "condition": "Salvage", "primaryColor": "Chartreuse"}, self.schema)
        self.assertEqual(sorted(u["field"] for u in unresolved), ["condition", "primaryColor"])
        self.assertEqual(item["generalDetails"]["condition"], "Salvage")

    def test_bare_listing_without_schema(self):
        item, unresolved = build_vendoo_item({"title": "Thing", "price": 5})
        self.assertEqual(item["generalDetails"]["title"], "Thing")
        self.assertEqual(item["generalDetails"]["price"], "5")
        self.assertEqual(item["generalDetails"]["quantity"], "1")
        self.assertEqual(unresolved, [])

    def test_create_item_payload_shape(self):
        body = create_item_payload(self.item, "v2")
        self.assertEqual(body["type"], "createItem")
        self.assertIs(body["payload"]["item"], self.item)
        self.assertEqual(body["payload"]["subscriptionVersion"], "v2")


class RoundTripTest(unittest.TestCase):
    """The serializer must survive a trip through Studio's own reader."""

    def test_import_reads_back_what_we_wrote(self):
        schema = observe_item_schema(PROBED_ITEMS)
        item, _ = build_vendoo_item(LISTING, schema, images=IMAGES)
        back = listing_from_vendoo(item, None)
        self.assertEqual(back["title"], "Levi's 501 Straight Jeans")
        self.assertEqual(back["price"], 48.0)
        self.assertEqual(back["cost"], 20.0)
        self.assertEqual(back["quantity"], 1)
        self.assertEqual(back["brand"], "Levi's")
        self.assertEqual(back["condition"], "Pre-Owned - Good")
        self.assertEqual(back["primaryColor"], "Blue")
        self.assertEqual(back["tags"], ["denim", "vintage"])
        self.assertEqual(back["labels"], ["shelf-a"])
        self.assertEqual(back["size"], "32x34")
        self.assertEqual(back["sizeType"], "Regular")
        self.assertEqual(back["weight_lb"], 1)
        self.assertEqual(back["weight_oz"], 8)
        self.assertEqual(back["package_dimensions_in"], "13x10x3")
        self.assertEqual(back["poshmark_specifics"]["originalPrice"], 90.0)
        self.assertEqual(back["ebay_specifics"]["department"], "Men")
        self.assertEqual(back["etsy_specifics"]["who_made"], "someone_else")
        self.assertEqual(back["etsy_specifics"]["category_specifics"], {"Pattern": "Solid"})


class DiffRoundTripTest(unittest.TestCase):
    def test_clean_when_vendoo_stored_what_we_sent(self):
        sent = {"generalDetails": {"title": "A", "price": "10", "images": [{"id": "x"}]}}
        stored = {"generalDetails": {"title": "A", "price": 10.0, "quantity": 1}}
        self.assertEqual(diff_roundtrip(sent, stored), [])

    def test_matches_across_coded_and_labelled_forms(self):
        sent = {"generalDetails": {"condition": {"value": "v_x", "displayName": "Pre-Owned - Good"}}}
        stored = {"generalDetails": {"condition": {"displayName": "pre owned good"}}}
        self.assertEqual(diff_roundtrip(sent, stored), [])

    def test_reports_a_field_vendoo_changed(self):
        diff = diff_roundtrip({"generalDetails": {"title": "A", "price": "10"}}, {"generalDetails": {"title": "A", "price": 12}})
        self.assertEqual([entry["field"] for entry in diff], ["price"])

    def test_reports_a_field_vendoo_dropped_but_ignores_blanks(self):
        diff = diff_roundtrip({"generalDetails": {"sku": "ABC", "notes": ""}}, {"generalDetails": {}})
        self.assertEqual([entry["field"] for entry in diff], ["sku"])


if __name__ == "__main__":
    unittest.main()
