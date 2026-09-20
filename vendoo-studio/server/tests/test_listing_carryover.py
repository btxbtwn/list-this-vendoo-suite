from __future__ import annotations

import unittest

from vendoo_studio.services.listing_carryover import carryover_updates, description_block


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


class CarryoverUpdatesTest(unittest.TestCase):
    def test_carries_vendoo_fields_and_description_facts(self):
        listing = {
            "description": DESCRIPTION,
            "cost": 1.5,
            "labels": ["Bin 4", "Thrift"],
            "internal_notes": "Bought at the Goodwill bins",
        }
        self.assertEqual(carryover_updates(listing, {}), {
            "cog": "1.50",
            "vendooLabels": "Bin 4, Thrift",
            "sellerNotes": "Bought at the Goodwill bins",
            "knownFlaws": "small stain near the hem and a loose button",
            "descriptionMeasurements": 'Pit to pit 20"; Length 27"',
        })

    def test_seller_entered_details_win(self):
        listing = {
            "description": DESCRIPTION,
            "cost": 1.5,
            "labels": ["Bin 4"],
            "internal_notes": "From the bins",
        }
        notes = {"cog": "3.00", "vendooLabels": "Rack B", "sellerNotes": "Mine"}
        updates = carryover_updates(listing, notes)
        self.assertNotIn("cog", updates)
        self.assertNotIn("vendooLabels", updates)
        self.assertNotIn("sellerNotes", updates)
        self.assertIn("knownFlaws", updates)

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
