from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services import user_settings


class SetupGuideSettingsTest(unittest.TestCase):
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

    def test_defaults_to_not_dismissed(self):
        self.assertFalse(user_settings.setup_guide_dismissed())

    def test_dismiss_persists_to_settings_json(self):
        self.assertEqual(user_settings.dismiss_setup_guide(), {"ok": True, "dismissed": True})
        self.assertTrue(user_settings.setup_guide_dismissed())
        stored = json.loads(Path(self.tmp.name, "settings.json").read_text())
        self.assertTrue(stored["setup_guide_dismissed"])

    def test_listing_provider_preference_defaults_and_persists(self):
        self.assertEqual(user_settings.get_listing_provider_order(), ("chatgpt", "mimo"))
        self.assertEqual(
            user_settings.set_listing_provider_order("mimo", "chatgpt"),
            {"primary": "mimo", "fallback": "chatgpt"},
        )
        self.assertEqual(user_settings.get_listing_provider_order(), ("mimo", "chatgpt"))
        stored = json.loads(Path(self.tmp.name, "settings.json").read_text())
        self.assertEqual(stored["listing_provider"], {"primary": "mimo", "fallback": "chatgpt"})
        self.assertEqual(
            user_settings.set_listing_provider_order("chatgpt", "none"),
            {"primary": "chatgpt", "fallback": "none"},
        )
        with self.assertRaises(ValueError):
            user_settings.set_listing_provider_order("claude")
        with self.assertRaises(ValueError):
            user_settings.set_listing_provider_order("chatgpt", "chatgpt")

    def test_legacy_string_preference_maps_to_primary_and_other_fallback(self):
        Path(self.tmp.name, "settings.json").write_text(json.dumps({"listing_provider": "mimo"}))
        self.assertEqual(user_settings.get_listing_provider_order(), ("mimo", "chatgpt"))

    def test_ui_prefs_default_and_persist(self):
        self.assertEqual(
            user_settings.get_ui_prefs(),
            {
                "recent_vendoo_labels": [],
                "settled_shelf_expanded": True,
                "hidden_vendoo_labels": [],
                "theme": "dark",
            },
        )
        self.assertEqual(
            user_settings.set_ui_prefs(settled_shelf_expanded=False, theme="light"),
            {
                "recent_vendoo_labels": [],
                "settled_shelf_expanded": False,
                "hidden_vendoo_labels": [],
                "theme": "light",
            },
        )
        self.assertEqual(
            user_settings.remember_vendoo_labels("Vintage, Nike, vintage"),
            ["Vintage", "Nike"],
        )
        stored = json.loads(Path(self.tmp.name, "settings.json").read_text())
        self.assertEqual(stored["ui"]["settled_shelf_expanded"], False)
        self.assertEqual(stored["ui"]["recent_vendoo_labels"], ["Vintage", "Nike"])
        self.assertEqual(stored["ui"]["theme"], "light")
        with self.assertRaises(ValueError):
            user_settings.set_ui_prefs(theme="solarized")

    def test_forgotten_label_stays_hidden_until_restored(self):
        user_settings.remember_vendoo_labels("Vintage, Nike")
        prefs = user_settings.forget_vendoo_label("vintage")
        self.assertEqual(prefs["recent_vendoo_labels"], ["Nike"])
        self.assertEqual(prefs["hidden_vendoo_labels"], ["vintage"])
        # Re-saving a listing that still has the label doesn't bring it back.
        self.assertEqual(user_settings.remember_vendoo_labels("Vintage, Nike"), ["Nike"])
        # Typing it into a listing again does.
        self.assertEqual(
            user_settings.remember_vendoo_labels("Vintage, Nike", ["Vintage"]),
            ["Vintage", "Nike"],
        )
        self.assertEqual(user_settings.get_ui_prefs()["hidden_vendoo_labels"], [])
        with self.assertRaises(ValueError):
            user_settings.forget_vendoo_label("  ")


