from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from vendoo_studio import config


def _load_make_icon() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "desktop" / "make_icon.py"
    spec = importlib.util.spec_from_file_location("make_icon", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.keys = (
            "VENDOO_STUDIO_DATA_DIR",
            "VENDOO_STUDIO_RESOURCE_DIR",
            "VENDOO_STUDIO_PACKAGED",
            "VENDOO_STUDIO_SKILLS_DIR",
            "VENDOO_STUDIO_EXTENSION_DIR",
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

    def test_extension_dir_has_manifest_and_icons(self):
        os.environ.pop("VENDOO_STUDIO_EXTENSION_DIR", None)
        extension = config.extension_source_dir()
        self.assertTrue((extension / "manifest.json").is_file(), extension)
        for name in ("icon16.png", "icon32.png", "icon48.png", "icon128.png"):
            self.assertTrue((extension / "icons" / name).is_file(), name)

    def test_extension_icons_are_the_macos_app_icon_source(self):
        from PIL import Image

        make_icon = _load_make_icon()
        source = Path(__file__).resolve().parents[3] / "vendoo-extension" / "icons" / "icon128.png"
        chrome = Image.open(source).convert("RGBA")
        self.assertEqual(make_icon.SOURCE_ICON.resolve(), source.resolve())
        self.assertEqual(make_icon.render_icon(128).tobytes(), chrome.tobytes())
        favicon = Path(__file__).resolve().parents[2] / "public" / "favicon.png"
        self.assertEqual(
            Image.open(favicon).convert("RGBA").tobytes(),
            make_icon.render_icon(32).tobytes(),
        )
