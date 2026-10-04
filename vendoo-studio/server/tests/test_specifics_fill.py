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

    def test_unencodable_optional_values_still_need_repair(self):
        fields = {"ebay": specs(
            Style=(["Bomber Jacket", "Windbreaker"], True, False),
            Features=(["Full Zip", "Pockets"], False, True),
            Theme=(["Sports"], False, False),
        )}
        listing = {"ebay_specifics": {
            "style": "Casual", "features": ["Full Zip", "Imaginary option"],
            "theme": "Does Not Apply",
        }}
        gaps = specifics_fill.specifics_gaps(listing, fields)
        self.assertEqual([gap["field"] for gap in gaps], ["Style", "Features"])
        self.assertEqual(gaps[0]["rejected"], "Casual")
        self.assertEqual(gaps[1]["options"], ["Full Zip", "Pockets"])

    def test_required_not_applicable_remains_a_gap(self):
        fields = {"ebay": specs(Style=(["Windbreaker"], True, False))}
        gaps = specifics_fill.specifics_gaps({"ebay_specifics": {"style": "Does Not Apply"}}, fields)
        self.assertEqual([gap["field"] for gap in gaps], ["Style"])


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

    def test_a_stalled_model_cannot_hold_the_send(self):
        """Past the deadline the fill returns what landed and reports the rest."""
        calls = []

        async def reply(provider, *, listing, gaps, evidence):
            calls.append(gaps)
            if len(calls) == 1:
                return [{"marketplace": "ebay", "field": "Department", "value": "Women"}]
            await asyncio.Event().wait()

        with (
            mock.patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", reply),
            mock.patch.object(specifics_fill, "FILL_DEADLINE_SEC", 0.2),
        ):
            listing, remaining = run(asyncio.wait_for(
                specifics_fill.fill_listing_specifics({}, self.FIELDS, provider=object()),
                timeout=5,
            ))

        self.assertEqual(listing["ebay_specifics"].get("department"), "Women")
        self.assertEqual([row["field"] for row in remaining], ["Season"])

    def test_without_a_provider_it_reports_instead_of_asking(self):
        listing, remaining = run(specifics_fill.fill_listing_specifics({}, self.FIELDS, provider=None))
        self.assertEqual(listing, {})
        self.assertEqual([row["field"] for row in remaining], ["Department", "Season"])

    def test_unanswerable_first_batch_does_not_starve_later_optionals(self):
        fields = {"ebay": specs(**{
            f"Optional {i:02d}": ([], False, False) for i in range(55)
        })}
        calls = []

        async def reply(provider, *, listing, gaps, evidence):
            calls.append([gap["field"] for gap in gaps])
            if len(calls) == 1:
                return None
            return [{"marketplace": "ebay", "field": gap["field"], "value": "Present"} for gap in gaps]

        with mock.patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", reply):
            listing, remaining = run(specifics_fill.fill_listing_specifics({}, fields, provider=object()))

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], [f"Optional {i:02d}" for i in range(50, 55)])
        self.assertEqual(len(remaining), 50)
        self.assertEqual(len(listing["ebay_specifics"]), 5)

    def test_replaces_invalid_jacket_optional_with_an_encodable_answer(self):
        fields = {"ebay": specs(Features=(["Full Zip", "Pockets"], False, True))}

        async def reply(provider, *, listing, gaps, evidence):
            self.assertEqual(gaps[0]["rejected"], "Zippered")
            return [{"marketplace": "ebay", "field": "Features", "value": ["Full Zip", "Pockets"]}]

        with mock.patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", reply):
            listing, remaining = run(specifics_fill.fill_listing_specifics(
                {"ebay_specifics": {"features": "Zippered"}}, fields, provider=object(),
            ))
        self.assertEqual(remaining, [])
        self.assertEqual(listing["ebay_specifics"]["features"], ["Full Zip", "Pockets"])

    def test_field_repair_receives_canonical_rules_and_required_status(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from vendoo_studio.services.listing_field_gaps import _request_missing_field_values

        async def reply(provider, messages):
            self.assertIn("Canonical optional field instructions", messages[0]["content"])
            self.assertIn("Required: no", messages[1]["content"])
            self.assertIn("Required: yes", messages[1]["content"])
            return '```json\n{"missing_fields":[{"marketplace":"ebay","field":"Features","value":"Pockets"}]}\n```'

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "list-this").mkdir()
            (root / "list-this" / "SKILL.md").write_text("Canonical optional field instructions")
            with (
                mock.patch("vendoo_studio.config.skills_dir", return_value=root),
                mock.patch("vendoo_studio.services.listing_generate.collect_provider_text", reply),
            ):
                patches = run(_request_missing_field_values(
                    object(), listing={}, evidence="Visible pockets",
                    gaps=[
                        {"marketplace": "ebay", "field": "Features", "options": ["Pockets"]},
                        {"marketplace": "ebay", "field": "Style", "required": True},
                    ],
                ))
        self.assertEqual(patches[0]["value"], "Pockets")


if __name__ == "__main__":
    unittest.main()
