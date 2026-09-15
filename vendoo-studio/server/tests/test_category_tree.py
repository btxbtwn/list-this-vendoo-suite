import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategorySchema, CategoryTree, CategoryTreeNode
from vendoo_studio.models.listing import Listing, ListingRevision  # noqa: F401
from vendoo_studio.services.catalog_index import (
    rebuild_catalog_index,
    reset_catalog_index_cache,
    search_catalog,
)
from vendoo_studio.services.category_selection import select_categories
from vendoo_studio.services.category_tree import store_children


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
        self.tmp = tempfile.TemporaryDirectory()
        self._data = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        os.environ["VENDOO_STUDIO_DATA_DIR"] = self.tmp.name
        reset_catalog_index_cache()
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
        rebuild_catalog_index(self.db)

    def tearDown(self):
        reset_catalog_index_cache()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()
        if self._data is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._data

    async def test_chooses_distinct_terminal_paths_from_each_tree(self):
        class Provider:
            async def chat(self, messages, stream=True):
                choices = json.loads(messages[-1]["content"])["choices"]
                yield json.dumps({"categories": {mp: rows[0]["id"] for mp, rows in choices.items()}})
        result = await select_categories(self.db, Provider(), "Women's cotton tops shirts", "", ["ebay"])
        self.assertEqual(result, {"general": "Clothing > Women's Tops", "ebay": "Fashion > Shirts"})

    async def test_rejects_invented_category_id(self):
        class Provider:
            async def chat(self, messages, stream=True):
                yield '{"categories": {"general": "invented", "ebay": "ebay-leaf"}}'
        with self.assertRaisesRegex(RuntimeError, "verified general category"):
            await select_categories(self.db, Provider(), "Women's Tops Shirts", "", ["ebay"])

    async def test_selectable_parent_still_descends_to_most_specific_category(self):
        for mp in ("general", "ebay"):
            self.db.get(CategoryTreeNode, (mp, mp + "-root")).is_leaf = True
        self.db.commit()
        rebuild_catalog_index(self.db)

        class Provider:
            async def chat(self, messages, stream=True):
                choices = json.loads(messages[-1]["content"])["choices"]
                yield json.dumps({"categories": {mp: rows[0]["id"] for mp, rows in choices.items()}})

        result = await select_categories(
            self.db, Provider(), "Women's Tops Shirts", "", ["ebay"], override="Clothing",
        )
        self.assertEqual(result, {"general": "Clothing > Women's Tops", "ebay": "Fashion > Shirts"})

    async def test_incomplete_tree_blocks_category_selection(self):
        self.db.get(CategoryTree, "ebay").status = "paused"
        self.db.commit()
        with self.assertRaisesRegex(RuntimeError, "Finish category-tree extraction.*ebay"):
            await select_categories(self.db, None, "tee", "", ["ebay"])


class CatalogIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._data = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        os.environ["VENDOO_STUDIO_DATA_DIR"] = self.tmp.name
        reset_catalog_index_cache()
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(CategoryTree(marketplace="general", status="complete", roots_loaded=True))
        self.db.add(CategoryTreeNode(
            marketplace="general", category_id="tops", parent_id="__root",
            label="Tops", path="Clothing > Women > Tops", is_leaf=True, has_children=False,
            children_loaded=True,
        ))
        self.db.add(CategoryTreeNode(
            marketplace="general", category_id="tees", parent_id="__root",
            label="T-Shirts", path="Clothing > Men > Shirts > T-Shirts", is_leaf=True,
            has_children=False, children_loaded=True,
        ))
        self.db.add(CategorySchema(
            id="schema-1",
            general_path="Clothing > Women > Tops",
            marketplace="general",
            category_path="Clothing > Women > Tops",
            fields=[{"label": "Brand", "key": "brand"}],
        ))
        self.db.commit()
        rebuild_catalog_index(self.db)

    def tearDown(self):
        reset_catalog_index_cache()
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()
        if self._data is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._data

    def test_search_returns_verified_leaf_for_womens_tops(self):
        hits = search_catalog(self.db, "women floral blouse tops", kind="category", top_k=5)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "tops")
        self.assertEqual(hits[0]["path"], "Clothing > Women > Tops")

    def test_search_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            search_catalog(self.db, "tops", kind="nope")

    def test_schema_search_finds_observed_fields(self):
        hits = search_catalog(self.db, "Women Tops Brand", kind="schema", top_k=5)
        self.assertTrue(any(hit.get("general_path") == "Clothing > Women > Tops" for hit in hits))

    def test_option_search_finds_condition_dropdown(self):
        hits = search_catalog(self.db, "general condition dropdown", kind="option", top_k=5)
        self.assertTrue(hits)
        self.assertTrue(any("Pre-Owned - Good" in (hit.get("options") or []) for hit in hits))

    def test_skill_search_returns_rule_snippets(self):
        from vendoo_studio.services.catalog_index import relevant_skill_rules
        text = relevant_skill_rules(self.db, "category path women's tops measurements")
        self.assertTrue(text.strip())

    def test_fill_helper_search_finds_extension_symbols(self):
        hits = search_catalog(self.db, "fill brand category", kind="fill", top_k=10)
        self.assertTrue(hits)
        self.assertTrue(any(hit.get("symbol") for hit in hits))

    def test_invented_doc_ids_are_not_returned(self):
        docs = Path(self.tmp.name) / "catalog-index" / "docs" / "categories" / "general"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "fake.md").write_text(
            "kind: category\nmarketplace: general\nid: invented\npath: Fake > Path\nlabel: Fake\n\nFake > Path\n",
            encoding="utf-8",
        )
        reset_catalog_index_cache()
        with patch("vendoo_studio.services.catalog_index._load_semble_index") as load:
            class FakeChunk:
                def __init__(self, content):
                    self.content = content

            class FakeResult:
                def __init__(self, content, score=1.0):
                    self.chunk = FakeChunk(content)
                    self.score = score

            class FakeIndex:
                def search(self, query, top_k=15):
                    return [FakeResult((docs / "fake.md").read_text(encoding="utf-8"))]

            load.return_value = FakeIndex()
            from vendoo_studio.services import catalog_index as mod
            mod._INDEX = FakeIndex()
            mod._STALE = False
            hits = search_catalog(self.db, "fake path", kind="category", top_k=5, ensure=False)
        self.assertEqual(hits, [])
