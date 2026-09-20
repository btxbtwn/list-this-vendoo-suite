from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, UTC

from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services import sell_through
from vendoo_studio.services.sell_through import (
    CohortStats,
    MIN_COHORT,
    SoldOutcome,
    cohort_stats,
    collect_outcomes,
    history_suggestion,
    listing_age_days,
    pick_cohort,
    target_discount,
)
from vendoo_studio.services.vendoo_import import vendoo_sale


def _sold(category="jeans", brand="levi's", first=50.0, sold=40.0, days=30, known=True):
    return SoldOutcome(
        category=category,
        brand=brand,
        first_price=first,
        sold_price=sold,
        days_listed=days,
        discount_known=known,
    )


class CohortTest(unittest.TestCase):
    def test_a_thin_group_is_not_a_pattern(self):
        self.assertIsNone(cohort_stats([_sold()] * (MIN_COHORT - 1), scope="all", label="items"))

    def test_stats_read_the_median_discount_and_time_to_sell(self):
        outcomes = [
            _sold(first=100, sold=80, days=10),
            _sold(first=100, sold=75, days=20),
            _sold(first=100, sold=90, days=30),
            _sold(first=100, sold=70, days=40),
            _sold(first=100, sold=85, days=50),
        ]
        stats = cohort_stats(outcomes, scope="all", label="items")
        self.assertEqual(stats.count, 5)
        self.assertAlmostEqual(stats.median_discount, 0.20)
        self.assertEqual(stats.median_days, 30)
        self.assertIn("20% off", stats.describe())
        self.assertIn("30 days", stats.describe())

    def test_sales_that_cannot_show_movement_leave_the_discount_unknown(self):
        """Imported-after-the-fact sales time the market; they do not price it."""
        outcomes = [_sold(first=100, sold=100, days=20, known=False) for _ in range(6)]
        stats = cohort_stats(outcomes, scope="category", label="dresses")
        self.assertEqual(stats.count, 6)
        self.assertEqual(stats.discount_count, 0)
        self.assertIsNone(stats.median_discount)
        self.assertEqual(stats.median_days, 20)
        # The old text read "sell at 0% off", which is not what the data says.
        self.assertNotIn("% off", stats.describe())
        self.assertIn("about 20 days", stats.describe())

    def test_a_sale_above_ask_is_not_a_negative_discount(self):
        self.assertEqual(_sold(first=40, sold=48).discount, 0.0)

    def test_the_most_specific_group_with_enough_sales_wins(self):
        jeans = [_sold(category="jeans", first=100, sold=80) for _ in range(MIN_COHORT)]
        tees = [_sold(category="tees", brand="nike", first=100, sold=50) for _ in range(MIN_COHORT)]
        self.assertEqual(pick_cohort(jeans + tees, category="Women > Jeans", brand="").scope, "category")
        # Too few tops of their own, but the brand carries enough.
        nike_tops = pick_cohort(jeans + tees, category="Women > Tops", brand="Nike")
        self.assertEqual(nike_tops.scope, "brand")
        self.assertEqual(nike_tops.label, "Nike")
        # Neither matches: fall back to the whole inventory.
        self.assertEqual(pick_cohort(jeans + tees, category="Shoes", brand="Vans").scope, "all")


    def test_a_broader_group_wins_when_the_specific_one_cannot_price(self):
        """Dresses can only say how long; the inventory can say how much off."""
        dresses = [_sold(category="dresses", first=40, sold=40, days=20, known=False) for _ in range(6)]
        rest = [_sold(category="tees", first=100, sold=75, days=30) for _ in range(MIN_COHORT)]
        stats = pick_cohort(dresses + rest, category="Women > Dresses", brand="")
        self.assertEqual(stats.scope, "all")
        self.assertAlmostEqual(stats.median_discount, 0.25)
        # With nothing broader to learn from, the thin group still stands.
        only_dresses = pick_cohort(dresses, category="Women > Dresses", brand="")
        self.assertEqual(only_dresses.scope, "category")
        self.assertIsNone(only_dresses.median_discount)


class TargetDiscountTest(unittest.TestCase):
    def _stats(self, discount=0.2, days=30.0):
        return CohortStats(scope="all", label="items", count=9, median_discount=discount, median_days=days)

    def test_a_young_listing_is_only_part_way_to_the_typical_discount(self):
        self.assertAlmostEqual(target_discount(self._stats(), 15), 0.10)

    def test_at_the_typical_age_it_reaches_it(self):
        self.assertAlmostEqual(target_discount(self._stats(), 30), 0.20)

    def test_an_overdue_listing_keeps_stepping_past_it(self):
        # Triple the usual age: 20% + (2 cycles × half of 20%).
        self.assertAlmostEqual(target_discount(self._stats(), 90), 0.40)

    def test_the_target_is_capped(self):
        self.assertLessEqual(target_discount(self._stats(0.5, 10.0), 3650), 0.6)

    def test_without_a_time_to_sell_it_uses_the_discount_as_is(self):
        self.assertAlmostEqual(target_discount(self._stats(days=None), 400), 0.2)

    def test_an_overdue_listing_still_steps_when_the_cohort_sells_at_ask(self):
        # 0% off is a real answer about price and no answer about waiting: at
        # triple the usual age this still has to move.
        self.assertAlmostEqual(target_discount(self._stats(0.0, 30.0), 90), 0.10)
        self.assertAlmostEqual(target_discount(self._stats(None, 30.0), 90), 0.10)

    def test_a_listing_inside_the_usual_window_is_not_pushed_by_the_floor(self):
        self.assertAlmostEqual(target_discount(self._stats(0.0, 30.0), 15), 0.0)

    def test_a_deep_cohort_is_capped_before_it_is_overdue(self):
        # Half off is the cohort's own median, but no suggestion goes past 60%.
        self.assertAlmostEqual(target_discount(self._stats(0.8, 30.0), 30), 0.6)


