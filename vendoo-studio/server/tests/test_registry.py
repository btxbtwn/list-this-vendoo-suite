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
    MEN_TSHIRT_PATH,
    POSHMARK_MEN_SHORT_TEE,
    POSHMARK_WOMEN_BLOUSE,
    POSHMARK_WOMEN_SHORT_TEE,
    MERCARI_WOMEN_BLOUSE,
    MERCARI_WOMEN_TEE,
    WOMEN_TOPS_PATH,
    RegistryService,
    align_listing_gender,
    is_account_managed_field,
    is_learned_listing_field,
    label_to_json_key,
    map_mercari_category_path,
    map_poshmark_category_path,
    map_vendoo_category_path,
)


class LabelHelpersTest(unittest.TestCase):
    def test_label_to_json_key(self):
        self.assertEqual(label_to_json_key("Fabric Weight"), "fabricWeight")
        self.assertEqual(label_to_json_key("MPN"), "mpn")
        self.assertEqual(label_to_json_key("Character"), "character")
        self.assertEqual(label_to_json_key("Clothing style"), "clothingStyle")
        self.assertEqual(label_to_json_key("Fabric pattern"), "fabricPattern")

    def test_seller_settings_and_size_are_not_listing_fields(self):
        self.assertFalse(is_learned_listing_field("ebay", "Allow Best Offer"))
        self.assertFalse(is_learned_listing_field("ebay", "Return Within"))
        self.assertFalse(is_learned_listing_field("ebay", "Return Payed By"))
        self.assertFalse(is_learned_listing_field("ebay", "Starting Price"))
        self.assertFalse(is_learned_listing_field("poshmark", "Size"))
        self.assertFalse(is_learned_listing_field("etsy", "Worldwide Shipping"))
        self.assertTrue(is_learned_listing_field("ebay", "Character"))
        self.assertTrue(is_learned_listing_field("etsy", "Holiday"))

    def test_shipping_is_account_managed_except_on_depop_and_mercari(self):
        self.assertTrue(is_account_managed_field("etsy", "Shipping Profile"))
        self.assertTrue(is_account_managed_field("etsy", "Processing Time"))
        self.assertTrue(is_account_managed_field("ebay", "Shipping Service"))
        self.assertTrue(is_account_managed_field("poshmark", "Discounted Shipping"))
        self.assertFalse(is_learned_listing_field("etsy", "Shipping Profile"))
        self.assertFalse(is_account_managed_field("depop", "Parcel Size"))
        self.assertFalse(is_account_managed_field("mercari", "Shipping Label"))
        self.assertFalse(is_account_managed_field("mercari", "Delivery Method"))
        self.assertTrue(is_learned_listing_field("depop", "Parcel Size"))

    def test_policies_are_account_managed_on_every_marketplace(self):
        for marketplace in ("ebay", "etsy", "poshmark", "mercari", "depop"):
            self.assertTrue(is_account_managed_field(marketplace, "Return Policy"), marketplace)
            self.assertTrue(is_account_managed_field(marketplace, "Payment Policy"), marketplace)
        self.assertFalse(is_account_managed_field("ebay", "Material"))
        # The general weight feeds Depop's parcel tier, so it is still filled.
        self.assertFalse(is_account_managed_field("general", "Weight (lbs)"))
        self.assertFalse(is_account_managed_field("general", "Length"))


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


