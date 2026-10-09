from __future__ import annotations

import unittest
from unittest import mock

from vendoo_studio.models.facebook_shipping import package_weight_label
from vendoo_studio.services.vendoo_api import (
    apply_update_all,
    build_vendoo_item,
    changed_fields,
    observe_item_schema,
    vinted_measurements,
)
from vendoo_studio.services.vendoo_specifics import normalize_specifics

CARRIER = "USPS_GA:USPS Ground Advantage"
DESCRIPTION = (
    "Faded Harry Potter graphic tee.\n\n"
    'Measurements: Pit to pit: 20.5"; Length: 28"; Sleeve: 8"'
)


def _spec(name, options=()):
    return {
        "id": name,
        "display": name,
        "rules": {"fieldType": "select", "fieldOptions": {
            "minValues": 0, "maxValues": 1, "selectionMode": "SelectionOnly",
        }},
        "options": {str(i): {"id": code, "display": label} for i, (code, label) in enumerate(options)},
    }


def _seller_item(*, ounces="8", carrier=CARRIER, tier="0.5-1 lbs", package_size="2"):
    """A draft the seller finished by hand on Vendoo's Facebook and Vinted forms."""
    return {
        "generalDetails": {"weight": {"pounds": "0", "ounces": ounces}},
        "listings": {
            "facebook": {
                "overrides": {"categoryV2": {"id": "fb1"}},
                "marketplaceSpecifics": {"packageWeightLabel": tier, "carrier": carrier},
            },
            "vinted": {
                "overrides": {"categoryV2": {"id": "77"}},
                "categorySpecifics": {"77_packageSizeId": package_size},
            },
        },
    }


def _listing(**extra):
    return {
        "title": "Harry Potter Tee",
        "description": DESCRIPTION,
        "weight_lb": 0,
        "weight_oz": 8,
        "marketplace_category_objects": {"facebook": {"id": "fb1"}, "vinted": {"id": "77"}},
        **extra,
    }


class PackageWeightLabelTest(unittest.TestCase):
    def test_tiers_follow_the_weight(self):
        for ounces, label in ((4, "Under 0.5 lbs"), (7, "Under 0.5 lbs"), (8, "0.5-1 lbs"),
                              (16, "1-2 lbs"), (40, "2-5 lbs"), (159, "5-10 lbs"), (200, "")):
            with self.subTest(ounces=ounces):
                self.assertEqual(package_weight_label({"pounds": "0", "ounces": str(ounces)}), label)

    def test_a_weightless_listing_ships_as_half_a_pound(self):
        self.assertEqual(package_weight_label(None), "0.5-1 lbs")


class FacebookShippingTest(unittest.TestCase):
    def test_package_weight_and_learned_carrier_are_filled(self):
        schema = observe_item_schema([_seller_item()])
        item, unresolved = build_vendoo_item(_listing(), schema)
        specifics = item["listings"]["facebook"]["marketplaceSpecifics"]
        self.assertEqual(specifics["packageWeightLabel"], "0.5-1 lbs")
        self.assertEqual(specifics["carrier"], CARRIER)
        self.assertNotIn("facebook:Shipping carrier", [row["field"] for row in unresolved])

    def test_an_unlearned_carrier_is_reported_not_invented(self):
        item, unresolved = build_vendoo_item(_listing())
        specifics = item["listings"]["facebook"]["marketplaceSpecifics"]
        self.assertEqual(specifics["packageWeightLabel"], "0.5-1 lbs")
        self.assertNotIn("carrier", specifics)
        self.assertIn("facebook:Shipping carrier", [row["field"] for row in unresolved])

    def test_no_facebook_category_leaves_the_form_alone(self):
        item, unresolved = build_vendoo_item({"title": "Thing", "weight_oz": 8})
        self.assertEqual(item["listings"]["facebook"]["marketplaceSpecifics"], {})
        self.assertEqual(unresolved, [])

    def test_the_general_color_reaches_an_optional_category_field(self):
        specs = normalize_specifics({
            "Color": _spec("Color", [("gray", "Gray"), ("black", "Black")]),
            "Sleeve Length": _spec("Sleeve Length", [("short", "Short")]),
        })
        item, _ = build_vendoo_item(
            _listing(primaryColor="Gray", facebook_specifics={"Sleeve Length": "Short"}),
            specifics={"facebook": specs},
        )
        self.assertEqual(item["listings"]["facebook"]["categorySpecifics"], {
            "fb1_Color": "gray", "fb1_Sleeve Length": "short",
        })

    def test_update_keeps_a_carrier_the_seller_picked_on_this_draft(self):
        schema = observe_item_schema([_seller_item(carrier="UPS:UPS Ground")])
        desired, _ = build_vendoo_item(_listing(), schema)
        current = _seller_item()
        apply_update_all(current, desired, schema=schema)
        self.assertNotIn("listings.facebook.marketplaceSpecifics.carrier", changed_fields(current, desired))


