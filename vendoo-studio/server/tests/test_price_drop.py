from __future__ import annotations

import unittest
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from vendoo_studio.services.price_drop import (
    drop_options,
    effective_percent,
    PRICE_DROP_SOURCE,
    apply_price_to_listing,
    build_preview,
    comps_formula_price,
    fields_from_listing,
    first_listed_price,
    listing_price,
    price_after_percent,
    price_drop_history,
    suggest_percent,
    whole_dollars,
)


def _rev(price: float, source: str, *, rev_id: str, parent: str | None = None, days_ago: int = 0):
    created = datetime.now(UTC) - timedelta(days=days_ago)
    return SimpleNamespace(
        id=rev_id,
        source=source,
        parent_revision_id=parent,
        created_at=created,
        listing_json={"price": price, "title": "Tee", "brand": "Nike"},
    )


class ListingPriceHelpersTest(unittest.TestCase):
    def test_reads_numeric_and_string_prices(self):
        self.assertEqual(listing_price({"price": 48}), 48.0)
        self.assertEqual(listing_price({"price": "36.00"}), 36.0)
        self.assertIsNone(listing_price({"price": 0}))
        self.assertIsNone(listing_price({}))

    def test_whole_dollar_percent_cut(self):
        self.assertEqual(whole_dollars(29.7), 30)
        # A cut rounds down, so the price never moves less than the label says:
        # 48 - 15% is 40.80, and $41 would only be a 14.6% cut.
        self.assertEqual(price_after_percent(48, 15), 40)
        self.assertEqual(price_after_percent(10, 20), 8)
        # The case that exposed it: a dollar is already 7% of a $14 listing.
        self.assertEqual(price_after_percent(14, 10), 12)
        self.assertEqual(price_after_percent(1, 10), 1)


class DropOptionsTest(unittest.TestCase):
    def test_options_state_the_cut_they_really_make(self):
        """A 10% target off $48 lands on $43, which is 10.4% — say so."""
        self.assertEqual(
            drop_options(48.0, (10, 15, 20)),
            [
                {"price": 43, "percent": 10, "effective_percent": 10.4},
                {"price": 40, "percent": 15, "effective_percent": 16.7},
                {"price": 38, "percent": 20, "effective_percent": 20.8},
            ],
        )

    def test_targets_that_collide_on_one_price_are_offered_once(self):
        """15% and 20% off $14 both floor to $11; one chip, not two."""
        self.assertEqual(
            drop_options(14.0, (10, 15, 20)),
            [
                {"price": 12, "percent": 10, "effective_percent": 14.3},
                {"price": 11, "percent": 15, "effective_percent": 21.4},
            ],
        )

    def test_a_cut_that_cannot_move_the_price_is_dropped(self):
        self.assertEqual(drop_options(1.0, (10, 15, 20)), [])
        self.assertEqual(effective_percent(0, 0), 0.0)


class FieldsFromListingTest(unittest.TestCase):
    def test_uses_brand_and_category_leaf(self):
        fields = fields_from_listing({
            "brand": "Levi's",
            "category_path": "Clothing > Men > Shorts",
            "size": "32",
            "primaryColor": "Blue",
        })
        self.assertEqual(fields["brand"], "Levi's")
        self.assertEqual(fields["category"], "Shorts")
        self.assertEqual(fields["size"], "32")
        self.assertEqual(fields["color"], "Blue")


class HistoryAndSuggestTest(unittest.TestCase):
    def test_history_reads_price_drop_revisions(self):
        revisions = [
            _rev(40, PRICE_DROP_SOURCE, rev_id="r3", parent="r2", days_ago=0),
            _rev(48, PRICE_DROP_SOURCE, rev_id="r2", parent="r1", days_ago=3),
            _rev(55, "generation", rev_id="r1", days_ago=20),
        ]
        history = price_drop_history(revisions)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].from_price, 48)
        self.assertEqual(history[0].to_price, 40)
        self.assertEqual(history[1].from_price, 55)
        self.assertEqual(history[1].to_price, 48)
        self.assertEqual(first_listed_price(revisions), 55)

    def test_suggest_shrinks_after_recent_or_repeated_drops(self):
        revisions = [
            _rev(40, PRICE_DROP_SOURCE, rev_id="r2", parent="r1", days_ago=1),
            _rev(48, "generation", rev_id="r1", days_ago=10),
        ]
        history = price_drop_history(revisions)
        percent, reason = suggest_percent(history)
        self.assertEqual(percent, 5)
        self.assertIn("Recent drop", reason)

        many = [
            _rev(30, PRICE_DROP_SOURCE, rev_id="r4", parent="r3", days_ago=10),
            _rev(35, PRICE_DROP_SOURCE, rev_id="r3", parent="r2", days_ago=20),
            _rev(40, PRICE_DROP_SOURCE, rev_id="r2", parent="r1", days_ago=30),
            _rev(50, "generation", rev_id="r1", days_ago=40),
        ]
        percent, reason = suggest_percent(price_drop_history(many))
        self.assertEqual(percent, 5)
        self.assertIn("Several prior", reason)

        percent, reason = suggest_percent([])
        self.assertEqual(percent, 10)
        self.assertEqual(reason, "Default 10% markdown.")


class ApplyPriceTest(unittest.TestCase):
    def test_updates_price_and_poshmark_original(self):
        listing = {
            "price": 48,
            "poshmark_specifics": {"originalPrice": 40},
            "title": "Nike Tee",
        }
        updated = apply_price_to_listing(listing, 41)
        self.assertEqual(updated["price"], 41)
        self.assertEqual(updated["poshmark_specifics"]["originalPrice"], 48)
        self.assertEqual(listing["price"], 48)


