from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vendoo_studio import config


class ReleaseChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _env(self, **values: str):
        env = {key: value for key, value in os.environ.items() if key != "VENDOO_STUDIO_CHANNEL"}
        env["VENDOO_STUDIO_RESOURCE_DIR"] = str(self.root)
        env.update(values)
        return patch.dict(os.environ, env, clear=True)

    def test_defaults_to_production_without_build_info(self):
        with self._env():
            self.assertEqual(config.channel_name(), "production")

    def test_reads_channel_from_build_info(self):
        (self.root / "build_info.json").write_text(json.dumps({"sha": "abc", "channel": "staging"}), encoding="utf-8")
        with self._env():
            self.assertEqual(config.channel_name(), "staging")

    def test_env_overrides_build_info(self):
        (self.root / "build_info.json").write_text(json.dumps({"channel": "staging"}), encoding="utf-8")
        with self._env(VENDOO_STUDIO_CHANNEL="production"):
            self.assertEqual(config.channel_name(), "production")

    def test_unknown_channel_falls_back_to_production(self):
        with self._env(VENDOO_STUDIO_CHANNEL="nightly"):
            self.assertEqual(config.channel_name(), "production")

    def test_staging_is_isolated_from_production(self):
        production = config.CHANNELS["production"]
        staging = config.CHANNELS["staging"]
        for key in ("app_name", "bundle_id", "release_tag", "port", "extension_suffix"):
            self.assertNotEqual(production[key], staging[key])


if __name__ == "__main__":
    unittest.main()