class VintedPackageTest(unittest.TestCase):
    def test_measurements_come_from_the_sellers_measurements_line(self):
        self.assertEqual(vinted_measurements({"description": DESCRIPTION}), {"width": "20.5", "length": "28"})
        self.assertEqual(vinted_measurements({"description": "Measurements: See photos"}), {})

    def test_measurements_and_learned_package_size_are_filled(self):
        schema = observe_item_schema([_seller_item(ounces="10", package_size="2")])
        item, unresolved = build_vendoo_item(
            # A model's own guess never stands in for the seller's tape measure.
            _listing(vinted_specifics={"Length": "30"}), schema,
            specifics={"vinted": normalize_specifics({"Length": _spec("length")})},
        )
        specifics = item["listings"]["vinted"]["categorySpecifics"]
        self.assertEqual(specifics["77_width"], "20.5")
        self.assertEqual(specifics["77_length"], "28")
        self.assertEqual(specifics["77_packageSizeId"], "2")
        self.assertNotIn("vinted:Package Size", [row["field"] for row in unresolved])

    def test_no_typed_measurements_writes_none(self):
        item, _ = build_vendoo_item(_listing(description="Tee.", vinted_specifics={"length": "30"}))
        specifics = item["listings"]["vinted"]["categorySpecifics"]
        self.assertNotIn("77_width", specifics)
        self.assertNotIn("77_length", specifics)

    def test_package_size_is_left_for_a_heavier_item_than_any_learned(self):
        schema = observe_item_schema([_seller_item(ounces="8")])
        item, unresolved = build_vendoo_item(_listing(weight_lb=2, weight_oz=0), schema)
        self.assertNotIn("77_packageSizeId", item["listings"]["vinted"]["categorySpecifics"])
        self.assertIn("vinted:Package Size", [row["field"] for row in unresolved])

    def test_package_size_follows_the_lightest_learned_package_that_covers_it(self):
        schema = observe_item_schema([
            _seller_item(ounces="8", package_size="2"),
            _seller_item(ounces="40", package_size="3"),
        ])
        light, _ = build_vendoo_item(_listing(weight_oz=6), schema)
        heavy, _ = build_vendoo_item(_listing(weight_lb=1, weight_oz=8), schema)
        self.assertEqual(light["listings"]["vinted"]["categorySpecifics"]["77_packageSizeId"], "2")
        self.assertEqual(heavy["listings"]["vinted"]["categorySpecifics"]["77_packageSizeId"], "3")


class LearnShippingChoicesTest(unittest.TestCase):
    def test_a_hand_filled_draft_is_remembered_once(self):
        from vendoo_studio.services import vendoo_create

        saved: dict = {}
        with mock.patch.object(vendoo_create, "load_schema", side_effect=lambda: saved.get("schema")), \
                mock.patch.object(vendoo_create, "save_schema", side_effect=lambda s: saved.update(schema=s)):
            self.assertTrue(vendoo_create.learn_shipping_choices(_seller_item()))
            self.assertFalse(vendoo_create.learn_shipping_choices(_seller_item()))
        markets = saved["schema"]["marketplaces"]
        self.assertEqual(markets["facebook"]["shippingCarrier"], {"0.5-1 lbs": CARRIER})
        self.assertEqual(markets["vinted"]["packageSize"], {"8": "2"})


if __name__ == "__main__":
    unittest.main()
