import unittest
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategoryTree, CategoryTreeNode
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.services.category_tree import store_children
from vendoo_studio.services.category_selection import select_categories


class CategoryTreeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(CategoryTree(marketplace="general"))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_branch_completion_waits_for_children_and_is_idempotent(self):
        root = {"nodes": [{"id": "women", "label": "Women", "path": ["Women"],
                           "is_leaf": False, "has_children": True}]}
        store_children(self.db, "general", "__root", root)
        store_children(self.db, "general", "__root", root)
        self.assertEqual(self.db.query(CategoryTreeNode).count(), 1)
        self.assertFalse(self.db.get(CategoryTreeNode, ("general", "women")).children_loaded)
        store_children(self.db, "general", "women", {"nodes": [{"id": "tees", "label": "Tees",
            "path": ["Women", "Tees"], "is_leaf": True, "has_children": False}]})
        self.assertEqual(self.db.query(CategoryTreeNode).filter_by(children_loaded=False).count(), 0)
        self.assertEqual(self.db.get(CategoryTreeNode, ("general", "tees")).path, "Women > Tees")

    def test_empty_response_does_not_mark_tree_complete(self):
        with self.assertRaises(ValueError):
            store_children(self.db, "general", "__root", {"nodes": []})
        self.assertFalse(self.db.get(CategoryTree, "general").roots_loaded)


class CategorySelectionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        for mp, root, leaf in [("general", "Clothing", "Women's Tops"), ("ebay", "Fashion", "Shirts")]:
            self.db.add(CategoryTree(marketplace=mp, status="complete", roots_loaded=True))
            self.db.add(CategoryTreeNode(marketplace=mp, category_id=mp + "-root", parent_id="__root",
                label=root, path=root, is_leaf=False, has_children=True, children_loaded=True))
            self.db.add(CategoryTreeNode(marketplace=mp, category_id=mp + "-leaf", parent_id=mp + "-root",
                label=leaf, path=root + " > " + leaf, is_leaf=True, has_children=False, children_loaded=True))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_chooses_distinct_terminal_paths_from_each_tree(self):
        class Provider:
            async def chat(self, messages, stream=True):
                choices = json.loads(messages[-1]["content"])["choices"]
                yield json.dumps({"categories": {mp: rows[0]["id"] for mp, rows in choices.items()}})
        result = await select_categories(self.db, Provider(), "Women's cotton tee", "", ["ebay"])
        self.assertEqual(result, {"general": "Clothing > Women's Tops", "ebay": "Fashion > Shirts"})

    async def test_rejects_invented_category_id(self):
        class Provider:
            async def chat(self, messages, stream=True):
                yield '{"categories": {"general": "invented", "ebay": "ebay-leaf"}}'
        with self.assertRaisesRegex(RuntimeError, "verified general category"):
            await select_categories(self.db, Provider(), "tee", "", ["ebay"])

    async def test_selectable_parent_still_descends_to_most_specific_category(self):
        for mp in ("general", "ebay"):
            self.db.get(CategoryTreeNode, (mp, mp + "-root")).is_leaf = True
        self.db.commit()

        class Provider:
            async def chat(self, messages, stream=True):
                choices = json.loads(messages[-1]["content"])["choices"]
                yield json.dumps({"categories": {mp: rows[0]["id"] for mp, rows in choices.items()}})

        result = await select_categories(self.db, Provider(), "tee", "", ["ebay"], override="Clothing")
        self.assertEqual(result, {"general": "Clothing > Women's Tops", "ebay": "Fashion > Shirts"})

    async def test_incomplete_tree_blocks_category_selection(self):
        self.db.get(CategoryTree, "ebay").status = "paused"
        self.db.commit()
        with self.assertRaisesRegex(RuntimeError, "Finish category-tree extraction.*ebay"):
            await select_categories(self.db, None, "tee", "", ["ebay"])
