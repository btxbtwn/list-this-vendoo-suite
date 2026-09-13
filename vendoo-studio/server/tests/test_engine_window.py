from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"
PREVIEW = EXTENSION_DIR / "preview-screencast.js"
BACKGROUND = EXTENSION_DIR / "background.js"


def _helper_source() -> str:
    text = PREVIEW.read_text(encoding="utf-8")
    start = text.index("const ENGINE_LEFT")
    end = text.index("function stopPreviewPolling")
    return text[start:end]


def _run_helper_script(body: str) -> dict:
    script = _helper_source() + "\n" + body
    proc = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


class EngineWindowHelperTest(unittest.TestCase):
    def test_offscreen_engine_windows_are_not_treated_as_visible(self) -> None:
        result = _run_helper_script(
            """
const result = {
  hidden: isOffscreenEngineWindow({ id: 1, left: ENGINE_LEFT }),
  visible: isOffscreenEngineWindow({ id: 2, left: SHOW_LEFT }),
  missing: isOffscreenEngineWindow(null),
};
console.log(JSON.stringify(result));
"""
        )
        self.assertTrue(result["hidden"])
        self.assertFalse(result["visible"])
        self.assertFalse(result["missing"])

    def test_pick_onscreen_bounds_uses_existing_window_and_fallback(self) -> None:
        result = _run_helper_script(
            """
const result = {
  fromVisible: pickOnscreenBounds([
    { id: 1, left: ENGINE_LEFT, top: 0, width: 1280, height: 900, state: 'normal' },
    { id: 2, left: 120, top: 40, width: 1440, height: 800, state: 'normal' },
  ]),
  fallback: pickOnscreenBounds([]),
  boundsError: isWindowBoundsError({
    message: 'Invalid value for bounds. Bounds must be at least 50% within visible screen space.',
  }),
  otherError: isWindowBoundsError({ message: 'No window with id: 9' }),
};
console.log(JSON.stringify(result));
"""
        )
        self.assertEqual(result["fromVisible"]["left"], 120)
        self.assertEqual(result["fromVisible"]["top"], 40)
        self.assertEqual(result["fromVisible"]["width"], 1280)
        self.assertEqual(result["fromVisible"]["height"], 800)
        self.assertEqual(result["fallback"]["left"], 80)
        self.assertEqual(result["fallback"]["top"], 80)
        self.assertEqual(result["fallback"]["width"], 800)
        self.assertEqual(result["fallback"]["height"], 600)
        self.assertTrue(result["boundsError"])
        self.assertFalse(result["otherError"])

    def test_pick_onscreen_bounds_uses_display_work_area(self) -> None:
        result = _run_helper_script(
            """
const displays = [{
  isPrimary: true,
  isEnabled: true,
  workArea: { left: 1920, top: 25, width: 1512, height: 945 },
}];
const offscreen = { id: 1, left: ENGINE_LEFT, top: 0, width: 1280, height: 900, state: 'normal' };
const stale = { id: 2, left: -400, top: 40, width: 1440, height: 800, state: 'normal' };
const result = {
  fromDisplay: pickOnscreenBounds([offscreen, stale], displays),
  skippedStale: isMostlyOnscreen(stale, workAreasFromDisplays(displays)),
};
console.log(JSON.stringify(result));
"""
        )
        self.assertGreaterEqual(result["fromDisplay"]["left"], 1920)
        self.assertLess(
            result["fromDisplay"]["left"] + result["fromDisplay"]["width"],
            1920 + 1512,
        )
        self.assertGreaterEqual(result["fromDisplay"]["top"], 25)
        self.assertFalse(result["skippedStale"])

    def test_window_create_and_update_do_not_use_offscreen_coordinates(self) -> None:
        preview = PREVIEW.read_text(encoding="utf-8")
        background = BACKGROUND.read_text(encoding="utf-8")
        self.assertNotRegex(preview, r"left:\s*ENGINE_LEFT")
        self.assertNotRegex(preview, r"windows\.create\([^)]*left:\s*-")
        self.assertIn("createWindowSafe", preview)
        self.assertIn("openEverydayListingTab", background)
        self.assertIn("closeListingTab", background)
        self.assertIn("delete withoutTab.tabId", preview)
        self.assertIn("system.display", Path(EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertRegex(preview, r"focused:\s*false,\s*state:\s*'normal'")
        self.assertTrue(re.search(r"pickOnscreenBounds", preview))


class EverydayListingTabTest(unittest.TestCase):
    def test_listing_opens_a_tab_in_everyday_chrome(self) -> None:
        preview = PREVIEW.read_text(encoding="utf-8")
        background = BACKGROUND.read_text(encoding="utf-8")
        self.assertIn("currentEverydayWindowId", preview)
        self.assertIn("chrome.windows.getLastFocused", preview)
        self.assertIn("openEverydayListingTab", preview)
        self.assertIn("openEverydayListingTab", background)
        self.assertNotIn("openTabInHiddenWindow", preview)
        self.assertNotIn("openTabInHiddenWindow", background)
        self.assertNotIn("hidden Chrome window", background)
        self.assertIn("everyday Chrome window", background)

    def test_listing_tab_closes_when_the_job_finishes(self) -> None:
        background = BACKGROUND.read_text(encoding="utf-8")
        preview = PREVIEW.read_text(encoding="utf-8")
        self.assertIn("closeListingTab", background)
        self.assertIn("Closed listing tab", preview)
        self.assertGreaterEqual(background.count("await closeListingTab("), 4)

    def test_listing_does_not_bring_chrome_to_front(self) -> None:
        preview = PREVIEW.read_text(encoding="utf-8")
        background = BACKGROUND.read_text(encoding="utf-8")
        self.assertIn("active: foreground", preview)
        self.assertIn("focused: foreground", preview)
        start = preview.index("async function startJobPreview")
        start_fn = preview[start:]
        self.assertNotIn("showWindow", start_fn.split("chrome.debugger.onEvent", 1)[0])
        self.assertNotIn("hideWindow", start_fn.split("chrome.debugger.onEvent", 1)[0])
        self.assertIn("tabIsInFront", start_fn)
        self.assertIn("attachDebuggerPreview", start_fn)
        self.assertIn("foreground: true", background)
        self.assertIn("{ foreground }", background)
        patch_start = background.index("async function openListingForPatch")
        patch_end = background.index("async function runFillFields")
        patch = background[patch_start:patch_end]
        self.assertIn("openVisibleVendooWindow", patch)
        self.assertIn("function focusVendooListing", background)
        self.assertIn("await showWindow", background)