class CompsFormulaTest(unittest.TestCase):
    def test_market_times_1_35(self):
        text = (
            "Sold comps:\n"
            "Query: Nike tee sold comps\n"
            "Source: Brave Search\n"
            "Market: $18–$22\n"
            "\n"
            "- $20 · eBay · Nike Tee\n"
            "  https://www.ebay.com/itm/1\n"
            "- $18 · Poshmark · Nike Tee\n"
            "  https://poshmark.com/listing/2\n"
            "- $22 · Mercari · Nike Tee\n"
            "  https://www.mercari.com/item/3\n"
            "\n"
            "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
        )
        market, target, report = comps_formula_price(text)
        self.assertEqual(market, 20.0)
        self.assertEqual(target, 27)
        self.assertIsNotNone(report)

    def test_outlier_comp_does_not_move_the_market(self):
        text = (
            "Sold comps:\n"
            "Query: Nike tee sold comps\n"
            "Source: Brave Search\n"
            "\n"
            "- $20 · eBay · Nike Tee\n"
            "  https://www.ebay.com/itm/1\n"
            "- $18 · Poshmark · Nike Tee\n"
            "  https://poshmark.com/listing/2\n"
            "- $22 · Mercari · Nike Tee\n"
            "  https://www.mercari.com/item/3\n"
            "- $200 · eBay · Nike Tee lot of 10\n"
            "  https://www.ebay.com/itm/4\n"
        )
        market, target, _ = comps_formula_price(text)
        self.assertEqual(market, 20.0)
        self.assertEqual(target, 27)

    def test_two_comps_are_too_thin_to_price_from(self):
        text = (
            "Sold comps:\n"
            "Query: Nike tee sold comps\n"
            "Source: Brave Search\n"
            "Market: $18–$22\n"
            "\n"
            "- $20 · eBay · Nike Tee\n"
            "  https://www.ebay.com/itm/1\n"
            "- $18 · Poshmark · Nike Tee\n"
            "  https://poshmark.com/listing/2\n"
        )
        market, target, report = comps_formula_price(text)
        self.assertIsNone(market)
        self.assertIsNone(target)
        self.assertEqual(len(report.comps), 2)


class BuildPreviewTest(unittest.IsolatedAsyncioTestCase):
    async def test_preview_without_comps(self):
        listing = {"price": 48, "brand": "Nike", "category_path": "Tops > T-Shirts"}
        revisions = [_rev(48, "generation", rev_id="r1")]
        with (
            patch("vendoo_studio.services.price_drop.comps_search_available", return_value=False),
            patch("vendoo_studio.services.price_drop.research_sold_comps", new=AsyncMock()) as research,
        ):
            preview = await build_preview(listing, revisions)
        research.assert_not_called()
        self.assertEqual(preview["current_price"], 48)
        self.assertEqual(preview["suggested_percent"], 10)
        self.assertEqual(preview["suggested_price"], 43)
        self.assertEqual(preview["prices_by_percent"]["10"], 43)
        self.assertFalse(preview["comps"]["available"])

    async def test_preview_prefers_deeper_comps_target(self):
        listing = {"price": 48, "brand": "Nike", "category_path": "Tops > T-Shirts"}
        revisions = [_rev(48, "generation", rev_id="r1")]
        comps = (
            "Sold comps:\n"
            "Query: Nike T-Shirts sold comps\n"
            "Source: Brave Search\n"
            "Market: $18–$22\n"
            "\n"
            "- $20 · eBay · Nike Tee\n"
            "  https://www.ebay.com/itm/1\n"
            "- $18 · Poshmark · Nike Tee\n"
            "  https://poshmark.com/listing/2\n"
            "- $22 · Mercari · Nike Tee\n"
            "  https://www.mercari.com/item/3\n"
            "\n"
            "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
        )
        with (
            patch("vendoo_studio.services.price_drop.comps_search_available", return_value=True),
            patch("vendoo_studio.services.price_drop.research_sold_comps", new=AsyncMock(return_value=comps)),
        ):
            preview = await build_preview(listing, revisions)
        self.assertEqual(preview["comps"]["target_price"], 27)
        self.assertEqual(preview["suggested_mode"], "comps")
        self.assertEqual(preview["suggested_price"], 27)

    async def test_preview_keeps_percent_when_comps_are_thin(self):
        listing = {"price": 48, "brand": "Nike", "category_path": "Tops > T-Shirts"}
        revisions = [_rev(48, "generation", rev_id="r1")]
        comps = (
            "Sold comps:\n"
            "Query: Nike T-Shirts sold comps\n"
            "Source: Brave Search\n"
            "Market: $20\n"
            "\n"
            "- $20 · eBay · Nike Tee\n"
            "  https://www.ebay.com/itm/1\n"
        )
        with (
            patch("vendoo_studio.services.price_drop.comps_search_available", return_value=True),
            patch("vendoo_studio.services.price_drop.research_sold_comps", new=AsyncMock(return_value=comps)),
        ):
            preview = await build_preview(listing, revisions)
        self.assertIsNone(preview["comps"]["target_price"])
        self.assertIsNone(preview["comps"]["market_midpoint"])
        self.assertEqual(preview["suggested_mode"], "percent")
        self.assertEqual(preview["suggested_price"], 43)
        self.assertIn("$20 · eBay", preview["comps"]["text"])


if __name__ == "__main__":
    unittest.main()
