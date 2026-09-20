"""SKU, price, labels and listed marketplaces — what the sidebar filters on."""

from __future__ import annotations

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
from vendoo_studio.routes.conversations import _conv_response, _extras
from vendoo_studio.services.vendoo_import import (
    split_vendoo_labels,
    vendoo_listed_marketplaces,
)


class ListingFacetsTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.convs = ConversationRepo(self.db)
        self.listings = ListingRepo(self.db)

    def tearDown(self):
        self.db.close()

    def test_facets_read_sku_and_price_from_the_current_revision(self):
        conv = self.convs.create(title="Nike tee")
        self.listings.save_revision(conv.id, {"title": "Nike tee", "sku": "NIKE-TEE-M", "price": 24.5}, "test")
        facets = self.convs.listing_facets()
        self.assertEqual(facets[conv.id], {"sku": "NIKE-TEE-M", "price": 24.5})
        self.assertEqual(self.convs.listing_facet(conv.id), {"sku": "NIKE-TEE-M", "price": 24.5})

    def test_facets_are_empty_without_a_listing(self):
        conv = self.convs.create(title="Bare draft")
        self.assertNotIn(conv.id, self.convs.listing_facets())
        self.assertEqual(self.convs.listing_facet(conv.id), {"sku": None, "price": None})

    def test_response_carries_labels_marketplaces_sku_and_price(self):
        conv = self.convs.create(title="Nike tee")
        conv.notes = json.dumps({
            "vendooLabels": "A19, To List",
            "vendooMarketplaces": ["ebay", "etsy"],
        })
        self.db.commit()
        self.listings.save_revision(conv.id, {"title": "Nike tee", "sku": "NIKE-TEE-M", "price": 24.5}, "test")
        response = _conv_response(conv, _extras(None, self.convs.listing_facet(conv.id)))
        self.assertEqual(response.sku, "NIKE-TEE-M")
        self.assertEqual(response.price, 24.5)
        self.assertEqual(response.vendoo_labels, ["A19", "To List"])
        self.assertEqual(response.vendoo_marketplaces, ["ebay", "etsy"])

    def test_listed_marketplaces_follow_vendoo_status_flags(self):
        item = {
            "listings": {
                "ebay": {"status": {"listed": True}},
                "poshmark": {"status": {"listed": False}},
                "etsy": {"status": {"sold": True}},
                "depop": {"status": {"shipped": True}},
                "vestiaireApi": {"status": {"listed": True}},
                "validate": {"status": {"listed": True}},
            }
        }
        self.assertEqual(
            vendoo_listed_marketplaces(item, None),
            ["depop", "ebay", "etsy", "vestiaire"],
        )

    def test_listed_marketplaces_are_empty_without_listings(self):
        self.assertEqual(vendoo_listed_marketplaces(None, None), [])
        self.assertEqual(vendoo_listed_marketplaces({"listings": "nope"}, None), [])

    def test_labels_split_on_commas(self):
        self.assertEqual(split_vendoo_labels(" A19 , To List ,"), ["A19", "To List"])
        self.assertEqual(split_vendoo_labels(None), [])


if __name__ == "__main__":
    unittest.main()
