from __future__ import annotations

import unittest
from unittest.mock import patch

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

    def test_apparel_intent_drops_hardware_candidates(self):
        """Semble/lexical hits can still surface Tee Nuts; choices must not."""
        from vendoo_studio.services.category_selection import _collect_choices

        with patch(
            "vendoo_studio.services.category_selection.search_catalog",
            return_value=[
                {"id": "0", "path": PATHS[0], "label": "Tee Nuts"},
                {"id": "3", "path": PATHS[3], "label": "Graphic Tees"},
            ],
        ):
            choices, _nodes = _collect_choices(
                self.db,
                ["ebay"],
                "women tee",
                {},
                "",
                analysis="category: Women's Graphic T-Shirt\nDepartment: Women",
                notes="",
            )
        paths = [row["path"] for row in choices["ebay"]]
        self.assertNotIn(PATHS[0], paths)
        self.assertIn(PATHS[3], paths)

    def test_tube_tops_stay_out_unless_listing_says_tube(self):
        from vendoo_studio.services.category_selection import _usable_search_node

        tube = CategoryTreeNode(
            marketplace="etsy", category_id="t", parent_id="",
            path="Clothing > Women's Clothing > Tops & Tees > Crop & Tube Tops > Tube Tops",
            label="Tube Tops", is_leaf=True, has_children=False,
        )
        self.assertFalse(_usable_search_node(
            tube, apparel=True, women_tops=True,
            context="Women scoop neck graphic tee",
        ))
        self.assertTrue(_usable_search_node(
            tube, apparel=True, women_tops=True,
            context="Women black tube top",
        ))

    def test_tank_tops_stay_out_unless_listing_says_tank(self):
        from vendoo_studio.services.category_selection import _usable_search_node

        tank = CategoryTreeNode(
            marketplace="poshmark", category_id="tank", parent_id="",
            path="Women > Tops > Tank Tops",
            label="Tank Tops", is_leaf=True, has_children=False,
        )
        self.assertFalse(_usable_search_node(
            tank, apparel=True, women_tops=True,
            context="Women Faded Glory short sleeve graphic tee",
        ))
        self.assertTrue(_usable_search_node(
            tank, apparel=True, women_tops=True,
            context="Women Faded Glory sleeveless tank",
        ))

    def test_tunics_stay_out_unless_listing_says_tunic(self):
        from vendoo_studio.services.category_selection import _usable_search_node

        tunic = CategoryTreeNode(
            marketplace="etsy", category_id="tunic", parent_id="",
            path="Clothing > Women's Clothing > Tops & Tees > Tunics",
            label="Tunics", is_leaf=True, has_children=False,
        )
        self.assertFalse(_usable_search_node(
            tunic, apparel=True, women_tops=True,
            context="Women notations floral button-up blouse short sleeve",
        ))
        self.assertTrue(_usable_search_node(
            tunic, apparel=True, women_tops=True,
            context="Women notations floral tunic top",
        ))

    def test_mens_item_drops_womens_category_candidates(self):
        """A keyword match must not override the explicitly stated department."""
        from vendoo_studio.services.category_selection import _collect_choices

        wrong_path = "Sporting Goods > Camping & Hiking > Clothing > Women's > Shirts, Tops & Sweaters"
        right_path = "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts"
        for category_id, path in (("wrong", wrong_path), ("right", right_path)):
            self.db.add(CategoryTreeNode(
                marketplace="ebay", category_id=category_id, parent_id="", path=path,
                label=path.rsplit(">", 1)[-1].strip(), is_leaf=True, has_children=False,
            ))
        self.db.commit()

        with patch(
            "vendoo_studio.services.category_selection.search_catalog",
            return_value=[
                {"id": "wrong", "path": wrong_path, "label": "Shirts, Tops & Sweaters"},
                {"id": "right", "path": right_path, "label": "T-Shirts"},
            ],
        ):
            choices, _nodes = _collect_choices(
                self.db,
                ["ebay"],
                "men t-shirt",
                {},
                "",
                analysis="- category: T-Shirt\n- department: Men",
            )

        self.assertEqual([row["path"] for row in choices["ebay"]], [right_path])
