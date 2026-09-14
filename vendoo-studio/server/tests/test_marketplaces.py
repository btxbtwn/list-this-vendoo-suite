from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services import marketplaces


class MarketplaceSettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._data = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VENDOO_STUDIO_DATA_DIR"] = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()
        if self._data is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._data

    def test_defaults_to_fillable_platforms(self):
        self.assertEqual(marketplaces.get_selected_marketplaces(), list(marketplaces.FILLABLE_MARKETPLACES))
        self.assertEqual(marketplaces.selected_fillable_platforms(), list(marketplaces.FILLABLE_MARKETPLACES))

    def test_persists_catalog_order_and_strips_unsupported(self):
        selected = marketplaces.set_selected_marketplaces(["ebay", "ebay", "poshmark"])
        self.assertEqual(selected, ["ebay", "poshmark"])
        self.assertEqual(marketplaces.get_selected_marketplaces(), ["ebay", "poshmark"])
        self.assertEqual(marketplaces.selected_fillable_platforms(), ["ebay", "poshmark"])

        payload = json.loads(Path(self.tmp.name, "settings.json").read_text())
        payload["marketplaces"] = ["ebay", "facebook", "shopify", "not-a-market"]
        Path(self.tmp.name, "settings.json").write_text(json.dumps(payload))
        # Unknown on read → defaults. Unsupported alone is stripped when readable.
        self.assertEqual(marketplaces.get_selected_marketplaces(), list(marketplaces.FILLABLE_MARKETPLACES))

        payload["marketplaces"] = ["ebay", "facebook", "shopify", "poshmark"]
        Path(self.tmp.name, "settings.json").write_text(json.dumps(payload))
        self.assertEqual(marketplaces.get_selected_marketplaces(), ["ebay", "poshmark"])
        rewritten = json.loads(Path(self.tmp.name, "settings.json").read_text())
        self.assertEqual(rewritten["marketplaces"], ["ebay", "poshmark"])

    def test_rejects_unknown_on_write(self):
        with self.assertRaises(ValueError):
            marketplaces.set_selected_marketplaces(["ebay", "not-a-market"])

    def test_rejects_unsupported_on_write(self):
        with self.assertRaises(ValueError) as ctx:
            marketplaces.set_selected_marketplaces(["ebay", "facebook", "shopify"])
        message = str(ctx.exception)
        self.assertIn("Facebook", message)
        self.assertIn("cannot be selected for Send", message)

    def test_empty_selection_is_general_only(self):
        self.assertEqual(marketplaces.set_selected_marketplaces([]), [])
        self.assertEqual(marketplaces.selected_fillable_platforms(), [])


class MarketplaceSettingsRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._data = os.environ.get("VENDOO_STUDIO_DATA_DIR")
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["VENDOO_STUDIO_DATA_DIR"] = self.tmp.name
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        if self._data is None:
            os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        else:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = self._data

    def test_get_and_put_marketplaces(self):
        empty = self.client.get("/api/settings/marketplaces")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["selected"], list(marketplaces.FILLABLE_MARKETPLACES))
        self.assertEqual(empty.json()["fillable"], list(marketplaces.FILLABLE_MARKETPLACES))
        self.assertEqual([item["id"] for item in empty.json()["available"]], list(marketplaces.KNOWN_MARKETPLACES))

        saved = self.client.put("/api/settings/marketplaces", json={"selected": ["poshmark", "poshmark"]})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["selected"], ["poshmark"])
        self.assertEqual(saved.json()["fillable"], ["poshmark"])

        rejected_unsupported = self.client.put(
            "/api/settings/marketplaces",
            json={"selected": ["poshmark", "facebook"]},
        )
        self.assertEqual(rejected_unsupported.status_code, 400)
        self.assertIn("cannot be selected for Send", rejected_unsupported.json()["detail"])

        rejected = self.client.put("/api/settings/marketplaces", json={"selected": ["ebay", "nope"]})
        self.assertEqual(rejected.status_code, 400)


if __name__ == "__main__":
    unittest.main()