class HistorySuggestionTest(unittest.TestCase):
    def _stats(self, discount=0.2, days=30.0):
        return CohortStats(scope="category", label="jeans", count=8, median_discount=discount, median_days=days)

    def test_it_prices_where_those_sales_landed(self):
        price, reason = history_suggestion(
            self._stats(), current_price=100, first_price=100, age_days=30
        )
        self.assertEqual(price, 80)
        self.assertIn("Your jeans sell at 20% off", reason)
        self.assertIn("30 days in", reason)

    def test_no_cohort_means_no_opinion(self):
        self.assertIsNone(history_suggestion(None, current_price=100, first_price=100, age_days=30))

    def test_a_listing_already_below_the_pattern_is_left_alone(self):
        # Asked 100, already down to 70; the cohort only sells 20% off.
        self.assertIsNone(
            history_suggestion(self._stats(), current_price=70, first_price=100, age_days=30)
        )

    def test_an_overdue_listing_says_it_is_stepping_past_the_pattern(self):
        price, reason = history_suggestion(
            self._stats(), current_price=100, first_price=100, age_days=90
        )
        # Target is 40% off, but one step never exceeds MAX_STEP_PERCENT.
        self.assertEqual(price, 65)
        self.assertIn("90 days in", reason)
        self.assertIn("well past that", reason)

    def test_a_listing_at_full_ask_does_not_claim_it_is_already_off(self):
        _price, reason = history_suggestion(
            self._stats(), current_price=100, first_price=100, age_days=30
        )
        self.assertNotIn("0% off —", reason)

    def test_one_step_is_capped_however_overdue_the_listing(self):
        price, _reason = history_suggestion(
            self._stats(0.5, 10.0), current_price=100, first_price=100, age_days=3650
        )
        self.assertEqual(price, 65)

    def test_the_cap_is_never_overshot_by_rounding(self):
        # 35% off $48 is $31.20; $31 would be a 35.4% step, so the cap holds at $32.
        price, _reason = history_suggestion(
            self._stats(0.28, 40.0), current_price=48, first_price=48, age_days=63
        )
        self.assertEqual(price, 32)


class CollectOutcomesTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def _conversation(self, *, status, notes, prices):
        conv = ConversationRepo(self.db).create(title="Tee", notes=json.dumps(notes))
        conv.status = status
        self.db.commit()
        for price in prices:
            ListingRepo(self.db).save_revision(
                conv.id,
                {"title": "Tee", "price": price, "category_path": "Women > Jeans", "brand": "Levi's"},
                "generate",
            )
        return conv

    def test_a_sold_listing_becomes_one_outcome(self):
        self._conversation(
            status="sold",
            notes={
                "vendooStatus": "sold",
                "vendooDates": {"listed": "2026-01-01T00:00:00+00:00", "sold": "2026-02-10T00:00:00+00:00"},
            },
            prices=[50, 44],
        )
        outcomes = collect_outcomes(self.db)
        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.category, "jeans")
        self.assertEqual(outcome.brand, "levi's")
        self.assertEqual(outcome.first_price, 50)
        # No captured sale price: the last asking price stands in for it.
        self.assertEqual(outcome.sold_price, 44)
        self.assertEqual(outcome.days_listed, 40)

    def test_a_captured_sale_price_beats_the_last_asking_price(self):
        self._conversation(
            status="sold",
            notes={"vendooStatus": "sold", "vendooSale": {"price": 38, "marketplace": "poshmark"}},
            prices=[50, 44],
        )
        self.assertEqual(collect_outcomes(self.db)[0].sold_price, 38)

    def test_an_item_imported_after_it_sold_cannot_show_a_discount(self):
        """One revision, captured at import: "sold at that price" is a tautology."""
        self._conversation(
            status="sold",
            notes={
                "vendooStatus": "sold",
                "vendooSale": {"price": 44},
                # Sold long before Studio ever saw the listing.
                "vendooDates": {"listed": "2020-01-01T00:00:00+00:00", "sold": "2020-02-10T00:00:00+00:00"},
            },
            prices=[44],
        )
        outcome = collect_outcomes(self.db)[0]
        self.assertEqual(outcome.discount, 0.0)
        self.assertFalse(outcome.discount_known)

    def test_a_price_studio_held_before_the_sale_is_evidence(self):
        """Same price in and out, but Studio watched it ask that much and sell."""
        self._conversation(
            status="sold",
            notes={
                "vendooStatus": "sold",
                "vendooSale": {"price": 44},
                "vendooDates": {
                    "listed": "2099-01-01T00:00:00+00:00",
                    "sold": "2099-02-10T00:00:00+00:00",
                },
            },
            prices=[44],
        )
        outcome = collect_outcomes(self.db)[0]
        self.assertEqual(outcome.discount, 0.0)
        self.assertTrue(outcome.discount_known)

    def test_a_price_that_moved_is_evidence_whenever_it_was_imported(self):
        self._conversation(
            status="sold",
            notes={"vendooStatus": "sold", "vendooSale": {"price": 38}},
            prices=[50],
        )
        outcome = collect_outcomes(self.db)[0]
        self.assertTrue(outcome.discount_known)
        self.assertAlmostEqual(outcome.discount, 0.24)

    def test_unsold_listings_are_not_evidence(self):
        self._conversation(status="active", notes={"vendooStatus": "active"}, prices=[50])
        self.assertEqual(collect_outcomes(self.db), [])


