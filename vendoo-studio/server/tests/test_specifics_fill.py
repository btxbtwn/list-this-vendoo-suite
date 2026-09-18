from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from vendoo_studio.services import specifics_fill
from vendoo_studio.services.vendoo_specifics import normalize_specifics


def run(coro):
    return asyncio.run(coro)


def specs(**fields):
    raw = {}
    for key, (options, required, multi) in fields.items():
        raw[key] = {
            "id": key,
            "display": key,
            "options": {str(i): {"id": v, "display": v} for i, v in enumerate(options)},
            "rules": {"fieldOptions": {
                "minValues": 1 if required else 0,
                "maxValues": 2 if multi else 1,
                "selectionMode": "SelectionOnly" if options else "FreeText",
            }},
        }
    return normalize_specifics(raw)


class SpecificsGapsTest(unittest.TestCase):
    def test_lists_only_unanswered_fields_required_first(self):
        fields = {"ebay": specs(
            Season=(["Spring", "Winter"], False, True),
            Department=(["Women", "Men"], True, False),
            Style=(["Blouse"], False, False),
        )}
        listing = {"ebay_specifics": {"style": "Blouse"}}

        gaps = specifics_fill.specifics_gaps(listing, fields)

        # Style is answered, so it is not asked again.
        self.assertEqual([g["field"] for g in gaps], ["Department", "Season"])
        self.assertTrue(gaps[0]["required"])
        self.assertEqual(gaps[0]["options"], ["Men", "Women"])

    def test_covers_marketplaces_the_learned_filler_ignores(self):
        """Schema fields are asked for any marketplace, not just the learned five."""
        fields = {"vinted": specs(Colour=(["Red"], True, False))}
        gaps = specifics_fill.specifics_gaps({}, fields)
        self.assertEqual([(g["marketplace"], g["field"]) for g in gaps], [("vinted", "Colour")])


class FillListingSpecificsTest(unittest.TestCase):
    FIELDS = {"ebay": specs(
        Season=(["Spring", "Winter"], False, True),
        Department=(["Women", "Men"], True, False),
    )}

    def test_asks_until_nothing_is_left_empty(self):
        answers = [
            [{"marketplace": "ebay", "field": "Department", "value": "Women"}],
            [{"marketplace": "ebay", "field": "Season", "value": "Spring"}],
        ]

        async def reply(provider, *, listing, gaps, evidence):
            return answers.pop(0) if answers else None

        with mock.patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", reply):
            listing, remaining = run(specifics_fill.fill_listing_specifics(
                {}, self.FIELDS, provider=object(), evidence="tag says Women",
            ))

        self.assertEqual(remaining, [])
        self.assertEqual(answers, [])
        block = listing["ebay_specifics"]
        self.assertEqual(block.get("department"), "Women")
        self.assertEqual(block.get("season"), "Spring")

    def test_reports_what_the_model_would_not_answer(self):
        """A field the evidence cannot support is left empty, not invented."""
        async def reply(provider, *, listing, gaps, evidence):
            return [{"marketplace": "ebay", "field": "Department", "value": "Women"}]

        with mock.patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", reply):
            listing, remaining = run(specifics_fill.fill_listing_specifics(
                {}, self.FIELDS, provider=object(),
            ))

        # Department landed; Season never did, and the second round changed
        # nothing, so it stops rather than looping.
        self.assertEqual([row["field"] for row in remaining], ["Season"])

    def test_without_a_provider_it_reports_instead_of_asking(self):
        listing, remaining = run(specifics_fill.fill_listing_specifics({}, self.FIELDS, provider=None))
        self.assertEqual(listing, {})
        self.assertEqual([row["field"] for row in remaining], ["Department", "Season"])


if __name__ == "__main__":
    unittest.main()
