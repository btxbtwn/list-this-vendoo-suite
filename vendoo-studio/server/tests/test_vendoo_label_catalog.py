"""On-disk Vendoo label id → name catalog."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from vendoo_studio.services import vendoo_label_catalog as catalog


class LabelCatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._prev = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        os.environ["VENDOO_STUDIO_DATA_DIR"] = self.tmp.name
        import vendoo_studio.config as config

        self._config_data = config.DATA_DIR
        config.DATA_DIR = self.tmp.name
        catalog.clear_for_tests()

    def tearDown(self):
        import vendoo_studio.config as config

        config.DATA_DIR = self._config_data
        if self._prev is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._prev
        catalog.clear_for_tests()

    def test_looks_like_label_id(self):
        self.assertTrue(catalog.looks_like_label_id("JC7rDodgOQtVOWgwDqe3"))
        self.assertFalse(catalog.looks_like_label_id("To List"))
        self.assertFalse(catalog.looks_like_label_id("A19"))
        self.assertFalse(catalog.looks_like_label_id(""))

    def test_remember_and_apply_survive_reload(self):
        catalog.remember({
            "g8MHWF7KiscANFLZRGyM": "Women",
            "0kGVwda9cRk55wmfd3Bq": "To List",
        })
        catalog._memory = None  # force disk read
        self.assertEqual(
            catalog.apply(["g8MHWF7KiscANFLZRGyM", "Already", "0kGVwda9cRk55wmfd3Bq"]),
            ["Women", "Already", "To List"],
        )
        self.assertTrue((Path(self.tmp.name) / catalog.CATALOG_FILE).exists())

    def test_remember_from_label_details_rows(self):
        catalog.remember([
            {"id": "UOYZA8oYMxY5fwBzyP2Q", "name": "Bin 4"},
            {"id": "skip", "name": ""},
        ])
        self.assertEqual(catalog.load(), {"UOYZA8oYMxY5fwBzyP2Q": "Bin 4"})


if __name__ == "__main__":
    unittest.main()
