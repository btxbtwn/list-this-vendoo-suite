from __future__ import annotations

import gzip
import json
import unittest

from vendoo_studio.services.category_tree_seed import default_seed_path
from vendoo_studio.services.garment_categories import (
    GARMENT_LEAVES,
    KIND_FALLBACKS,
    family_kind,
    garment_leaf,
)


def _seed_leaves() -> dict[str, set[str]]:
    with gzip.open(default_seed_path(), "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    leaves: dict[str, set[str]] = {}
    for node in payload["category_tree_nodes"]:
        if node.get("is_leaf") and not node.get("has_children"):
            leaves.setdefault(node["marketplace"], set()).add(node["path"])
    return leaves


class GarmentLeafTableTest(unittest.TestCase):
    """The tables name real leaves, so they cannot drift from the trees."""

    @classmethod
    def setUpClass(cls):
        cls.leaves = _seed_leaves()

    def test_every_mapped_path_is_a_real_leaf(self):
        for marketplace, departments in GARMENT_LEAVES.items():
            known = self.leaves.get(marketplace) or set()
            self.assertTrue(known, f"no seeded leaves for {marketplace}")
            for department, kinds in departments.items():
                for kind, path in kinds.items():
                    with self.subTest(marketplace=marketplace, department=department, kind=kind):
                        self.assertIn(path, known)

    def test_every_leaf_sits_in_its_own_department(self):
        for marketplace, departments in GARMENT_LEAVES.items():
            for department, kinds in departments.items():
                wanted = "women" if department == "women" else "men"
                for kind, path in kinds.items():
                    with self.subTest(marketplace=marketplace, department=department, kind=kind):
                        head = path.split(" > ")[0 if marketplace != "etsy" else 1].casefold()
                        self.assertIn(wanted, head)

    def test_fallbacks_do_not_loop_or_point_nowhere(self):
        known_kinds = {
            kind
            for departments in GARMENT_LEAVES.values()
            for kinds in departments.values()
            for kind in kinds
        }
        for kind, chain in KIND_FALLBACKS.items():
            for target in chain:
                with self.subTest(kind=kind):
                    self.assertIn(target, known_kinds)
                    self.assertNotEqual(target, kind)
        # A resolved chain terminates for every kind on every marketplace.
        for marketplace, departments in GARMENT_LEAVES.items():
            for department in departments:
                for kind in known_kinds:
                    garment_leaf(marketplace, department, kind)


class FamilyKindTest(unittest.TestCase):
    def test_reads_the_cut_a_title_names(self):
        cases = {
            ("dress", "Old Navy M Floral Midi Dress"): "dress_midi",
            ("dress", "Vintage Black Maxi Dress"): "dress_maxi",
            ("dress", "Silk Wrap Dress"): "dress_wrap",
            ("dress", "White Wedding Gown Dress"): "dress_wedding",
            ("jeans", "Levi's 8 High-Rise Skinny Jeans"): "jeans_skinny",
            ("jeans", "Wrangler Boot Cut Jeans"): "jeans_boot_cut",
            ("jeans", "Vintage Mom Jeans"): "jeans_boyfriend",
            ("pants", "Dockers Khakis Chinos"): "pants_chinos",
            ("pants", "Nike Track Pants Joggers"): "pants_joggers",
            ("shorts", "Old Navy Denim Jean Shorts"): "shorts_denim",
            ("shorts", "Nike Athletic Running Shorts"): "shorts_athletic",
            ("skirt", "Ann Taylor Black Pencil Skirt"): "skirt_pencil",
            ("skirt", "Pleated Tennis Mini Skirt"): "skirt_pleated",
        }
        for (family, title), wanted in cases.items():
            with self.subTest(title=title):
                self.assertEqual(family_kind(family, title), wanted)

    def test_a_cut_nobody_named_stays_empty(self):
        self.assertEqual(family_kind("dress", "Old Navy Floral Dress"), "")
        self.assertEqual(family_kind("jeans", "Levi's 501 Jeans"), "")


class GarmentLeafLookupTest(unittest.TestCase):
    def test_a_cut_falls_back_to_the_family_leaf(self):
        # Depop files every skinny jean under Bottoms > Jeans.
        self.assertEqual(
            garment_leaf("depop", "women", "jeans_skinny"), "Women > Bottoms > Jeans",
        )

    def test_a_marketplace_without_the_family_is_left_alone(self):
        # Mercari subdivides jeans and has no general Jeans leaf to fall back to.
        self.assertEqual(garment_leaf("mercari", "women", "jeans"), "")

    def test_men_get_their_own_branch(self):
        self.assertEqual(garment_leaf("mercari", "men", "tee"), "Men > Tops > T-shirts")
        self.assertEqual(garment_leaf("depop", "men", "jeans_skinny"), "Men > Bottoms > Jeans")