class CategoryMappingTest(unittest.TestCase):
    def test_maps_abbreviated_womens_tee_path_using_title(self):
        mapped = map_vendoo_category_path(
            "Clothing > Women",
            {"title": "Unknown S Southwestern Graphic T-Shirt", "department": "Women"},
        )
        self.assertEqual(mapped, WOMEN_TOPS_PATH)

    def test_maps_mercari_style_womens_tshirt_path(self):
        mapped = map_vendoo_category_path("Women > Clothing > Tops > T-shirts")
        self.assertEqual(mapped, WOMEN_TOPS_PATH)

    def test_maps_shirts_and_blouses_alias(self):
        mapped = map_vendoo_category_path("Women's Shirts & Blouses")
        self.assertEqual(mapped, WOMEN_TOPS_PATH)

    def test_keeps_womens_dresses_path(self):
        mapped = map_vendoo_category_path(
            "Clothing > Women > Dresses",
            {"title": "Floral Midi Dress", "department": "Women"},
        )
        self.assertEqual(mapped, "Clothing > Women > Dresses")

    def test_keeps_mens_sweatshirt_path_when_title_contains_sweatshirt(self):
        path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweaters"
        mapped = map_vendoo_category_path(
            path,
            {
                "title": "Fruit of the Loom M Retro Graphic Sweatshirt Blue",
                "department": "Men",
                "ebay_specifics": {"department": "Men", "type": "Sweatshirt"},
            },
        )
        self.assertEqual(mapped, path)

    def test_keeps_sweatshirt_leaf_even_when_ebay_type_is_still_tshirt(self):
        path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweatshirts & Hoodies"
        mapped = map_vendoo_category_path(
            path,
            {
                "title": "Fruit of the Loom M Retro Graphic Sweatshirt",
                "department": "Men",
                "ebay_specifics": {"department": "Men", "type": "T-Shirt"},
            },
        )
        self.assertEqual(mapped, path)

    def test_align_keeps_sweatshirt_category_from_chat_patch(self):
        path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweaters"
        listing = {
            "title": "Fruit of the Loom M Retro Graphic Sweatshirt Blue",
            "department": "Men",
            "category_path": MEN_TSHIRT_PATH,
            "ebay_specifics": {"department": "Men", "type": "T-Shirt"},
        }
        listing["category_path"] = path
        listing["ebay_specifics"]["type"] = "Sweatshirt"
        align_listing_gender(listing, [
            {"op": "replace", "path": "/category_path", "value": path},
            {"op": "replace", "path": "/ebay_specifics/type", "value": "Sweatshirt"},
        ])
        self.assertEqual(listing["category_path"], path)

    def test_maps_mens_tee_from_listing_type(self):
        mapped = map_vendoo_category_path(
            "Clothing > Men",
            {"title": "Nike Tee", "ebay_specifics": {"department": "Men", "type": "T-Shirt"}},
        )
        self.assertEqual(mapped, MEN_TSHIRT_PATH)

    def test_mens_department_wins_over_womens_path(self):
        mapped = map_vendoo_category_path(
            WOMEN_TOPS_PATH,
            {
                "title": "Casa San Bord M Graphic T-Shirt Maroon Crewneck Cotton",
                "department": "Men",
            },
        )
        self.assertEqual(mapped, MEN_TSHIRT_PATH)

    def test_keeps_mens_path_when_ebay_department_still_women(self):
        mapped = map_vendoo_category_path(
            MEN_TSHIRT_PATH,
            {
                "title": "Casa San Bord M Graphic T-Shirt",
                "department": "Men",
                "ebay_specifics": {"department": "Women", "type": "T-Shirt"},
            },
        )
        self.assertEqual(mapped, MEN_TSHIRT_PATH)

    def test_ensure_listing_defaults_rewrites_womens_path_for_mens_tee(self):
        from vendoo_studio.services.job_snapshot import ensure_listing_defaults

        listing = {
            "title": "Casa San Bord M Graphic T-Shirt Maroon Crewneck Cotton",
            "category_path": WOMEN_TOPS_PATH,
            "department": "Men",
            "condition": "Good",
        }
        ensure_listing_defaults(listing)
        self.assertEqual(listing["category_path"], MEN_TSHIRT_PATH)

    def test_align_listing_gender_rewrites_category_from_department_patch(self):
        listing = {
            "title": "Casa San Bord M Graphic T-Shirt Maroon Crewneck Cotton",
            "department": "Women",
            "category_path": WOMEN_TOPS_PATH,
            "ebay_specifics": {"department": "Women", "type": "T-Shirt"},
        }
        align_listing_gender(listing, [
            {"op": "replace", "path": "/department", "value": "Men"},
        ])
        self.assertEqual(listing["department"], "Men")
        self.assertEqual(listing["ebay_specifics"]["department"], "Men")
        self.assertEqual(listing["category_path"], MEN_TSHIRT_PATH)

    def test_ensure_listing_defaults_rewrites_category(self):
        from vendoo_studio.services.job_snapshot import ensure_listing_defaults

        listing = {
            "title": "Unknown S Southwestern Graphic T-Shirt",
            "category_path": "Clothing > Women",
            "department": "Women",
            "condition": "Good",
        }
        ensure_listing_defaults(listing)
        self.assertEqual(listing["category_path"], WOMEN_TOPS_PATH)
        self.assertEqual(listing["mercari_specifics"]["shippingLabel"], "USPS Ground Advantage / 1 - 7 days / $ 5.66 / 0.5 lb")


