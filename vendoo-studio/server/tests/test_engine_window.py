from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"


class EngineWindowHelperTest(unittest.TestCase):
    def test_offscreen_engine_windows_are_not_treated_as_visible(self) -> None:
        text = (EXTENSION_DIR / "preview-screencast.js").read_text(encoding="utf-8")
        start = text.index("const ENGINE_LEFT")
        end = text.index("function stopPreviewPolling")
        helpers = text[start:end]
        script = helpers + """
const result = {
  hidden: isOffscreenEngineWindow({ id: 1, left: ENGINE_LEFT }),
  visible: isOffscreenEngineWindow({ id: 2, left: SHOW_LEFT }),
  missing: isOffscreenEngineWindow(null),
};
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(proc.stdout)
        self.assertTrue(result["hidden"])
        self.assertFalse(result["visible"])
        self.assertFalse(result["missing"])
