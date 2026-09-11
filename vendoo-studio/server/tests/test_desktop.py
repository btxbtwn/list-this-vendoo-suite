from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from vendoo_studio import desktop


class StudioWindowChromeTest(unittest.TestCase):
    def test_window_kwargs_hide_native_titlebar(self):
        kwargs = desktop.studio_window_kwargs()
        self.assertTrue(kwargs["frameless"])
        self.assertFalse(kwargs["easy_drag"])
        self.assertTrue(kwargs["shadow"])
        self.assertEqual(kwargs["background_color"], desktop.WINDOW_BACKGROUND)
        self.assertEqual(kwargs["min_size"], desktop.MIN_WINDOW_SIZE)

    def test_create_studio_window_applies_chrome_before_show(self):
        class Event:
            def __init__(self) -> None:
                self.handlers: list = []

            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self

        events = SimpleNamespace(before_show=Event())
        window = SimpleNamespace(events=events)
        webview = SimpleNamespace(create_window=MagicMock(return_value=window))

        created = desktop.create_studio_window(webview)

        self.assertIs(created, window)
        webview.create_window.assert_called_once()
        _, kwargs = webview.create_window.call_args
        self.assertTrue(kwargs["frameless"])
        self.assertEqual(kwargs["background_color"], desktop.WINDOW_BACKGROUND)
        self.assertEqual(events.before_show.handlers, [desktop.apply_unified_macos_chrome])

    def test_hex_to_srgb(self):
        self.assertEqual(desktop._hex_to_srgb("#000000"), (0.0, 0.0, 0.0))
        self.assertEqual(desktop._hex_to_srgb("#ffffff"), (1.0, 1.0, 1.0))

    def test_apply_chrome_is_noop_off_macos(self):
        native = MagicMock()
        window = SimpleNamespace(native=native)
        with patch.object(desktop.sys, "platform", "linux"):
            desktop.apply_unified_macos_chrome(window)
        native.setTitlebarAppearsTransparent_.assert_not_called()

    def test_apply_chrome_restores_traffic_lights(self):
        close = MagicMock()
        miniaturize = MagicMock()
        zoom = MagicMock()
        titlebar = MagicMock()
        native = MagicMock()
        native.contentView.return_value.superview.return_value.subviews.return_value = [titlebar]
        native.standardWindowButton_.side_effect = lambda button: {
            0: close,
            1: miniaturize,
            2: zoom,
        }[button]

        appkit = SimpleNamespace(
            NSWindowTitleHidden=1,
            NSWindowCloseButton=0,
            NSWindowMiniaturizeButton=1,
            NSWindowZoomButton=2,
            NSAppearanceNameDarkAqua="dark",
            NSColor=SimpleNamespace(
                colorWithSRGBRed_green_blue_alpha_=MagicMock(return_value="black"),
                clearColor=MagicMock(return_value="clear"),
            ),
            NSAppearance=SimpleNamespace(appearanceNamed_=MagicMock(return_value="appearance")),
        )
        window = SimpleNamespace(native=native)

        with (
            patch.object(desktop.sys, "platform", "darwin"),
            patch.dict(sys.modules, {"AppKit": appkit}),
        ):
            desktop.apply_unified_macos_chrome(window)

        native.setTitlebarAppearsTransparent_.assert_called_once_with(True)
        native.setTitleVisibility_.assert_called_once_with(1)
        native.setAppearance_.assert_called_once_with("appearance")
        close.setHidden_.assert_called_once_with(False)
        miniaturize.setHidden_.assert_called_once_with(False)
        zoom.setHidden_.assert_called_once_with(False)
        titlebar.setBackgroundColor_.assert_called_once_with("clear")
