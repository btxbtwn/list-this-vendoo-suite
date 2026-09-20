from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, UTC

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
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


def _sold(category="jeans", brand="levi's", first=50.0, sold=40.0, days=30):
    return SoldOutcome(
        category=category,
        brand=brand,
        first_price=first,
        sold_price=sold,
        days_listed=days,
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

    def test_unsold_listings_are_not_evidence(self):
        self._conversation(status="active", notes={"vendooStatus": "active"}, prices=[50])
        self.assertEqual(collect_outcomes(self.db), [])


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
