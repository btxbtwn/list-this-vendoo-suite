from __future__ import annotations

import unittest
import asyncio
from unittest.mock import AsyncMock, Mock, patch

from vendoo_studio.services.category_lookup import (
    category_search_query,
    condense_category_search_query,
    marketplace_path_fits_general,
    pick_category_path,
)
from vendoo_studio.services.registry import MEN_TSHIRT_PATH


class CategorySearchQueryTest(unittest.TestCase):
    def test_builds_men_sweatshirt_query_from_title(self):
        query = category_search_query({
            "title": "Fruit of the Loom M Retro Graphic Sweatshirt Blue",
            "department": "Men",
            "category_path": MEN_TSHIRT_PATH,
            "ebay_specifics": {"department": "Men", "type": "T-Shirt"},
        })
        self.assertIn("Men", query)
        self.assertIn("Sweatshirt", query)

    def test_uses_requested_leaf_over_stale_tshirt_path(self):
        query = category_search_query(
            {
                "title": "Fruit of the Loom Sweatshirt",
                "department": "Men",
                "category_path": MEN_TSHIRT_PATH,
            },
            "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweaters",
        )
        self.assertEqual(query, "Men Sweaters")


class MarketplacePathFitsGeneralTest(unittest.TestCase):
    def test_rejects_tee_nuts_under_women_tops(self):
        general = "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops"
        self.assertFalse(marketplace_path_fits_general(
            general,
            "Business & Industrial > Fasteners & Hardware > Fastener Nuts > Tee Nuts",
        ))
        self.assertFalse(marketplace_path_fits_general(
            general,
            "Toys & Collectibles > Dress Up & Pretend Play > Play Teepees",
        ))
        self.assertTrue(marketplace_path_fits_general(
            general,
            "Women > Tops > T-shirts",
        ))
        self.assertTrue(marketplace_path_fits_general(
            general,
            "Clothing > Women's Clothing > Tops & Tees > T-shirts",
        ))

    def test_rejects_a_marketplace_path_for_the_wrong_department(self):
        general = "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts"
        self.assertFalse(marketplace_path_fits_general(
            general,
            "Sporting Goods > Camping & Hiking > Clothing > Women's > Shirts, Tops & Sweaters",
        ))
        self.assertTrue(marketplace_path_fits_general(
            general,
            "Men > Shirts > Tees - Short Sleeve",
        ))

    def test_accepts_grailed_menswear_outerwear(self):
        general = (
            "Clothing, Shoes & Accessories > Men > Men's Clothing > "
            "Coats, Jackets & Vests"
        )
        self.assertTrue(marketplace_path_fits_general(
            general, "Menswear > Outerwear > Light Jackets",
        ))
        self.assertFalse(marketplace_path_fits_general(
            general, "Womenswear > Outerwear > Light Jackets",
        ))


class PickCategoryPathTest(unittest.TestCase):
    def test_prefers_sweatshirt_leaf_over_tshirt(self):
        listing = {
            "title": "Fruit of the Loom M Retro Graphic Sweatshirt",
            "department": "Men",
        }
        path = pick_category_path(
            [
                {"path": MEN_TSHIRT_PATH, "score": 4},
                {
                    "path": "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweats & Hoodies > Sweatshirts",
                    "score": 3,
                },
            ],
            listing,
            "Men Sweatshirt",
            MEN_TSHIRT_PATH,
        )
        self.assertIn("Sweatshirt", path)
        self.assertNotIn("T-Shirt", path)

    def test_keeps_matching_selected_path(self):
        path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweaters"
        self.assertEqual(
            pick_category_path(
                [{"path": path, "score": 4}],
                {"title": "Sweatshirt", "department": "Men"},
                "Men Sweatshirt",
                path,
            ),
            path,
        )


    def test_skips_path_whose_separators_were_lost(self):
        glued = "Clothing, Shoes & AccessoriesMenMen's ClothingShirtsT-Shirts"
        self.assertEqual(
            pick_category_path(
                [{"path": glued, "score": 5}, {"path": MEN_TSHIRT_PATH, "score": 4}],
                {"title": "Harley-Davidson XL Tank Top", "department": "Men"},
                "Men T-Shirt",
                glued,
            ),
            MEN_TSHIRT_PATH,
        )

    def test_returns_nothing_when_no_match_is_a_breadcrumb(self):
        glued = "Clothing, Shoes & AccessoriesMenMen's ClothingShirtsT-Shirts"
        self.assertEqual(
            pick_category_path([{"path": glued}], {"department": "Men"}, "Men T-Shirt", glued),
            "",
        )


