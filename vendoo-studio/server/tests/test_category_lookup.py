from __future__ import annotations

import unittest
import asyncio
from unittest.mock import AsyncMock, Mock, patch

from vendoo_studio.services.category_lookup import category_search_query, pick_category_path
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

            with patch("vendoo_studio.routes.extension.extension_manager", manager), patch(
                "vendoo_studio.routes.extension.dispatch_search_categories",
                new=AsyncMock(return_value=True),
            ):
                result = await resolve_listing_category(db, conv.id, job=job)

            self.assertTrue(result["ok"])
            db.refresh(job)
            self.assertEqual(job.listing_snapshot["category_path"], MEN_TSHIRT_PATH)
            self.assertEqual(ListingRepo(db).get_revisions(conv.id)[0].listing_json["category_path"], target)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
