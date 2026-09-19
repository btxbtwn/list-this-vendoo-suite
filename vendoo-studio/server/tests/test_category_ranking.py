from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base
from vendoo_studio.models.catalog import CategoryTreeNode
from vendoo_studio.services.category_selection import _leaves_matching_query

TITLE = "GB Girls XL Oatmeal Cat Graphic Tee Cap Sleeve Hi-Low"

PATHS = [
    "Business & Industrial > Fasteners & Hardware > Fastener Nuts > Tee Nuts",
    "Toys & Collectibles > Dress Up & Pretend Play > Play Teepees",
    "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
    "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops > Graphic Tees",
]


class CategoryRankingTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        for i, path in enumerate(PATHS):
            self.db.add(CategoryTreeNode(
                marketplace="ebay", category_id=str(i), parent_id="", path=path,
                label=path.rsplit(">", 1)[-1].strip(), is_leaf=True, has_children=False,
            ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_a_token_must_be_a_whole_word(self):
        """"tee" is not a match for "Teepees" — substring scoring put a t-shirt
        under Play Teepees and Fastener Nuts."""
        paths = [n.path for n in _leaves_matching_query(self.db, "ebay", TITLE)]
        self.assertNotIn(PATHS[1], paths)

    def test_the_clothing_leaf_outranks_the_hardware_one(self):
        """Ties used to break alphabetically, so "Business & Industrial" won."""
        paths = [n.path for n in _leaves_matching_query(self.db, "ebay", TITLE)]
        self.assertEqual(paths[0], PATHS[3])
        self.assertLess(paths.index(PATHS[3]), paths.index(PATHS[0]))

    def test_a_prefix_is_applied_by_the_database(self):
        rows = _leaves_matching_query(
            self.db, "ebay", TITLE,
            "Clothing, Shoes & Accessories > Women",
        )
        self.assertTrue(rows)
        for node in rows:
            self.assertTrue(node.path.startswith("Clothing, Shoes & Accessories > Women"))

    def test_a_label_cannot_act_as_a_wildcard(self):
        """Paths carry % and _ in the wild; they must not widen the LIKE."""
        self.db.add(CategoryTreeNode(
            marketplace="ebay", category_id="99", parent_id="", path="Odd > 100%_Cotton Tee",
            label="100%_Cotton Tee", is_leaf=True, has_children=False,
        ))
        self.db.commit()
        rows = _leaves_matching_query(self.db, "ebay", TITLE, "Odd")
        self.assertEqual([n.path for n in rows], ["Odd > 100%_Cotton Tee"])