class ApplyResolvedCategoryTest(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from vendoo_studio.database import Base
        from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
        from vendoo_studio.models.job import Job  # noqa: F401
        from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
        from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
        from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.conv = ConversationRepo(self.db).create(title="Sweatshirt")
        ListingRepo(self.db).save_revision(self.conv.id, {
            "title": "Fruit of the Loom M Retro Graphic Sweatshirt",
            "department": "Men",
            "category_path": MEN_TSHIRT_PATH,
        }, source="model")

    def tearDown(self):
        self.db.close()

    def test_writes_picker_path_onto_listing_and_notes(self):
        import json

        from vendoo_studio.repositories.queries import ConversationRepo, ListingRepo
        from vendoo_studio.services.category_lookup import apply_resolved_category

        path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweats & Hoodies > Sweatshirts"
        saved = apply_resolved_category(self.db, self.conv.id, path)
        self.assertEqual(saved["category_path"], path)
        listing = ListingRepo(self.db).get_revisions(self.conv.id)[0].listing_json
        self.assertEqual(listing["category_path"], path)
        notes = json.loads(ConversationRepo(self.db).get(self.conv.id).notes)
        self.assertEqual(notes["categoryOverride"], path)


class ResolveCategorySnapshotTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_creates_revision_without_mutating_approved_snapshot(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from vendoo_studio.database import Base
        from vendoo_studio.models.conversation import Conversation
        from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
        from vendoo_studio.models.job import Job
        from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
        from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
        from vendoo_studio.repositories.queries import ListingRepo
        from vendoo_studio.services.category_lookup import resolve_listing_category

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            conv = Conversation(title="Sweatshirt")
            db.add(conv)
            db.commit()
            original = {
                "title": "Fruit of the Loom M Retro Graphic Sweatshirt",
                "department": "Men",
                "category_path": MEN_TSHIRT_PATH,
            }
            ListingRepo(db).save_revision(conv.id, original, source="model")
            job = Job(
                conversation_id=conv.id,
                approved_revision_id="rev1",
                listing_snapshot=dict(original),
                status="completed",
                vendoo_item_id="abc123",
            )
            db.add(job)
            db.commit()
            target = "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweats & Hoodies > Sweatshirts"
            waiter = asyncio.get_running_loop().create_future()
            waiter.set_result({"ok": True, "matches": [{"path": target, "score": 5}], "path": target})
            manager = Mock(connected=True)
            manager.register_wait.return_value = waiter

            with patch("vendoo_studio.services.extension_connection.extension_manager", manager), patch(
                "vendoo_studio.services.extension_connection.dispatch_search_categories",
                new=AsyncMock(return_value=True),
            ):
                result = await resolve_listing_category(db, conv.id, job=job)

            self.assertTrue(result["ok"])
            db.refresh(job)
            self.assertEqual(job.listing_snapshot["category_path"], MEN_TSHIRT_PATH)
            self.assertEqual(ListingRepo(db).get_revisions(conv.id)[0].listing_json["category_path"], target)
        finally:
            db.close()


class StatedDepartmentTest(unittest.TestCase):
    """The vision pass states who an item is cut for; the query must use it.

    A women's tee routinely names no department in its brand, size or style,
    and "Women's Clothing > Tops" shares no word with "T-Shirt" — so without
    this the correct category cannot be ranked at all.
    """

    ANALYSIS = (
        "Photo analysis:\n- brand: Belle\n- size: Small\n- color: Black\n"
        "- style: Graphic Scoop Neck Tee\n- department: Women\n- category: T-Shirt"
    )

    def test_department_reaches_the_query(self):
        query = condense_category_search_query(self.ANALYSIS).lower()
        self.assertIn("women", query)

    def test_department_survives_a_garment_that_names_no_gender(self):
        # Nothing here says "women" except the department line.
        self.assertNotIn("women", self.ANALYSIS.replace("- department: Women", "").lower())
        self.assertIn("women", condense_category_search_query(self.ANALYSIS).lower())

    def test_stated_department_beats_a_stray_word(self):
        analysis = (
            "Photo analysis:\n- style: Tee from the men's floor of a department store\n"
            "- department: Women\n- category: T-Shirt"
        )
        query = condense_category_search_query(analysis).lower()
        # "men" is a substring of "women", so check the department token itself.
        self.assertEqual(query.split()[0], "women")

    def test_girls_and_boys_are_departments_too(self):
        for stated, expected in (("Girls", "girls"), ("Boys", "boys")):
            analysis = f"Photo analysis:\n- department: {stated}\n- category: T-Shirt"
            self.assertIn(expected, condense_category_search_query(analysis).lower())

    def test_no_department_line_still_works(self):
        analysis = "Photo analysis:\n- category: Women's T-Shirt"
        self.assertIn("women", condense_category_search_query(analysis).lower())

    def test_unisex_takes_men_but_unisex_kids_does_not(self):
        adult = "Photo analysis:\n- department: Unisex\n- category: T-shirt"
        kids = "Photo analysis:\n- department: Unisex Kids\n- category: T-shirt"
        self.assertEqual(condense_category_search_query(adult).split()[0], "men")
        self.assertNotIn("men", condense_category_search_query(kids).lower().split())

    def test_short_sleeve_is_not_shorts(self):
        # A short-sleeve tee's query came out "Short shirt", and eBay's only
        # candidate was Uniforms > Pants & Shorts.
        analysis = (
            "Photo analysis:\n- style: Short-sleeve crewneck graphic tee\n"
            "- department: Unisex\n- category: T-shirt"
        )
        query = condense_category_search_query(analysis).lower()
        self.assertNotIn("short", query.split())
        self.assertIn("t-shirt", query)


if __name__ == "__main__":
    unittest.main()


class EveryVisionProviderAsksForDepartmentTest(unittest.TestCase):
    """Adding a field to one provider's prompt is not adding it.

    The department was added to two providers and missed on the third, and
    the third was the one the app had switched to — so the analysis came back
    without it and the category query lost its department again. Every
    provider now sends the one prompt in ``photo_analysis.py``.
    """

    def test_every_provider_sends_the_shared_prompt(self):
        from pathlib import Path

        providers = Path(__file__).resolve().parents[1] / "vendoo_studio" / "providers"
        self.assertIn("- department:", (providers / "photo_analysis.py").read_text(encoding="utf-8"))
        missing = [
            path.name
            for path in (
                providers / "xiaomi_mimo.py",
                providers / "chatgpt_codex.py",
                providers / "cursor_agent.py",
                providers / "claude_agent.py",
                providers / "chat_completions.py",
                providers / "anthropic_api.py",
            )
            if "PHOTO_ANALYSIS_SYSTEM" not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [], f"vision prompts not using the shared prompt: {missing}")
