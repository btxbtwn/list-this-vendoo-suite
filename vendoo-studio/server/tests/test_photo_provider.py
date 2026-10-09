"""Photo analysis can run on a different provider than listing generation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vendoo_studio.services import listing_provider, user_settings


class PhotoProviderChoiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        settings = patch.object(
            user_settings, "settings_path", return_value=Path(self._tmp.name) / "settings.json"
        )
        settings.start()
        self.addCleanup(settings.stop)

    def test_defaults_to_the_listing_provider(self):
        self.assertEqual(user_settings.get_photo_provider_choice(), "same")

    def test_saves_a_choice(self):
        self.assertEqual(user_settings.set_photo_provider_choice("ChatGPT"), "chatgpt")
        self.assertEqual(user_settings.get_photo_provider_choice(), "chatgpt")

    def test_rejects_an_unknown_provider(self):
        with self.assertRaises(ValueError):
            user_settings.set_photo_provider_choice("gemini")


class GetPhotoProviderTest(unittest.TestCase):
    CHATGPT = object()
    CURSOR = object()

    def provider(self, choice: str, *, chatgpt: bool):
        with (
            patch.object(listing_provider, "get_photo_provider_choice", return_value=choice),
            patch.object(listing_provider, "get_listing_provider_order", return_value=("cursor", "none")),
            patch.object(listing_provider, "_chatgpt_provider", return_value=self.CHATGPT if chatgpt else None),
            patch.object(listing_provider, "_cursor_provider", return_value=self.CURSOR),
        ):
            return listing_provider.get_photo_provider()

    def test_same_uses_the_listing_provider(self):
        self.assertIs(self.provider("same", chatgpt=True), self.CURSOR)

    def test_a_ready_choice_reads_photos(self):
        self.assertIs(self.provider("chatgpt", chatgpt=True), self.CHATGPT)

    def test_a_choice_that_is_not_ready_falls_back_to_the_listing_provider(self):
        self.assertIs(self.provider("chatgpt", chatgpt=False), self.CURSOR)


class PhotoProviderRouteTest(unittest.TestCase):
    def test_settings_round_trip(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(user_settings, "settings_path", return_value=Path(tmp) / "settings.json"):
            client = TestClient(app)
            saved = client.put("/api/settings/provider/photos", json={"choice": "chatgpt"})
            self.assertEqual(saved.json(), {"ok": True, "photo_provider": "chatgpt"})
            self.assertEqual(user_settings.get_photo_provider_choice(), "chatgpt")
            self.assertEqual(client.put("/api/settings/provider/photos", json={"choice": "gemini"}).status_code, 422)
