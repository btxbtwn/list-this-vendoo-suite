from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vendoo_studio.database import Base
from vendoo_studio.models.conversation import Conversation
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job  # noqa: F401
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.repositories.queries import RegistryRepo
from vendoo_studio.services.registry import (
    RegistryService,
    is_learned_listing_field,
    label_to_json_key,
)


class LabelHelpersTest(unittest.TestCase):
    def test_label_to_json_key(self):
        self.assertEqual(label_to_json_key("Fabric Weight"), "fabricWeight")
        self.assertEqual(label_to_json_key("MPN"), "mpn")
        self.assertEqual(label_to_json_key("Character"), "character")
        self.assertEqual(label_to_json_key("Clothing style"), "clothingStyle")

    def test_seller_settings_and_size_are_not_listing_fields(self):
        self.assertFalse(is_learned_listing_field("ebay", "Allow Best Offer"))
        self.assertFalse(is_learned_listing_field("poshmark", "Size"))
        self.assertFalse(is_learned_listing_field("etsy", "Worldwide Shipping"))
        self.assertTrue(is_learned_listing_field("ebay", "Character"))
        self.assertTrue(is_learned_listing_field("etsy", "Holiday"))


class RegistryMergeTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = Conversation(title="Tee")
        self.db.add(self.conv)
        self.db.commit()
        self.repo = RegistryRepo(self.db)
        self.service = RegistryService(self.db)
        self.category = "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops"

    def tearDown(self):
        self.db.close()

    def test_merge_adds_item_fields_and_skips_settings(self):
        for label in ("Character", "Fabric Weight", "Allow Best Offer", "Size"):
            self.repo.ensure_field("ebay", label, category_path=self.category)
        self.repo.ensure_field("etsy", "Holiday", category_path=self.category)
        self.repo.ensure_field("poshmark", "Style Tags", category_path=self.category)

        listing = {
            "title": "Tee",
            "category_path": self.category,
            "size": "S",
            "ebay_specifics": {"type": "T-Shirt", "character": "Does Not Apply"},
        }
        added = self.service.merge_learned_fields(listing)

        self.assertIn("ebay_specifics.fabricWeight", added)
        self.assertNotIn("ebay_specifics.character", added)
        self.assertEqual(listing["ebay_specifics"]["character"], "Does Not Apply")
        self.assertEqual(listing["ebay_specifics"]["fabricWeight"], "")
        self.assertNotIn("allowBestOffer", listing["ebay_specifics"])
        self.assertNotIn("size", listing["ebay_specifics"])
        self.assertEqual(listing["etsy_specifics"]["holiday"], "")
        self.assertEqual(listing["poshmark_specifics"]["styleTags"], "")

    def test_generation_context_lists_learned_keys(self):
        self.repo.ensure_field("ebay", "Character", category_path=self.category)
        self.repo.ensure_field("ebay", "Allow Best Offer", category_path=self.category)
        text = self.service.generation_context(self.category)
        self.assertIn("character", text)
        self.assertNotIn("allow best offer", text.lower())
        self.assertIn("ebay", text)
