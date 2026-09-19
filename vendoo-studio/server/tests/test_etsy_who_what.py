from __future__ import annotations

import unittest

from vendoo_studio.models.validation import normalize_listing_dropdowns, validate_listing


def _etsy_issues(etsy: dict) -> list[str]:
    listing = {"title": "Shorts", "etsy_specifics": etsy}
    result = validate_listing(listing, require_photos=False, selected_marketplaces=["etsy"])
    return [
        issue["message"]
        for issue in result.errors
        if issue["field"] in {"etsy_specifics.who_made", "etsy_specifics.what_is"}
    ]


class EtsyWhoWhatTests(unittest.TestCase):
    def test_vendoo_codes_become_dropdown_labels(self):
        listing = {"etsy_specifics": {"whoMade": "someone_else", "whatIsIt": "0"}}
        normalize_listing_dropdowns(listing)
        self.assertEqual(listing["etsy_specifics"]["who_made"], "Another company or person")
        self.assertEqual(listing["etsy_specifics"]["what_is"], "A finished product")

    def test_codes_and_paraphrases_pass_validation(self):
        for who, what in [
            ("someone_else", "0"),
            ("collective", "1"),
            ("i_did", "0"),
            ("another company or person", "a finished product"),
            ("Someone else", "Finished product"),
        ]:
            with self.subTest(who=who, what=what):
                self.assertEqual(_etsy_issues({"who_made": who, "what_is": what}), [])

    def test_unknown_values_still_flagged(self):
        issues = _etsy_issues({"who_made": "My grandma", "what_is": "A hat"})
        self.assertIn("Etsy who-made is not a current dropdown value", issues)
        self.assertIn("Etsy what-is is not a current dropdown value", issues)


if __name__ == "__main__":
    unittest.main()