class CollectOutcomesCostTest(unittest.TestCase):
    """The dialog asks for this on every open; it must not rescan every time."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        sell_through._outcome_cache.clear()

    def tearDown(self):
        sell_through._outcome_cache.clear()
        self.db.close()

    def _sold_conversation(self, price=50):
        conv = ConversationRepo(self.db).create(
            title="Tee",
            notes=json.dumps({"vendooStatus": "sold", "vendooSale": {"price": price - 6}}),
        )
        conv.status = "sold"
        self.db.commit()
        ListingRepo(self.db).save_revision(
            conv.id,
            {"title": "Tee", "price": price, "category_path": "Women > Jeans", "brand": "Levi's"},
            "generate",
        )
        return conv

    def _count_selects(self, fn):
        seen: list[str] = []

        def record(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                seen.append(statement)

        event.listen(self.engine, "before_cursor_execute", record)
        try:
            result = fn()
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        return result, len(seen)

    def test_an_unchanged_workspace_is_answered_from_the_cache(self):
        self._sold_conversation()
        first, queries = self._count_selects(lambda: collect_outcomes(self.db))
        self.assertEqual(len(first), 1)
        self.assertGreater(queries, 2)
        again, cheap = self._count_selects(lambda: collect_outcomes(self.db))
        self.assertEqual(again, first)
        # Only the two fingerprint aggregates — no conversation or revision scan.
        self.assertEqual(cheap, 2)

    def test_a_new_sale_invalidates_it(self):
        self._sold_conversation()
        self.assertEqual(len(collect_outcomes(self.db)), 1)
        self._sold_conversation(price=80)
        self.assertEqual(len(collect_outcomes(self.db)), 2)

    def test_a_new_revision_invalidates_it(self):
        conv = self._sold_conversation()
        self.assertEqual(collect_outcomes(self.db)[0].sold_price, 44)
        ListingRepo(self.db).save_revision(
            conv.id,
            {"title": "Tee", "price": 30, "category_path": "Women > Jeans", "brand": "Levi's"},
            "price_drop",
        )
        # The captured sale price still wins, but the scan ran again to see it.
        outcome = collect_outcomes(self.db)[0]
        self.assertEqual(outcome.first_price, 50)
        self.assertEqual(outcome.sold_price, 44)

    def test_more_sold_items_than_one_id_batch(self):
        for index in range(5):
            self._sold_conversation(price=50 + index)
        with patch.object(sell_through, "_ID_BATCH", 2):
            sell_through._outcome_cache.clear()
            outcomes = collect_outcomes(self.db)
        self.assertEqual(len(outcomes), 5)
        self.assertEqual(sorted(o.first_price for o in outcomes), [50, 51, 52, 53, 54])


class VendooSaleTest(unittest.TestCase):
    def test_it_reads_the_sale_record(self):
        sale = vendoo_sale({"saleRecord": {"marketplace": "poshmark", "price_sold": 24}})
        self.assertEqual(sale["price"], 24)
        self.assertEqual(sale["marketplace"], "poshmark")

    def test_it_falls_back_to_a_listing_sale(self):
        item = {"listings": {"ebay": {"sales": [{"price_sold": 31}]}}}
        self.assertEqual(vendoo_sale(item)["price"], 31)

    def test_an_unsold_item_has_no_sale(self):
        self.assertEqual(vendoo_sale({"listings": {"ebay": {"status": {"listed": True}}}}), {})


class ListingAgeTest(unittest.TestCase):
    def test_age_counts_from_the_last_time_it_went_live(self):
        listed = (datetime.now(UTC) - timedelta(days=63)).isoformat()
        notes = json.dumps({"vendooDates": {"listed": listed}})
        self.assertEqual(listing_age_days(notes), 63)

    def test_no_listing_date_means_no_age(self):
        self.assertIsNone(listing_age_days(json.dumps({"vendooDates": {}})))
        self.assertIsNone(listing_age_days(None))


if __name__ == "__main__":
    unittest.main()
