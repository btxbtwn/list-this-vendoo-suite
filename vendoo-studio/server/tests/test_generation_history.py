from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.services.chat_prompts import listing_generation_messages
from vendoo_studio.services.generation_history import seller_history_context, seller_history_prompt
from vendoo_studio.services.registry import MEN_TSHIRT_PATH, WOMEN_TOPS_PATH
from vendoo_studio.services.skill_formulas import with_pinned_formulas

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
ANALYSIS = "Photo analysis:\n- brand: Nike (source: tag)\n- condition: Good\n- category: T-Shirts"


class GenerationHistoryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.repo = ConversationRepo(self.db)
        self.current = self.add_item(status="draft")
        current = ListingRepo(self.db).get_revisions(self.current.id)[0]
        current.listing_json = {key: value for key, value in current.listing_json.items()
                                if key not in {"internal_notes", "sku"}}
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_item(self, *, status="sold", price=32, sold_price=24, brand="Nike",
                 category=MEN_TSHIRT_PATH, condition="Pre-Owned - Good", sold_at=None,
                 notes=None, listed_days=20):
        conv = self.repo.create(title="Nike M Cotton Tee")
        when = sold_at if sold_at is not None else NOW - timedelta(days=1)
        payload = {
            "vendooStatus": status,
            "vendooDates": {
                "sold": when.isoformat(),
                "listed": (NOW - timedelta(days=listed_days)).isoformat(),
            },
            "vendooSale": {
                "price": sold_price, "soldAt": when.isoformat(),
                "marketplace": "depop", "cost": 0, "fees": 0,
            },
        }
        if notes:
            payload.update(notes)
        conv.notes = json.dumps(payload)
        self.db.commit()
        ListingRepo(self.db).save_revision(conv.id, {
            "title": conv.title, "price": price, "brand": brand,
            "category_path": category, "condition": condition, "size": "M",
            "quantity": 1,
            "internal_notes": "PRIVATE-OTHER-ITEM-NOTE", "sku": "PRIVATE-OTHER-SKU",
        }, source="vendoo_import")
        return conv

    def context(self, analysis=ANALYSIS):
        return seller_history_context(self.db, self.current.id, analysis, now=NOW)

    def test_recorded_prices_and_durations_are_used_without_duplicate_revisions(self):
        for days, amount in enumerate((20, 22, 24, 26, 28), start=1):
            self.add_item(sold_price=amount, sold_at=NOW - timedelta(days=days))
        another = self.add_item(sold_price=30, sold_at=NOW - timedelta(days=6))
        ListingRepo(self.db).save_revision(another.id, {
            "title": "Nike Tee", "brand": "Nike", "condition": "Good",
            "category_path": MEN_TSHIRT_PATH, "price": 999,
            "quantity": 1,
        }, source="user_form")
        result = self.context()
        self.assertEqual(result["sales"]["count"], 6)
        self.assertEqual(result["sales"]["median_sold_price"], 24)
        self.assertEqual(result["sales"]["median_days_to_sell"], 17)
        self.assertEqual(result["sales"]["summary_count"], 5)
        self.assertEqual(len(result["sales"]["examples"]), 5)
        self.assertNotIn("999", json.dumps(result))

    def test_recent_examples_are_sorted_by_instant_across_time_zones(self):
        self.add_item(sold_price=20, sold_at=datetime.fromisoformat("2026-10-04T23:00:00-05:00"))
        self.add_item(sold_price=30, sold_at=datetime.fromisoformat("2026-10-05T02:00:00+02:00"))
        examples = self.context()["sales"]["examples"]
        self.assertEqual([row["sold_price"] for row in examples], [20, 30])
        self.assertEqual(examples[0]["sold_at"], "2026-10-05T04:00:00+00:00")

    def test_full_category_brand_and_known_condition_limit_the_candidates(self):
        self.add_item()
        self.add_item(category=WOMEN_TOPS_PATH)
        self.add_item(brand="Adidas")
        self.add_item(condition="New With Tags/Box")
        self.add_item(category="Hardware > Shirts > T-Shirts")
        result = self.context()
        self.assertEqual(result["sales"]["count"], 1)
        self.assertIsNone(result["sales"]["median_sold_price"])
        self.assertIsNone(result["sales"]["median_days_to_sell"])

    def test_asking_prices_invalid_dates_and_invalid_money_never_become_sales(self):
        self.add_item()
        for price in (None, 0, -10, True, "NaN", "Infinity"):
            self.add_item(sold_price=price)
        self.add_item(sold_at=NOW + timedelta(days=1))
        self.add_item(sold_at=NOW - timedelta(days=366))
        self.add_item(notes={"vendooDates": {}, "vendooSale": {"price": 24}})
        busy = self.add_item()
        busy.status = "listing"
        self.db.commit()
        result = self.context()
        self.assertEqual(result["sales"]["count"], 1)
        self.assertEqual(result["sales"]["excluded_missing_invalid_or_old"], 9)

    def test_active_inventory_keeps_asking_prices_separate_and_missing_costs_unknown(self):
        self.add_item()
        self.add_item(status="active", price=80, listed_days=130)
        self.add_item(status="active", notes={"vendooDates": {}})
        self.add_item(status="draft")
        result = self.context()
        self.assertEqual(result["active"]["count"], 2)
        self.assertEqual(result["active"]["listed_90_plus_days"], 1)
        self.assertEqual(result["active"]["unknown_age_count"], 1)
        self.assertEqual(result["active"]["examples"][0]["asking_price"], 80)
        sale = result["sales"]["examples"][0]
        self.assertEqual(sale["cost"], 0)
        self.assertEqual(sale["fees"], 0)
        self.assertIsNone(sale["shipping_cost"])
        self.assertIsNone(sale["shipping_credit"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("sell_through", json.dumps(result))

    def test_current_item_and_unknown_photo_brand_are_not_evidence(self):
        self.current.notes = json.dumps({"vendooStatus": "sold", "vendooSale": {"price": 99}})
        self.db.commit()
        self.assertIsNone(self.context())
        self.add_item()
        self.assertIsNone(self.context("Photo analysis:\n- brand: Unknown"))
        self.assertIsNone(self.context("Photo analysis:\n- brand: Adidas"))

    def test_duplicate_vendoo_items_and_multi_quantity_prices_do_not_inflate_history(self):
        self.add_item(notes={"vendooItemId": "same-item"})
        self.add_item(notes={"vendooItemId": "same-item"})
        bundle = self.add_item(sold_price=200)
        revision = ListingRepo(self.db).get_revisions(bundle.id)[0]
        revision.listing_json = {**revision.listing_json, "quantity": 10}
        self.db.commit()
        self.assertEqual(self.context()["sales"]["count"], 1)
        self.current.notes = json.dumps({"vendooItemId": "same-item"})
        self.db.commit()
        self.assertIsNone(self.context())

    def test_category_paths_stored_as_json_arrays_match_the_full_path(self):
        self.add_item(category=MEN_TSHIRT_PATH.split(" > "))
        self.assertEqual(self.context()["sales"]["count"], 1)

    def test_history_reaches_generation_with_rules_that_limit_its_use(self):
        # Relative dates keep the real prompt's rolling window deterministic.
        self.add_item(sold_at=datetime.now(UTC) - timedelta(days=1))
        rules = with_pinned_formulas("OTHER-RULES")
        prompt = listing_generation_messages(rules, "", ANALYSIS, self.db, self.current.id)[0]["content"]
        self.assertIn("--- Seller history for this item ---", prompt)
        self.assertIn('"sold_price": 24', prompt)
        self.assertIn("### Seller History During Generation", prompt)
        self.assertIn("at least five genuinely comparable recorded sales", prompt)
        self.assertIn("A sale does not prove its wording caused the sale", prompt)
        self.assertIn("Never copy another item's", prompt)
        self.assertNotIn("PRIVATE-OTHER", prompt)

    def test_no_matching_history_produces_no_prompt_block(self):
        self.assertEqual(seller_history_prompt(self.db, self.current.id, ANALYSIS), "")

    def test_partial_catalog_formula_does_not_hide_pricing_or_history_rules(self):
        rules = with_pinned_formulas("## Formula Reference\n\n### TITLE Formula\n{BRAND} {SIZE}")
        self.assertIn("### PRICING Formula", rules)
        self.assertIn("### Seller History During Generation", rules)
        self.assertIn("Keep sales evidence, cost, profit, and pricing reasoning out", rules)
