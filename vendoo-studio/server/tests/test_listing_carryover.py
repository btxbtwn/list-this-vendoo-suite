from __future__ import annotations

import unittest

from vendoo_studio.services.listing_carryover import (
    carryover_updates,
    description_block,
    set_description_block,
)


DESCRIPTION = (
    "Cozy oversized grunge flannel.\n\n"
    "Flaws: small stain near the hem and a loose button.\n\n"
    'Measurements: Pit to pit 20"; Length 27"'
)


class DescriptionBlockTest(unittest.TestCase):
    def test_reads_block_up_to_the_next_marker(self):
        self.assertEqual(
            description_block(DESCRIPTION, "flaws?"),
            "small stain near the hem and a loose button",
        )

    def test_reads_last_block_to_the_end(self):
        self.assertEqual(
            description_block(DESCRIPTION, "measurements?"),
            'Pit to pit 20"; Length 27"',
        )

    def test_missing_block_is_empty(self):
        self.assertEqual(description_block("Just vibes.", "flaws?"), "")
        self.assertEqual(description_block(None, "flaws?"), "")


    def test_reads_measurements_written_one_per_line(self):
        description = (
            "Cozy flannel.\n\nMeasurements:\n"
            'Pit to pit: 22"\nLength: 27"\nSleeve: 25"\nCondition: good'
        )
        self.assertEqual(
            description_block(description, "measurements?"),
            'Pit to pit: 22"; Length: 27"; Sleeve: 25"',
        )

    def test_set_block_replaces_in_place(self):
        self.assertEqual(
            set_description_block(DESCRIPTION, "measurements?", 'Measurements: Length 28"'),
            "Cozy oversized grunge flannel.\n\n"
            "Flaws: small stain near the hem and a loose button.\n\n"
            'Measurements: Length 28"',
        )

    def test_set_block_adds_flaws_above_measurements(self):
        self.assertEqual(
            set_description_block(
                'Cozy flannel.\n\nMeasurements: Length 27"',
                "flaws?",
                "Flaws: torn cuff. See photos for details.",
                before="measurements?",
            ),
            "Cozy flannel.\n\nFlaws: torn cuff. See photos for details.\n\nMeasurements: Length 27\"",
        )


class CarryoverUpdatesTest(unittest.TestCase):
    def test_carries_vendoo_fields_and_description_facts(self):
        listing = {
            "description": DESCRIPTION,
            "cost": 1.5,
            "sku": "SAG-HARBOR-L",
            "package_dimensions_in": "14x11x4",
            "poshmark_specifics": {"originalPrice": 48},
            "labels": ["Bin 4", "Thrift"],
            "internal_notes": "Bought at the Goodwill bins",
        }
        self.assertEqual(carryover_updates(listing, {}), {
            "sku": "SAG-HARBOR-L",
            "cog": "1.50",
            "packageDimensions": "14x11x4",
            "poshmarkOriginalPrice": "48",
            "vendooLabels": "Bin 4, Thrift",
            "sellerNotes": "Bought at the Goodwill bins",
            "knownFlaws": "small stain near the hem and a loose button",
            "descriptionMeasurements": 'Pit to pit 20"; Length 27"',
        })

    def test_flaws_drop_the_see_photos_phrase(self):
        listing = {"description": "Tee.\n\nFlaws: tiny hole on the cuff. See photos for details.\n\nMeasurements: See photos"}
        self.assertEqual(carryover_updates(listing, {}), {"knownFlaws": "tiny hole on the cuff"})

    def test_default_package_and_zero_posh_do_not_block_listing_values(self):
        listing = {
            "package_dimensions_in": "12x10x2",
            "poshmark_specifics": {"originalPrice": 60},
        }
        notes = {"packageDimensions": "13x10x3", "poshmarkOriginalPrice": "0"}
        self.assertEqual(carryover_updates(listing, notes), {
            "packageDimensions": "12x10x2",
            "poshmarkOriginalPrice": "60",
        })

    def test_seller_entered_details_win(self):
        listing = {
            "description": DESCRIPTION,
            "cost": 1.5,
            "sku": "FROM-LISTING",
            "package_dimensions_in": "14x11x4",
            "poshmark_specifics": {"originalPrice": 48},
            "labels": ["Bin 4"],
            "internal_notes": "From the bins",
        }
        notes = {
            "sku": "MINE-SKU",
            "cog": "3.00",
            "packageDimensions": "15x12x5",
            "poshmarkOriginalPrice": "99",
            "vendooLabels": "Rack B",
            "sellerNotes": "Mine",
        }
        updates = carryover_updates(listing, notes)
        self.assertNotIn("sku", updates)
        self.assertNotIn("cog", updates)
        self.assertNotIn("packageDimensions", updates)
        self.assertNotIn("poshmarkOriginalPrice", updates)
        self.assertNotIn("vendooLabels", updates)
        self.assertNotIn("sellerNotes", updates)
        self.assertIn("knownFlaws", updates)

    def test_price_carries_over_and_refreshes(self):
        """Regenerate rewrites at the price the seller just confirmed."""
        self.assertEqual(carryover_updates({"price": 42}, {})["askingPrice"], "42.00")
        # Unlike SKU or COG, a newer listing price wins over the carried one.
        self.assertEqual(
            carryover_updates({"price": 34}, {"askingPrice": "42.00"})["askingPrice"],
            "34.00",
        )
        self.assertNotIn("askingPrice", carryover_updates({"price": 0}, {}))

    def test_placeholder_blocks_carry_nothing(self):
        listing = {
            "description": (
                "Cute tee.\n\n"
                "Flaws: none noted. See photos for details.\n\n"
                "Measurements: See photos"
            ),
        }
        self.assertEqual(carryover_updates(listing, {}), {})

    def test_zero_cost_and_empty_listing_carry_nothing(self):
        self.assertEqual(carryover_updates({"cost": 0, "labels": [], "internal_notes": ""}, {}), {})
        self.assertEqual(carryover_updates(None, {}), {})


if __name__ == "__main__":
    unittest.main()