class SetupGuideRouteTest(unittest.TestCase):
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

    def test_dismiss_endpoint_persists(self):
        saved = self.client.post("/api/settings/setup-guide/dismiss")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json(), {"ok": True, "dismissed": True})
        self.assertTrue(user_settings.setup_guide_dismissed())
        again = self.client.post("/api/settings/setup-guide/dismiss")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), {"ok": True, "dismissed": True})

    def test_preferred_provider_endpoint_persists(self):
        saved = self.client.put(
            "/api/settings/provider/preferred",
            json={"primary": "mimo", "fallback": "none"},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json(), {"ok": True, "primary": "mimo", "fallback": "none"})
        self.assertEqual(user_settings.get_listing_provider_order(), ("mimo", "none"))
        bad = self.client.put("/api/settings/provider/preferred", json={"primary": "claude"})
        self.assertEqual(bad.status_code, 422)

    def test_data_folder_and_ui_endpoints(self):
        folder = self.client.get("/api/settings/data-folder")
        self.assertEqual(folder.status_code, 200)
        body = folder.json()
        self.assertEqual(body["path"], self.tmp.name)
        self.assertIn("vendoo_studio.db", body["contains"])
        self.assertIn("Keychain", body["secrets"])

        ui = self.client.get("/api/settings/ui")
        self.assertEqual(ui.status_code, 200)
        self.assertEqual(ui.json()["settled_shelf_expanded"], True)
        self.assertEqual(ui.json()["theme"], "dark")

        saved = self.client.put(
            "/api/settings/ui",
            json={"settled_shelf_expanded": False, "remember_labels": "Thrifted", "theme": "system"},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["settled_shelf_expanded"], False)
        self.assertEqual(saved.json()["recent_vendoo_labels"], ["Thrifted"])
        self.assertEqual(saved.json()["theme"], "system")

        forgot = self.client.put("/api/settings/ui", json={"forget_label": "Thrifted"})
        self.assertEqual(forgot.status_code, 200)
        self.assertEqual(forgot.json()["recent_vendoo_labels"], [])
        self.assertEqual(forgot.json()["theme"], "system")
        bad_theme = self.client.put("/api/settings/ui", json={"theme": "solarized"})
        self.assertEqual(bad_theme.status_code, 400)
        self.assertEqual(forgot.json()["hidden_vendoo_labels"], ["Thrifted"])

        status = self.client.get("/api/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["data_dir"], self.tmp.name)

    def test_listing_formulas_endpoint_defaults_and_persists(self):
        from vendoo_studio.services.skill_formulas import (
            DEFAULT_DESCRIPTION_FORMULA,
            DEFAULT_TITLE_FORMULA,
            description_formula_markers,
            listing_formula_rules,
        )

        got = self.client.get("/api/settings/formulas")
        self.assertEqual(got.status_code, 200)
        body = got.json()
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["title"], "")
        self.assertEqual(body["description"], "")
        self.assertEqual(body["default_title"], DEFAULT_TITLE_FORMULA)
        self.assertEqual(body["default_description"], DEFAULT_DESCRIPTION_FORMULA)
        self.assertEqual(description_formula_markers(), ("flaws:", "measurements:"))

        saved = self.client.put(
            "/api/settings/formulas",
            json={
                "title": "{BRAND} {ITEM}",
                "description": "Short pitch.\n\nNotes: {detail}\n\nMeasurements: {meas}",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["title"], "{BRAND} {ITEM}")
        self.assertIn("Notes:", saved.json()["description"])
        self.assertEqual(user_settings.get_listing_formulas()["title"], "{BRAND} {ITEM}")
        self.assertEqual(description_formula_markers(), ("measurements:", "notes:"))
        self.assertIn("{BRAND} {ITEM}", listing_formula_rules())
        self.assertIn("Notes: {detail}", listing_formula_rules())

        cleared = self.client.put("/api/settings/formulas", json={"title": "", "description": ""})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["title"], "")
        self.assertEqual(cleared.json()["description"], "")
        self.assertEqual(user_settings.get_listing_formulas(), {})
        self.assertEqual(description_formula_markers(), ("flaws:", "measurements:"))


if __name__ == "__main__":
    unittest.main()
