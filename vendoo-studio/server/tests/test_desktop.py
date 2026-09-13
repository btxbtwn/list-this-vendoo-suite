from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from vendoo_studio import desktop
from vendoo_studio.routes import desktop as desktop_routes


class StudioWindowChromeTest(unittest.TestCase):
    def test_window_kwargs_hide_native_titlebar(self):
        kwargs = desktop.studio_window_kwargs()
        self.assertTrue(kwargs["frameless"])
        self.assertFalse(kwargs["easy_drag"])
        self.assertTrue(kwargs["shadow"])
        self.assertEqual(kwargs["background_color"], desktop.WINDOW_BACKGROUND)
        self.assertEqual(kwargs["min_size"], desktop.MIN_WINDOW_SIZE)

    def test_window_kwargs_use_chrome_extension_icon(self):
        kwargs = desktop.studio_window_kwargs()
        icon = desktop.extension_app_icon_path()
        self.assertIsNotNone(icon)
        self.assertEqual(kwargs["icon"], str(icon))
        self.assertEqual(icon.name, "icon128.png")

    def test_install_bundle_icon_copies_chrome_extension_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            resources = Path(tmp) / "Resources"
            name = desktop.install_bundle_icon(resources)
            self.assertEqual(name, "AppIcon.png")
            copied = resources / "AppIcon.png"
            source = desktop.extension_app_icon_path()
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.read_bytes(), source.read_bytes())

    def test_titlebar_matches_t3_code(self):
        self.assertEqual(desktop.TITLEBAR_HEIGHT_PX, 38)
        self.assertEqual(desktop.TRAFFIC_LIGHT_SIZE_PX, 12.0)
        self.assertEqual(desktop.TRAFFIC_LIGHT_GAP_PX, 8.0)
        self.assertEqual(desktop.TRAFFIC_LIGHT_X_PX, 16.0)

    def test_traffic_light_rect_matches_electron_hidden_inset(self):
        close = desktop.traffic_light_rect(0, 38)
        miniaturize = desktop.traffic_light_rect(1, 38)
        zoom = desktop.traffic_light_rect(2, 38)
        self.assertEqual(close, (16.0, 13.0, 12.0, 12.0))
        self.assertEqual(miniaturize, (36.0, 13.0, 12.0, 12.0))
        self.assertEqual(zoom, (56.0, 13.0, 12.0, 12.0))

    def test_traffic_light_rect_stays_in_t3_band_when_os_titlebar_is_taller(self):
        close = desktop.traffic_light_rect(0, 52)
        self.assertEqual(close, (16.0, 27.0, 12.0, 12.0))

    def test_create_studio_window_applies_chrome_before_show(self):
        class Event:
            def __init__(self) -> None:
                self.handlers: list = []

            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self

        events = SimpleNamespace(before_show=Event(), shown=Event(), restored=Event(), resized=Event())
        window = SimpleNamespace(events=events)
        webview = SimpleNamespace(create_window=MagicMock(return_value=window))

        created = desktop.create_studio_window(webview)

        self.assertIs(created, window)
        webview.create_window.assert_called_once()
        _, kwargs = webview.create_window.call_args
        self.assertTrue(kwargs["frameless"])
        self.assertEqual(kwargs["background_color"], desktop.WINDOW_BACKGROUND)
        self.assertEqual(events.before_show.handlers, [desktop.apply_unified_macos_chrome])
        self.assertEqual(events.shown.handlers, [desktop.apply_unified_macos_chrome])
        self.assertEqual(events.restored.handlers, [desktop.apply_unified_macos_chrome])
        self.assertEqual(events.resized.handlers, [])

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
        container = MagicMock()
        container.frame.return_value.size.height = 38.0
        close.superview.return_value = container
        native = MagicMock()
        native.styleMask.return_value = 0
        native.collectionBehavior.return_value = 0
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
            NSControlSizeSmall=1,
            NSFullScreenWindowMask=1 << 14,
            NSWindowCollectionBehaviorFullScreenNone=1 << 9,
            NSWindowCollectionBehaviorFullScreenPrimary=1 << 7,
            NSAppearanceNameDarkAqua="dark",
            NSMakeRect=lambda x, y, w, h: (x, y, w, h),
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
        native.setCollectionBehavior_.assert_called_once_with(1 << 9)
        close.setHidden_.assert_called_once_with(False)
        miniaturize.setHidden_.assert_called_once_with(False)
        zoom.setHidden_.assert_called_once_with(False)
        close.setControlSize_.assert_called_once_with(1)
        close.setFrame_.assert_called_once_with((16.0, 13.0, 12.0, 12.0))
        miniaturize.setFrame_.assert_called_once_with((36.0, 13.0, 12.0, 12.0))
        zoom.setFrame_.assert_called_once_with((56.0, 13.0, 12.0, 12.0))
        titlebar.setBackgroundColor_.assert_called_once_with("clear")

    def test_apply_chrome_skips_layout_in_fullscreen(self):
        close = MagicMock()
        native = MagicMock()
        native.styleMask.return_value = 1 << 14
        native.standardWindowButton_.return_value = close
        appkit = SimpleNamespace(
            NSFullScreenWindowMask=1 << 14,
            NSWindowCollectionBehaviorFullScreenNone=1 << 9,
            NSWindowCollectionBehaviorFullScreenPrimary=1 << 7,
            NSWindowCloseButton=0,
        )
        window = SimpleNamespace(native=native)

        with (
            patch.object(desktop.sys, "platform", "darwin"),
            patch.dict(sys.modules, {"AppKit": appkit}),
        ):
            desktop.apply_unified_macos_chrome(window)

        native.setCollectionBehavior_.assert_not_called()
        native.setTitlebarAppearsTransparent_.assert_not_called()
        close.setFrame_.assert_not_called()


class ConnectChromeRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_connect_chrome_opens_everyday_chrome(self):
        with patch.object(
            desktop_routes,
            "relaunch_studio_chrome",
            return_value={"ok": True, "visible": True},
        ) as launch, patch(
            "vendoo_studio.services.chrome_bridge.extension_reload_token_if_needed",
            return_value=None,
        ):
            result = await desktop_routes.connect_chrome()
        launch.assert_called_once_with(visible=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["via"], "chrome")
        self.assertNotIn("extension_reload", result)

    async def test_connect_chrome_reloads_stale_worker(self):
        with patch.object(
            desktop_routes,
            "relaunch_studio_chrome",
            return_value={"ok": True, "visible": True},
        ), patch(
            "vendoo_studio.services.chrome_bridge.extension_reload_token_if_needed",
            return_value="gen-1",
        ), patch(
            "vendoo_studio.routes.extension.request_extension_reload",
            return_value=True,
        ) as reload:
            result = await desktop_routes.connect_chrome()
        reload.assert_awaited_once_with("gen-1")
        self.assertTrue(result["extension_reload"])
