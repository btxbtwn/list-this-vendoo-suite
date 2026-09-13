from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services import hidden_fields


class HiddenFieldsServiceTest(unittest.TestCase):
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

    def test_hide_always_and_on_one_listing(self):
        always = hidden_fields.hide_field("Etsy", "Custom Property", "always", label="Custom Property")
        self.assertEqual(always["always"], [{"marketplace": "etsy", "field": "custom property", "label": "Custom Property"}])
        self.assertEqual(always["listing"], [])

        listing = hidden_fields.hide_field(
            "depop",
            "Worldwide Shipping",
            "listing",
            conversation_id="conv-1",
            label="Worldwide Shipping",
        )
        self.assertEqual(len(listing["always"]), 1)
        self.assertEqual(listing["listing"], [{"marketplace": "depop", "field": "worldwide shipping", "label": "Worldwide Shipping"}])

        other = hidden_fields.hidden_fields("conv-2")
        self.assertEqual(len(other["always"]), 1)
        self.assertEqual(other["listing"], [])

        same = hidden_fields.hidden_fields("conv-1")
        self.assertEqual(len(same["listing"]), 1)

    def test_always_hide_replaces_listing_hide(self):
        hidden_fields.hide_field("etsy", "holiday", "listing", conversation_id="conv-1", label="Holiday")
        hidden_fields.hide_field("etsy", "holiday", "always", conversation_id="conv-1", label="Holiday")
        payload = hidden_fields.hidden_fields("conv-1")
        self.assertEqual(payload["always"], [{"marketplace": "etsy", "field": "holiday", "label": "Holiday"}])
        self.assertEqual(payload["listing"], [])

    def test_restore_only_that_scope(self):
        hidden_fields.hide_field("etsy", "pattern", "always", label="Pattern")
        hidden_fields.hide_field("etsy", "pattern", "listing", conversation_id="conv-1", label="Pattern")
        hidden_fields.restore_field("etsy", "pattern", "listing", conversation_id="conv-1")
        payload = hidden_fields.hidden_fields("conv-1")
        self.assertEqual(len(payload["always"]), 1)
        self.assertEqual(payload["listing"], [])

        hidden_fields.restore_field("etsy", "pattern", "always")
        self.assertEqual(hidden_fields.hidden_fields()["always"], [])

    def test_listing_scope_requires_conversation(self):
        with self.assertRaises(ValueError):
            hidden_fields.hide_field("etsy", "holiday", "listing")
        with self.assertRaises(ValueError):
            hidden_fields.restore_field("etsy", "holiday", "listing")

    def test_persists_to_settings_json(self):
        hidden_fields.hide_field("mercari", "Tags", "always", label="Tags")
        stored = json.loads(Path(self.tmp.name, "settings.json").read_text())
        self.assertEqual(stored["hidden_fields"]["always"][0]["field"], "tags")


class HiddenFieldsRouteTest(unittest.TestCase):
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

    def test_get_put_delete_hidden_fields(self):
        empty = self.client.get("/api/settings/hidden-fields")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json(), {"always": [], "listing": []})

        saved = self.client.put(
            "/api/settings/hidden-fields",
            json={"marketplace": "etsy", "field": "Custom Property", "label": "Custom Property", "scope": "always"},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["always"][0]["field"], "custom property")

        listing = self.client.put(
            "/api/settings/hidden-fields",
            json={
                "marketplace": "depop",
                "field": "Worldwide Shipping",
                "label": "Worldwide Shipping",
                "scope": "listing",
                "conversation_id": "abc123",
            },
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()["always"]), 1)
        self.assertEqual(len(listing.json()["listing"]), 1)

        fetched = self.client.get("/api/settings/hidden-fields", params={"conversation_id": "abc123"})
        self.assertEqual(len(fetched.json()["always"]), 1)
        self.assertEqual(len(fetched.json()["listing"]), 1)

        restored = self.client.request(
            "DELETE",
            "/api/settings/hidden-fields",
            json={"marketplace": "etsy", "field": "custom property", "scope": "always"},
        )
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()["always"], [])

        rejected = self.client.put(
            "/api/settings/hidden-fields",
            json={"marketplace": "etsy", "field": "holiday", "scope": "listing"},
        )
        self.assertEqual(rejected.status_code, 400)


if __name__ == "__main__":
    unittest.main()
