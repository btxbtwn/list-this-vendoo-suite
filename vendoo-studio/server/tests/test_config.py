from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from vendoo_studio import config


class ConfigPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.keys = (
            "VENDOO_STUDIO_DATA_DIR",
            "VENDOO_STUDIO_RESOURCE_DIR",
            "VENDOO_STUDIO_PACKAGED",
            "VENDOO_STUDIO_SKILLS_DIR",
            "VENDOO_STUDIO_EXTENSION_DIR",
            "VENDOO_STUDIO_HOST",
        )
        self.saved = {key: os.environ.get(key) for key in self.keys}

    def tearDown(self) -> None:
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_user_data_dir_uses_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["VENDOO_STUDIO_DATA_DIR"] = tmp
            self.assertEqual(config.user_data_root(), Path(tmp).resolve())

    def test_packaged_flag_from_env(self):
        os.environ.pop("VENDOO_STUDIO_PACKAGED", None)
        self.assertFalse(config.is_packaged())
        os.environ["VENDOO_STUDIO_PACKAGED"] = "1"
        self.assertTrue(config.is_packaged())

    def test_packaged_user_data_lives_in_application_support(self):
        os.environ["VENDOO_STUDIO_PACKAGED"] = "1"
        os.environ.pop("VENDOO_STUDIO_DATA_DIR", None)
        self.assertEqual(
            config.user_data_root(),
            Path.home() / "Library" / "Application Support" / "List This Studio",
        )

    def test_skills_dir_finds_repo_skill(self):
        os.environ.pop("VENDOO_STUDIO_SKILLS_DIR", None)
        skill = config.skills_dir() / "list-this" / "SKILL.md"
        self.assertTrue(skill.is_file(), skill)

    def test_bind_host_rejects_non_loopback(self):
        os.environ["VENDOO_STUDIO_HOST"] = "0.0.0.0"
        self.assertEqual(config.bind_host(), "127.0.0.1")
        os.environ["VENDOO_STUDIO_HOST"] = "127.0.0.1"
        self.assertEqual(config.bind_host(), "127.0.0.1")

    def test_cors_origins_are_loopback_only(self):
        joined = " ".join(config.CORS_ORIGINS)
        self.assertNotIn("vendoo.co", joined)
        self.assertNotIn("ebay.com", joined)
        for origin in config.CORS_ORIGINS:
            self.assertTrue(
                origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:"),
                origin,
            )
