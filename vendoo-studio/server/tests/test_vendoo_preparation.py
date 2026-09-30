from __future__ import annotations

import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from vendoo_studio.services import vendoo_create
from vendoo_studio.services.vendoo_specifics import FieldSpec

PROVIDER = object()

class PreparationTest(unittest.TestCase):
    def setUp(self):
        self.listing = {
            "title": "Cotton tee", "description": "Classic", "price": 20,
            "category_path": "Clothing > Tops", "category_id": "tops",
            "marketplace_categories": {"ebay": "Clothing > Shirts"},
            "marketplace_category_ids": {"ebay": "shirts"},
            "marketplace_category_objects": {"general": {"id": "tops"}, "ebay": {"id": "shirts"}},
            "ebay_specifics": {"material": "Cotton", "categoryId": "shirts", "categoryPath": ["Clothing", "Shirts"]},
            "labels": ["To List"],
        }
        self.fields = {"ebay": {
            "Material": FieldSpec("Material"), "Season": FieldSpec("Season"),
        }}
        self.fetch = patch.object(vendoo_create, "fetch_listing_specifics", new=AsyncMock(return_value=self.fields))
        self.fetch.start()
        self.addCleanup(self.fetch.stop)
        self.markets = patch.object(vendoo_create, "_mappable_marketplaces", return_value=())
        self.markets.start()
        self.addCleanup(self.markets.stop)
        self.request = patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", new=AsyncMock(return_value=[]))
        self.model = self.request.start()
        self.addCleanup(self.request.stop)

    def prepare(self, listing, provider=PROVIDER):
        return asyncio.run(vendoo_create.prepare_listing_fields_for_vendoo(
            SimpleNamespace(id=None), listing, provider=provider,
        ))[0]

    def test_preparation_is_read_only_and_copy_edits_do_not_repeat_unanswerable_gaps(self):
        with patch.object(vendoo_create, "run_ops", new=AsyncMock(side_effect=AssertionError("unexpected write"))):
            prepared = self.prepare(self.listing)
            self.assertEqual(self.model.await_count, 1)
            self.prepare({**prepared, "price": 15, "description": "Revised copy"})
        self.assertEqual(self.model.await_count, 1)
        self.assertEqual(prepared["labels"], ["To List"])
        self.assertNotIn("_vendoo_preparation", self.listing)

    def test_clearing_a_previously_filled_field_requests_it_again(self):
        prepared = self.prepare(self.listing)
        prepared["ebay_specifics"]["material"] = ""
        self.prepare(prepared)
        self.assertEqual(self.model.await_count, 2)
        self.assertIn("Material", [row["field"] for row in self.model.await_args.kwargs["gaps"]])

    def test_new_schema_rechecks_fields(self):
        prepared = self.prepare(self.listing)
        self.fields["ebay"]["Pattern"] = FieldSpec("Pattern", required=True)
        self.prepare(prepared)
        self.assertEqual(self.model.await_count, 2)

    def test_no_provider_does_not_mark_unattempted_gaps_as_prepared(self):
        prepared = self.prepare(self.listing, provider=None)
        self.assertNotIn("_vendoo_preparation", prepared)
        self.prepare(prepared)
        self.assertEqual(self.model.await_count, 1)

    def test_category_edit_discards_old_ids_before_resolution_without_mutating_input(self):
        prepared = self.prepare(self.listing)
        prepared["marketplace_categories"]["ebay"] = "Clothing > Sweaters"
        untouched = copy.deepcopy(prepared)

        async def resolve(_job, listing, **kwargs):
            self.assertNotIn("ebay", listing["marketplace_category_ids"])
            self.assertNotIn("ebay", listing["marketplace_category_objects"])
            self.assertNotIn("categoryId", listing["ebay_specifics"])
            self.assertEqual(listing["category_id"], "tops")
            listing["marketplace_category_ids"]["ebay"] = "sweaters"
            return listing, []

        with patch.object(vendoo_create, "resolve_listing_categories", resolve):
            self.prepare(prepared)
        self.assertEqual(prepared, untouched)
        self.assertEqual(self.model.await_count, 2)

    def test_general_category_edit_discards_all_mapped_leaves(self):
        prepared = self.prepare(self.listing)
        prepared["category_path"] = "Clothing > Sweaters"

        async def resolve(_job, listing, **kwargs):
            self.assertNotIn("category_id", listing)
            self.assertEqual(listing["marketplace_category_ids"], {})
            self.assertEqual(listing["marketplace_category_objects"], {})
            return listing, []

        with patch.object(vendoo_create, "resolve_listing_categories", resolve):
            self.prepare(prepared)
