from __future__ import annotations

import unittest

from vendoo_studio.services.vendoo_specifics import normalize_specifics
from vendoo_studio.services.vendoo_api import (
    apply_update_all,
    changed_fields,
    pick_mapped_category,
    ALL_MARKETPLACES,
    CURRENT_ITEM_VERSION,
    build_vendoo_item,
    category_from_hit,
    create_item_payload,
    default_listing_section,
    diff_roundtrip,
    encode_field,
    observe_item_schema,
    pick_category_hit,
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


def _spec(name, *, options=(), min_values=0, max_values=1, free_text=False):
    """One entry shaped like Vendoo's category-specifics payload."""
    built = {}
    for index, option in enumerate(options):
        code, display = option if isinstance(option, tuple) else (option, option)
        built[str(index)] = {"id": code, "display": display}
    return {
        "id": name,
        "display": name,
        "rules": {
            "fieldType": "select",
            "fieldOptions": {
                "minValues": min_values,
                "maxValues": max_values,
                "selectionMode": "FreeText" if free_text else "SelectionOnly",
            },
        },
        "options": built,
    }


class PickCategoryHitTest(unittest.TestCase):
    def test_prefers_exact_path_leaf(self):
        hits = [
            {"id": "wrong", "is_leaf": True, "path": "Women > Tops > Tees"},
            {"id": "right", "is_leaf": True, "path": "Women > Tops > Blouses"},
            {"id": "parent", "is_leaf": False, "path": "Women > Tops"},
        ]
        hit = pick_category_hit(hits, "Women > Tops > Blouses")
        self.assertEqual(hit["id"], "right")

    def test_falls_back_to_matching_leaf_name(self):
        hits = [
            {"id": "a", "is_leaf": True, "path": "Clothing > Women > Tops"},
            {"id": "b", "is_leaf": True, "path": "Other > Blouses"},
        ]
        hit = pick_category_hit(hits, "Women > Tops > Blouses")
        self.assertEqual(hit["id"], "b")


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
        self.assertEqual(section["marketplaceSpecifics"], {
            "originalPrice": "",
            "smartSell": {"enabled": True, "minPrice": "5"},
        })
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
        # Vendoo's own save replaces the factory's "notSaved" with complete or
        # inProgress; creating one and leaving it notSaved is what made every
        # marketplace form read as untouched.
        self.assertEqual(item["status"], {"complete": True})
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

    def test_a_created_item_is_marked_saved_and_its_forms_stamped(self):
        item, unresolved = build_vendoo_item(
            {**LISTING, "category_id": "cat_1", "marketplace_category_ids": {"ebay": "53159"}},
            self.schema,
        )
        self.assertEqual(item["status"], {"complete": True})
        ebay = item["listings"]["ebay"]
        # A form that was filled carries the dates a save writes.
        self.assertIn("_seconds", ebay["dateCreated"])
        self.assertEqual(ebay["dateCreated"], ebay["dateLastModified"])
        # One nobody touched is left alone.
        self.assertEqual(item["listings"]["vinted"]["dateLastModified"], "")

    def test_an_item_with_nothing_unresolved_claims_complete(self):
        item, unresolved = build_vendoo_item(
            {"title": "Tee", "category_path": "Clothing > Tops"}, self.schema,
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(item["status"], {"complete": True})

    def test_category_id_becomes_category_v2(self):
        item, _ = build_vendoo_item({**LISTING, "category_id": "cat_1"}, self.schema)
        self.assertEqual(item["generalDetails"]["categoryV2"], {"id": "cat_1", "displayPath": ["Clothing", "Men", "Jeans"]})
        self.assertIsNone(item["generalDetails"]["category"])

    def test_marketplace_sections_are_filled_from_specifics(self):
        listings = self.item["listings"]
        ebay = listings["ebay"]
        self.assertEqual(ebay["marketplaceSpecifics"]["shippingService"], "USPSGround")
        self.assertEqual(ebay["categorySpecifics"], {})
        self.assertEqual(ebay["overrides"]["weight"], {"pounds": "1", "ounces": "8"})
        self.assertEqual(ebay["overrides"]["dimensions"]["length"], "13")

        posh = listings["poshmark"]
        self.assertEqual(posh["overrides"]["categoryV2"], {"displayPath": ["Men", "Jeans", "Straight"]})
        self.assertEqual(posh["marketplaceSpecifics"]["originalPrice"], "90")

        mercari = listings["mercari"]
        self.assertEqual(mercari["overrides"]["categoryV2"]["displayPath"], ["Men", "Jeans"])
        self.assertTrue(mercari["marketplaceSpecifics"]["smartPricing"])
        self.assertEqual(mercari["categorySpecifics"], {})
        # LISTING is 1 lb 8 oz — the 2 lb Ground Advantage tier.
        self.assertEqual(
            mercari["marketplaceSpecifics"]["shipping"]["carrierId"],
            "2511",
        )

        depop = listings["depop"]
        # Vendoo's Depop mapper keeps only its option codes, never labels.
        self.assertEqual(depop["marketplaceSpecifics"]["style"], ["streetwear"])
        self.assertEqual(depop["marketplaceSpecifics"]["source"], ["preloved"])
        self.assertEqual(depop["overrides"]["brand"], "Levi's")
        self.assertEqual(ebay["overrides"]["brand"], "Levi's")
        self.assertEqual(mercari["overrides"]["brand"], "Levi's")
        self.assertFalse(mercari["overrides"].get("noBrand"))
        fixed = ebay["marketplaceSpecifics"]["pricingFormatDetails"]["fixedPrice"]
        self.assertEqual(ebay["marketplaceSpecifics"]["pricingFormat"], "FixedPriceItem")
        self.assertTrue(fixed["allowBestOffer"])
        self.assertEqual(fixed["buyItNowPrice"], "48")
        self.assertEqual(fixed["acceptOffersOfAtLeast"], "19")
        self.assertEqual(posh["marketplaceSpecifics"]["smartSell"], {"enabled": True, "minPrice": "5"})
        etsy = listings["etsy"]
        self.assertEqual(etsy["marketplaceSpecifics"]["whoMade"], "someone_else")
        self.assertEqual(etsy["marketplaceSpecifics"]["whatIsIt"], "0")
        self.assertEqual(etsy["marketplaceSpecifics"]["whenMade"], "2020_2026")
        self.assertEqual(etsy["marketplaceSpecifics"]["materials"], ["denim"])
        self.assertEqual(etsy["categorySpecifics"], {})
        self.assertEqual(etsy["overrides"]["brand"], "Levi's")

        self.assertEqual(listings["grailed"]["marketplaceSpecifics"], {})

    def test_depop_style_age_source_use_vendoo_codes(self):
        item, unresolved = build_vendoo_item({
            "title": "Tee",
            "depop_specifics": {
                "style": ["Y2K", "Avant Garde", "Utility", "Nonsense"],
                "age": "Y2K",
                "source": "vintage",
            },
        }, self.schema)
        specifics = item["listings"]["depop"]["marketplaceSpecifics"]
        self.assertEqual(specifics["style"], ["y2_k", "avant_garde", "techwear"])
        self.assertEqual(specifics["age"], ["y2k"])
        self.assertEqual(specifics["source"], ["vintage"])
        self.assertIn({"field": "depop:style", "value": "Nonsense"}, unresolved)

        back = listing_from_vendoo(item, None)["depop_specifics"]
        self.assertEqual(back["style"], ["Y2K", "Avant Garde", "Utility"])
        self.assertEqual(back["source"], "Vintage")
        self.assertEqual(back["age"], "y2k")

    def test_unbranded_sets_ebay_brand_and_mercari_no_brand(self):
        item, _ = build_vendoo_item({
            "title": "Plain tee",
            "brand": "Unbranded",
            "depop_specifics": {"style": ["Casual", "Retro", "Boho"]},
            "mercari_specifics": {"shippingLabel": "USPS Ground Advantage"},
        }, self.schema)
        self.assertEqual(item["generalDetails"]["brand"], "Unbranded")
        self.assertEqual(item["listings"]["ebay"]["overrides"]["brand"], "Unbranded")
        # Lowercased ebay_specifics must not win over the Unbranded label.
        item2, _ = build_vendoo_item({
            "title": "Plain tee",
            "brand": "Unbranded",
            "ebay_specifics": {"brand": "unbranded"},
        }, self.schema)
        self.assertEqual(item2["listings"]["ebay"]["overrides"]["brand"], "Unbranded")

        mercari = item["listings"]["mercari"]
        self.assertTrue(mercari["overrides"].get("noBrand"))
        self.assertNotIn("brand", mercari["overrides"])
        # No weight on this listing: the half-pound tier it always ships as.
        self.assertEqual(mercari["marketplaceSpecifics"]["shipping"]["carrierId"], "2508")
        self.assertIn("Ground Advantage", mercari["marketplaceSpecifics"]["shippingLabel"])
        self.assertEqual(
            item["listings"]["depop"]["marketplaceSpecifics"]["style"],
            ["casual", "retro", "boho"],
        )
        self.assertEqual(item["listings"]["depop"]["overrides"]["brand"], "Other")
        posh = item["listings"]["poshmark"]["marketplaceSpecifics"]["smartSell"]
        self.assertEqual(posh, {"enabled": True, "minPrice": "5"})
        etsy = item["listings"]["etsy"]["marketplaceSpecifics"]
        self.assertEqual(etsy["whoMade"], "someone_else")
        self.assertEqual(etsy["whatIsIt"], "0")

    def test_mercari_shipping_label_follows_the_weight(self):
        # Vendoo's form only offers the tiers that carry the package, so a tier
        # that is too small for the weight shows as an empty Shipping Label.
        for pounds, ounces, carrier, price in (
            (0, 3, "2507", "5.87"),
            (0, 8, "2508", "6.41"),
            (0, 12, "2509", "7.48"),
            (1, 0, "2510", "8.12"),
            (2, 0, "2511", "14.43"),
            (None, None, "2508", "6.41"),
        ):
            with self.subTest(pounds=pounds, ounces=ounces):
                item, _ = build_vendoo_item({
                    "title": "Tee",
                    "weight_lb": pounds,
                    "weight_oz": ounces,
                }, self.schema)
                mercari = item["listings"]["mercari"]["marketplaceSpecifics"]
                self.assertEqual(mercari["shipping"]["carrierId"], carrier)
                self.assertIn(f"$ {price}", mercari["shippingLabel"])
                self.assertEqual(mercari["shipping"]["deliveryMethod"], "mercari_shipping")

    def test_etsy_is_live_and_inherits_general_tags(self):
        tags = [f"tag{i}" for i in range(15)] + ["a tag far longer than twenty"]
        item, _ = build_vendoo_item({
            "title": "Tee",
            "tags": tags,
            "etsy_specifics": {"listing_state": "Draft Listing", "listingState": "draft"},
        }, self.schema)
        etsy = item["listings"]["etsy"]["marketplaceSpecifics"]
        self.assertEqual(etsy["listingState"], "active")
        self.assertEqual(etsy["tags"], tags[:13])
        self.assertEqual(item["generalDetails"]["tags"], tags)

    def test_etsy_display_labels_become_form_codes(self):
        item, _ = build_vendoo_item({
            "title": "Tee",
            "price": 16,
            "etsy_specifics": {
                "who_made": "Another company or person",
                "what_is": "A finished product",
                "when_made": "2020 - 2026 (Recently)",
            },
        }, self.schema)
        etsy = item["listings"]["etsy"]["marketplaceSpecifics"]
        self.assertEqual(etsy["whoMade"], "someone_else")
        self.assertEqual(etsy["whatIsIt"], "0")
        self.assertEqual(etsy["whenMade"], "2020_2026")
        self.assertEqual(etsy["listingState"], "active")
        fixed = item["listings"]["ebay"]["marketplaceSpecifics"]["pricingFormatDetails"]["fixedPrice"]
        self.assertTrue(fixed["allowBestOffer"])
        self.assertEqual(fixed["buyItNowPrice"], "16")
        self.assertEqual(fixed["acceptOffersOfAtLeast"], "6")

    def test_empty_brand_checks_mercari_no_brand(self):
        item, _ = build_vendoo_item({"title": "Tee", "brand": ""}, self.schema)
        mercari = item["listings"]["mercari"]
        self.assertTrue(mercari["overrides"].get("noBrand"))
        self.assertNotIn("brand", mercari["overrides"])
        self.assertNotIn("brand", item["listings"]["ebay"]["overrides"])

    def test_marketplace_categories_string_sets_category_v2(self):
        item, _ = build_vendoo_item({
            "title": "Top",
            "marketplace_categories": {
                "ebay": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
                "poshmark": "Women > Tops > Blouses",
            },
            "marketplace_category_ids": {"ebay": "ebay_tops_1", "poshmark": "posh_blouses"},
        })
        ebay = item["listings"]["ebay"]["overrides"]["categoryV2"]
        self.assertEqual(ebay["id"], "ebay_tops_1")
        self.assertEqual(ebay["displayPath"][-1], "Tops")
        posh = item["listings"]["poshmark"]["overrides"]["categoryV2"]
        self.assertEqual(posh, {"id": "posh_blouses", "displayPath": ["Women", "Tops", "Blouses"]})

    def test_ebay_aspects_use_vendoos_schema_for_the_leaf(self):
        """Vendoo's schema decides the keys, the list shapes and the codes."""
        specs = normalize_specifics({
            "Department": _spec("Department", options=["Women", "Men"], min_values=1),
            "Size": _spec("Size", free_text=True, min_values=1),
            "Size Type": _spec("Size Type", options=["Regular", "Petite"], min_values=1),
            "Type": _spec("Type", free_text=True, min_values=1),
            "Season": _spec("Season", options=["Spring", "Fall"], max_values=100),
            "Occasion": _spec("Occasion", options=["Casual"], max_values=100),
            "upc": _spec("upc", free_text=True),
            "condition": _spec(
                "condition",
                options=[("3000", "Pre-owned - Good"), ("1000", "New with tags")],
                min_values=1,
            ),
        })
        item, unresolved = build_vendoo_item(
            {
                "title": "Top",
                "condition": "Pre-Owned - Good",
                "size": "M",
                "sizeType": "Regular",
                "marketplace_categories": {
                    "ebay": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
                },
                "marketplace_category_ids": {"ebay": "53159"},
                "ebay_specifics": {
                    "department": "Women",
                    "type": "Top",
                    "season": "Spring",
                    "occasion": "Casual",
                    "upc": "Does Not Apply",
                    "conditionDescription": "Good condition.",
                },
            },
            specifics={"ebay": specs},
        )
        ebay = item["listings"]["ebay"]
        self.assertEqual(ebay["overrides"]["categoryV2"]["id"], "53159")
        stored = ebay["categorySpecifics"]
        self.assertEqual(stored["53159_Department"], "Women")
        self.assertEqual(stored["53159_Size"], "M")
        self.assertEqual(stored["53159_Size Type"], "Regular")
        self.assertEqual(stored["53159_Type"], "Top")
        # The listing keeps "Does Not Apply"; the form field is pushed blank.
        self.assertEqual(stored["53159_upc"], "")
        # maxValues > 1 means Vendoo stores a list, and a bare string there is
        # what breaks the form.
        self.assertEqual(stored["53159_Season"], ["Spring"])
        self.assertEqual(stored["53159_Occasion"], ["Casual"])
        # Condition is eBay's own id, in both places the form reads it from.
        self.assertEqual(ebay["overrides"]["condition"], "3000")
        self.assertEqual(stored["53159_condition"], "3000")
        self.assertNotIn("department", stored)
        self.assertEqual(ebay["marketplaceSpecifics"]["conditionDescription"], "Good condition.")
        # Nothing about the eBay leaf is left unresolved; generalDetails still
        # reports its own condition because no learned schema was passed.
        self.assertEqual([row for row in unresolved if "ebay" in row["field"]], [])

    def test_selection_only_value_is_reported_not_stored(self):
        """A value the leaf has no option for must never reach Vendoo."""
        specs = normalize_specifics({
            "Department": _spec("Department", options=["Women", "Men"]),
        })
        item, unresolved = build_vendoo_item(
            {
                "title": "Top",
                "marketplace_category_ids": {"ebay": "53159"},
                "marketplace_categories": {"ebay": "Clothing > Tops"},
                "ebay_specifics": {"department": "Womens Petite"},
            },
            specifics={"ebay": specs},
        )
        stored = item["listings"]["ebay"]["categorySpecifics"]
        self.assertNotIn("53159_Department", stored)
        self.assertIn(
            {"field": "ebay:Department", "value": "Womens Petite"}, unresolved
        )

    def test_without_vendoos_schema_nothing_is_invented(self):
        """No schema for the leaf means no guessed aspect keys."""
        item, _ = build_vendoo_item({
            "title": "Top",
            "size": "M",
            "marketplace_category_ids": {"ebay": "53159"},
            "marketplace_categories": {"ebay": "Clothing > Tops"},
            "ebay_specifics": {"department": "Women", "season": "Spring"},
        })
        self.assertEqual(item["listings"]["ebay"]["categorySpecifics"], {})

    def test_ebay_condition_needs_ebays_own_code(self):
        """A Vendoo label in ``overrides.condition`` is what crashes the form."""
        listing = {
            "title": "Top",
            "condition": "Pre-Owned - Good",
            "marketplace_categories": {"ebay": "Clothing > Women > Tops"},
            "marketplace_category_ids": {"ebay": "53159"},
        }
        item, unresolved = build_vendoo_item(listing)
        ebay = item["listings"]["ebay"]
        self.assertNotIn("condition", ebay["overrides"])
        self.assertNotIn("53159_condition", ebay["categorySpecifics"])
        self.assertIn("condition:ebay", [u["field"] for u in unresolved])

        learned = observe_item_schema([{
            "generalDetails": {"condition": "v_preowned"},
            "listings": {"ebay": {
                "overrides": {"condition": "3000", "categoryV2": {"id": "53159"}},
                "categorySpecifics": {"53159_condition": "3000"},
            }},
        }])
        item, unresolved = build_vendoo_item({**listing, "condition": "v_preowned"}, learned)
        ebay = item["listings"]["ebay"]
        self.assertEqual(ebay["overrides"]["condition"], "3000")
        self.assertEqual(ebay["categorySpecifics"]["53159_condition"], "3000")
        self.assertEqual([u["field"] for u in unresolved], [])

    def test_multi_select_aspects_are_stored_as_lists(self):
        learned = observe_item_schema([{
            "listings": {"ebay": {
                "overrides": {"categoryV2": {"id": "53159"}},
                "categorySpecifics": {"53159_Season": ["Spring"], "53159_Department": "Women"},
            }},
        }])
        item, _ = build_vendoo_item({
            "title": "Top",
            "marketplace_categories": {"ebay": "Clothing > Women > Tops"},
            "marketplace_category_ids": {"ebay": "53159"},
            "ebay_specifics": {"season": "Spring", "department": "Women"},
        }, learned)
        specs = item["listings"]["ebay"]["categorySpecifics"]
        self.assertEqual(specs["53159_Season"], ["Spring"])
        self.assertEqual(specs["53159_Department"], "Women")

    def test_resolved_category_object_is_kept_whole(self):
        """The eBay form reads ``path`` and ``extras.siteId``; both must survive."""
        hit = {
            "id": "53159",
            "is_leaf": True,
            "has_children": False,
            "last_subcategory_label": "Tops",
            "all_category_label": ["Clothing, Shoes & Accessories", "Women", "Tops"],
            "parent_category_id_path": ["11450", "260010", "15724"],
            "payload_text": '{"siteId": "0"}',
        }
        resolved = category_from_hit(hit)
        self.assertEqual(resolved, {
            "id": "53159",
            "displayPath": ["Clothing, Shoes & Accessories", "Women", "Tops"],
            "displayName": "Tops",
            "isLeaf": True,
            "hasChildren": False,
            "path": ["11450", "260010", "15724", "53159"],
            "extras": {"siteId": "0"},
        })
        item, _ = build_vendoo_item({
            "title": "Top",
            "marketplace_category_objects": {"ebay": resolved, "general": resolved},
        })
        self.assertEqual(item["listings"]["ebay"]["overrides"]["categoryV2"], resolved)
        self.assertEqual(item["generalDetails"]["categoryV2"], resolved)

    def test_string_category_path_in_specifics(self):
        item, _ = build_vendoo_item({
            "title": "Top",
            "etsy_specifics": {"categoryPath": "Clothing > Women's Clothing > Tops & Tees > Blouses"},
        })
        self.assertEqual(
            item["listings"]["etsy"]["overrides"]["categoryV2"]["displayPath"],
            ["Clothing", "Women's Clothing", "Tops & Tees", "Blouses"],
        )

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
        self.assertNotIn("department", back.get("ebay_specifics") or {})
        self.assertEqual(back["etsy_specifics"]["who_made"], "someone_else")
        self.assertNotIn("category_specifics", back.get("etsy_specifics") or {})
        self.assertEqual(back["depop_specifics"]["style"], ["Streetwear"])


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


class GeneralFormFieldsTest(unittest.TestCase):
    """The general form feeds every marketplace, so its own fields must be
    stored the way Vendoo stores them. Shapes taken from real saved items."""

    LISTING = {
        "title": "Cat Graphic Tee",
        "size": "XL",
        "sizeType": "Regular",
        "primaryColor": "Beige",
        "secondaryColor": "Pink",
        "category_id": "clothing_shoes__accessories__women__women's_clothing__tops",
        "category_path": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
    }

    def build(self, **over):
        listing = {**self.LISTING, **over}
        return build_vendoo_item(listing)

    def test_size_carries_the_category_it_belongs_to(self):
        item, _ = self.build()
        size = item["generalDetails"]["size"]
        self.assertEqual(size["option"], {"label": "XL", "value": "XL"})
        self.assertEqual(size["scale"], {"label": "Regular", "value": "Regular"})
        # Without categoryId the form has no scale to read the option against.
        self.assertEqual(size["categoryId"], self.LISTING["category_id"])

    def test_colours_use_vendoos_vocabulary_not_the_words(self):
        item, unresolved = self.build()
        general = item["generalDetails"]
        self.assertEqual(general["primaryColor"], "v_Beige")
        self.assertEqual(general["secondaryColor"], "v_Pink")
        # A colour Vendoo ships is not something to report as unencodable.
        self.assertEqual([r for r in unresolved if "Color" in r["field"]], [])

    def test_a_colour_vendoo_does_not_ship_is_reported(self):
        _item, unresolved = self.build(primaryColor="Chartreuse")
        self.assertEqual(
            [r["field"] for r in unresolved if r["value"] == "Chartreuse"], ["primaryColor"]
        )

    def test_size_without_a_category_omits_the_key(self):
        item, _ = self.build(category_id="", category_path="")
        self.assertNotIn("categoryId", item["generalDetails"]["size"])


class MappedCategoryTest(unittest.TestCase):
    """Vendoo's mapper offers alternates; its first answer is not always best."""

    GENERAL = {"displayPath": [
        "Clothing, Shoes & Accessories", "Kids", "Girls",
        "Girls' Clothing (Sizes 4 & Up)", "Tops, Shirts & T-Shirts",
    ]}

    def hit(self, cid, labels):
        return {"id": cid, "all_category_label": labels}

    def test_the_wrong_gender_loses_to_the_right_one(self):
        # Real answer for a girls' tee: eBay matched Boys', with Girls' among
        # the alternates. Boys' Department offers no "Girls" at all.
        match = self.hit("260966", ["Clothing, Shoes & Accessories", "Kids", "Boys",
                                    "Boys' Clothing (Sizes 4 & Up)", "Tops, Shirts & T-Shirts"])
        recs = [self.hit("260965", ["Clothing, Shoes & Accessories", "Kids", "Girls",
                                    "Girls' Clothing (Sizes 4 & Up)", "Tops, Shirts & T-Shirts"])]
        self.assertEqual(pick_mapped_category(self.GENERAL, match, recs)["id"], "260965")

    def test_the_wrong_garment_loses_to_the_right_one(self):
        # Etsy matched Tanks, whose Sleeve length offers only "Sleeveless".
        match = self.hit("11142", ["Clothing", "Girls' Clothing", "Tops & Tees", "Tanks"])
        recs = [self.hit("11143", ["Clothing", "Girls' Clothing", "Tops & Tees", "T-shirts"])]
        self.assertEqual(pick_mapped_category(self.GENERAL, match, recs)["id"], "11143")

    def test_tank_tops_does_not_beat_tees_for_womens_tops(self):
        """Parent-echo scoring used to give Tank Tops a leaf hit on bare Tops."""
        general = {"displayPath": [
            "Clothing, Shoes & Accessories", "Women", "Women's Clothing", "Tops",
        ]}
        match = self.hit("tank", ["Women", "Tops", "Tank Tops"])
        recs = [self.hit("tee", ["Women", "Tops", "Tees - Short Sleeve"])]
        self.assertEqual(pick_mapped_category(general, match, recs)["id"], "tee")

    def test_real_tank_match_stands_when_general_names_tank(self):
        general = {"displayPath": [
            "Clothing, Shoes & Accessories", "Women", "Women's Clothing", "Tops", "Tank Tops",
        ]}
        match = self.hit("tank", ["Women", "Tops", "Tank Tops"])
        recs = [self.hit("tee", ["Women", "Tops", "Tees - Short Sleeve"])]
        self.assertEqual(pick_mapped_category(general, match, recs)["id"], "tank")

    def test_the_match_keeps_a_tie(self):
        """Only override Vendoo when something genuinely fits better."""
        match = self.hit("a", ["Clothing", "Girls' Clothing", "Tops & Tees", "T-shirts"])
        recs = [self.hit("b", ["Clothing", "Girls' Clothing", "Tops & Tees", "T-shirts"])]
        self.assertEqual(pick_mapped_category(self.GENERAL, match, recs)["id"], "a")

    def test_no_answer_at_all_is_none(self):
        self.assertIsNone(pick_mapped_category(self.GENERAL, None, []))

    def test_without_a_general_path_the_match_stands(self):
        match = self.hit("a", ["Anything"])
        self.assertEqual(pick_mapped_category({}, match, [self.hit("b", ["Other"])])["id"], "a")


class ChangedFieldsTest(unittest.TestCase):
    """A save writes the fields that differ, and nothing else."""

    CURRENT = {
        "generalDetails": {"title": "Old", "brand": "GB Girls", "price": "15"},
        "listings": {
            "ebay": {
                "overrides": {"title": "Old", "condition": "3000"},
                "categorySpecifics": {"53159_Size Type": "Regular"},
                "marketplaceSpecifics": {"shippingPolicyId": 253383644010},
            },
        },
    }

    def desired(self, **over):
        item = {
            "generalDetails": {"title": "New", "brand": "GB Girls", "price": "15"},
            "listings": {
                "ebay": {
                    "overrides": {"title": "New", "condition": "3000"},
                    "categorySpecifics": {"53159_Size Type": "Regular", "53159_Season": ["Spring"]},
                    "marketplaceSpecifics": {"shippingPolicyId": ""},
                },
            },
        }
        item.update(over)
        return item

    def test_only_differing_paths_are_written(self):
        out = changed_fields(self.CURRENT, self.desired())
        self.assertEqual(sorted(out), [
            "generalDetails.title",
            "listings.ebay.categorySpecifics.53159_Season",
            "listings.ebay.overrides.title",
        ])
        self.assertEqual(out["generalDetails.title"], "New")
        self.assertEqual(out["listings.ebay.categorySpecifics.53159_Season"], ["Spring"])

    def test_an_empty_desired_value_never_clears_vendoo(self):
        """Studio not knowing something is not the seller erasing it."""
        out = changed_fields(self.CURRENT, self.desired())
        self.assertNotIn("listings.ebay.marketplaceSpecifics.shippingPolicyId", out)

    def test_fields_vendoo_owns_are_untouched(self):
        current = {**self.CURRENT, "status": {"complete": True}, "itemID": "abc"}
        out = changed_fields(current, self.desired())
        self.assertEqual([p for p in out if p.startswith(("status", "itemID", "dateCreated"))], [])

    def test_labels_are_added_to_the_ones_already_on_the_item(self):
        current = {**self.CURRENT, "labels": ["idSeller"]}
        out = changed_fields(current, self.desired(labels=["idToList", "idSeller"]))
        self.assertEqual(out["labels"], ["idSeller", "idToList"])

    def test_labels_already_on_the_item_write_nothing(self):
        current = {**self.CURRENT, "labels": ["idToList", "idSeller"]}
        self.assertNotIn("labels", changed_fields(current, self.desired(labels=["idToList"])))

    def test_nothing_to_do_writes_nothing(self):
        item = {
            "generalDetails": dict(self.CURRENT["generalDetails"]),
            "listings": {"ebay": {k: dict(v) for k, v in self.CURRENT["listings"]["ebay"].items()}},
        }
        self.assertEqual(changed_fields(self.CURRENT, item), {})

    def test_a_does_not_apply_already_on_the_draft_is_cleared(self):
        """The form shows the phrase verbatim, so this one empty is pushed."""
        current = {
            "generalDetails": {"title": "Old"},
            "listings": {"ebay": {"categorySpecifics": {
                "53159_upc": "Does Not Apply", "53159_Theme": ["N/A"],
            }}},
        }
        desired = {
            "generalDetails": {"title": "Old"},
            "listings": {"ebay": {"categorySpecifics": {
                "53159_upc": "", "53159_Theme": [],
            }}},
        }
        out = changed_fields(current, desired)
        self.assertEqual(out["listings.ebay.categorySpecifics.53159_upc"], "")
        self.assertEqual(out["listings.ebay.categorySpecifics.53159_Theme"], [])

    def test_brand_case_is_significant(self):
        """eBay's Brand dropdown matches Unbranded, not lowercased free text."""
        current = {
            "generalDetails": {"brand": "Unbranded"},
            "listings": {"ebay": {"overrides": {"brand": "unbranded"}}},
        }
        desired = {
            "generalDetails": {"brand": "Unbranded"},
            "listings": {"ebay": {"overrides": {"brand": "Unbranded"}}},
        }
        out = changed_fields(current, desired)
        self.assertEqual(out.get("listings.ebay.overrides.brand"), "Unbranded")

    def test_depop_codes_replace_stored_labels(self):
        """Drafts saved with labels must be rewritten; Depop rejects "Modern"."""
        current = {"listings": {"depop": {"marketplaceSpecifics": {
            "age": ["Modern"], "source": ["Preloved"], "style": ["Casual", "Avant Garde"],
        }}}}
        desired = {"listings": {"depop": {"marketplaceSpecifics": {
            "age": ["modern"], "source": ["preloved"], "style": ["casual", "avant_garde"],
        }}}}
        out = changed_fields(current, desired)
        prefix = "listings.depop.marketplaceSpecifics."
        self.assertEqual(out[prefix + "age"], ["modern"])
        self.assertEqual(out[prefix + "source"], ["preloved"])
        self.assertEqual(out[prefix + "style"], ["casual", "avant_garde"])
        self.assertEqual(changed_fields(desired, desired), {})


class ApplyUpdateAllTest(unittest.TestCase):
    """A save pushes general-form edits onto marketplace copies, like Update All."""

    def test_title_description_and_price_copy_onto_marketplace_overrides(self):
        current = {
            "generalDetails": {"title": "Old", "description": "Old desc", "price": "20"},
            "listings": {
                "ebay": {"overrides": {"title": "Old eBay title"}},
                "poshmark": {"overrides": {"title": "Old Posh title", "price": "20"}},
            },
        }
        desired = {
            "generalDetails": {"title": "New", "description": "New desc", "price": "15"},
            "listings": {
                "ebay": {"overrides": {"quantity": "1"}},
                "poshmark": {"overrides": {"quantity": "1"}},
            },
        }
        apply_update_all(current, desired)
        self.assertEqual(desired["listings"]["ebay"]["overrides"]["title"], "New")
        self.assertEqual(desired["listings"]["ebay"]["overrides"]["description"], "New desc")
        self.assertEqual(desired["listings"]["poshmark"]["overrides"]["title"], "New")
        self.assertEqual(desired["listings"]["poshmark"]["overrides"]["description"], "New desc")
        self.assertEqual(desired["listings"]["poshmark"]["overrides"]["price"], "15")
        self.assertEqual(
            desired["listings"]["ebay"]["marketplaceSpecifics"]["pricingFormatDetails"]["fixedPrice"]["buyItNowPrice"],
            "15",
        )
        out = changed_fields(current, desired)
        self.assertEqual(out["listings.ebay.overrides.title"], "New")
        self.assertEqual(out["listings.poshmark.overrides.price"], "15")
        self.assertEqual(
            out["listings.ebay.marketplaceSpecifics.pricingFormatDetails.fixedPrice.buyItNowPrice"],
            "15",
        )

    def test_tags_and_condition_copy_onto_each_marketplace(self):
        current = {
            "generalDetails": {
                "title": "Old",
                "tags": ["old"],
                "condition": "v_preowned",
                "price": "20",
            },
            "listings": {
                "ebay": {
                    "marketplaceID": "ebay",
                    "overrides": {"condition": "3000"},
                    "categorySpecifics": {"53159_condition": "3000"},
                    "marketplaceSpecifics": {},
                },
                "etsy": {
                    "marketplaceID": "etsy",
                    "overrides": {"condition": "used_excellent"},
                    "marketplaceSpecifics": {"tags": ["old"]},
                },
                "poshmark": {
                    "marketplaceID": "poshmark",
                    "overrides": {"condition": "nwt", "price": "20"},
                },
                "mercari": {
                    "marketplaceID": "mercari",
                    "overrides": {"condition": "3"},
                    "marketplaceSpecifics": {"tags": ["old"]},
                },
                "depop": {
                    "marketplaceID": "depop",
                    "overrides": {"condition": "used_excellent", "price": "20"},
                },
            },
        }
        desired = {
            "generalDetails": {
                "title": "New",
                "tags": ["denim", "vintage"],
                "condition": "v_good",
                "price": "15",
            },
            "listings": {
                "ebay": {"marketplaceID": "ebay", "overrides": {"condition": "4000"}},
                "etsy": {"marketplaceID": "etsy", "overrides": {"condition": "used_good"}},
                "poshmark": {"marketplaceID": "poshmark", "overrides": {"condition": "good"}},
                "mercari": {"marketplaceID": "mercari", "overrides": {"condition": "4"}},
                "depop": {"marketplaceID": "depop", "overrides": {"condition": "used_good"}},
            },
        }
        apply_update_all(current, desired)
        ebay = desired["listings"]["ebay"]
        self.assertEqual(ebay["overrides"]["tags"], ["denim", "vintage"])
        self.assertEqual(ebay["overrides"]["condition"], "4000")
        self.assertEqual(ebay["categorySpecifics"]["53159_condition"], "4000")
        self.assertEqual(
            ebay["marketplaceSpecifics"]["pricingFormatDetails"]["fixedPrice"]["buyItNowPrice"],
            "15",
        )
        etsy = desired["listings"]["etsy"]
        self.assertEqual(etsy["overrides"]["tags"], ["denim", "vintage"])
        self.assertEqual(etsy["overrides"]["condition"], "used_good")
        self.assertEqual(etsy["marketplaceSpecifics"]["tags"], ["denim", "vintage"])
        self.assertEqual(etsy["overrides"]["price"], "15")
        self.assertEqual(desired["listings"]["poshmark"]["overrides"]["condition"], "good")
        self.assertEqual(desired["listings"]["poshmark"]["overrides"]["price"], "15")
        self.assertEqual(desired["listings"]["mercari"]["overrides"]["condition"], "4")
        self.assertEqual(desired["listings"]["mercari"]["marketplaceSpecifics"]["tags"], ["denim", "vintage"])
        self.assertEqual(desired["listings"]["depop"]["overrides"]["condition"], "used_good")
        self.assertEqual(desired["listings"]["depop"]["overrides"]["price"], "15")
        out = changed_fields(current, desired)
        self.assertEqual(out["listings.ebay.overrides.condition"], "4000")
        self.assertEqual(out["listings.ebay.categorySpecifics.53159_condition"], "4000")
        self.assertEqual(out["listings.etsy.marketplaceSpecifics.tags"], ["denim", "vintage"])
        self.assertEqual(out["listings.poshmark.overrides.price"], "15")

    def test_ebay_does_not_receive_the_general_vendoo_condition_label(self):
        current = {
            "generalDetails": {"condition": "v_preowned"},
            "listings": {"ebay": {"marketplaceID": "ebay", "overrides": {"condition": "3000"}}},
        }
        desired = {
            "generalDetails": {"condition": "Pre-Owned - Good"},
            "listings": {"ebay": {"marketplaceID": "ebay", "overrides": {}}},
        }
        apply_update_all(current, desired)
        self.assertEqual(desired["listings"]["ebay"]["overrides"].get("condition"), None)

    def test_marketplaces_absent_from_the_item_are_left_alone(self):
        current = {"generalDetails": {"title": "Old"}, "listings": {}}
        desired = {
            "generalDetails": {"title": "New"},
            "listings": {"ebay": {"overrides": {"quantity": "1"}}},
        }
        apply_update_all(current, desired)
        self.assertNotIn("title", desired["listings"]["ebay"]["overrides"])


if __name__ == "__main__":
    unittest.main()
