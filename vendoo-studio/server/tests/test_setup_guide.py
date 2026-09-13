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


if __name__ == "__main__":
    unittest.main()