class PoshmarkCategoryMappingTest(unittest.TestCase):
    def test_maps_mens_vendoo_tee_path(self):
        mapped = map_poshmark_category_path(
            MEN_TSHIRT_PATH,
            {"title": "Amplife L Graphic T-Shirt", "ebay_specifics": {"department": "Men", "type": "T-Shirt"}},
        )
        self.assertEqual(mapped, POSHMARK_MEN_SHORT_TEE)

    def test_maps_womens_graphic_tee_to_short_sleeve(self):
        mapped = map_poshmark_category_path(
            WOMEN_TOPS_PATH,
            {"title": "Southwestern Graphic T-Shirt", "department": "Women"},
        )
        self.assertEqual(mapped, POSHMARK_WOMEN_SHORT_TEE)

    def test_maps_blouse_type_to_blouses(self):
        mapped = map_poshmark_category_path(
            WOMEN_TOPS_PATH,
            {"title": "Silk Blouse", "ebay_specifics": {"department": "Women", "type": "Blouse"}},
        )
        self.assertEqual(mapped, POSHMARK_WOMEN_BLOUSE)

    def test_keeps_explicit_matching_poshmark_path(self):
        mapped = map_poshmark_category_path(
            WOMEN_TOPS_PATH,
            {
                "title": "Silk Blouse",
                "department": "Women",
                "poshmark_specifics": {"categoryPath": ["Women", "Tops", "Blouses"]},
            },
        )
        self.assertEqual(mapped, POSHMARK_WOMEN_BLOUSE)

    def test_ignores_stale_womens_poshmark_path_for_mens_tee(self):
        mapped = map_poshmark_category_path(
            MEN_TSHIRT_PATH,
            {
                "title": "Amplife Graphic T-Shirt",
                "ebay_specifics": {"department": "Men", "type": "T-Shirt"},
                "poshmark_specifics": {"categoryPath": ["Women", "Tops"]},
            },
        )
        self.assertEqual(mapped, POSHMARK_MEN_SHORT_TEE)

    def test_maps_mens_tee_when_vendoo_path_is_still_womens(self):
        mapped = map_poshmark_category_path(
            WOMEN_TOPS_PATH,
            {
                "title": "Casa San Bord M Graphic T-Shirt Maroon Crewneck Cotton",
                "department": "Men",
                "ebay_specifics": {"type": "T-Shirt"},
            },
        )
        self.assertEqual(mapped, POSHMARK_MEN_SHORT_TEE)

    def test_remaps_stale_tank_tops_for_short_sleeve_tee(self):
        mapped = map_poshmark_category_path(
            "Women > Tops > Tank Tops",
            {
                "title": "Faded Glory L Graphic T-Shirt Short Sleeve",
                "department": "Women",
                "ebay_specifics": {"type": "T-Shirt", "sleeveLength": "Short Sleeve"},
                "marketplace_categories": {"poshmark": "Women > Tops > Tank Tops"},
                "poshmark_specifics": {"categoryPath": ["Women", "Tops", "Tank Tops"]},
            },
        )
        self.assertEqual(mapped, POSHMARK_WOMEN_SHORT_TEE)

    def test_keeps_tank_tops_for_sleeveless_tank(self):
        mapped = map_poshmark_category_path(
            "Women > Tops > Tank Tops",
            {
                "title": "Faded Glory Sleeveless Tank Top",
                "department": "Women",
                "ebay_specifics": {"type": "Tank", "sleeveLength": "Sleeveless"},
                "poshmark_specifics": {"categoryPath": ["Women", "Tops", "Tank Tops"]},
            },
        )
        self.assertEqual(mapped, "Women > Tops > Tank Tops")

    def test_does_not_map_sweatshirt_to_poshmark_tee(self):
        path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweaters"
        mapped = map_poshmark_category_path(
            path,
            {
                "title": "Fruit of the Loom M Retro Graphic Sweatshirt",
                "department": "Men",
                "ebay_specifics": {"department": "Men", "type": "T-Shirt"},
            },
        )
        self.assertEqual(mapped, path)
        self.assertNotEqual(mapped, POSHMARK_MEN_SHORT_TEE)


class MercariCategoryMappingTest(unittest.TestCase):
    def test_maps_button_up_blouse_to_mercari_blouses(self):
        mapped = map_mercari_category_path(
            WOMEN_TOPS_PATH,
            {
                "title": "Notations XL Retro Short Sleeve Button-Up Shirt",
                "department": "Women",
                "ebay_specifics": {"department": "Women", "type": "Blouse"},
            },
        )
        self.assertEqual(mapped, MERCARI_WOMEN_BLOUSE)

    def test_maps_graphic_tee_to_mercari_tshirts(self):
        mapped = map_mercari_category_path(
            WOMEN_TOPS_PATH,
            {"title": "Southwestern Graphic T-Shirt", "department": "Women"},
        )
        self.assertEqual(mapped, MERCARI_WOMEN_TEE)
