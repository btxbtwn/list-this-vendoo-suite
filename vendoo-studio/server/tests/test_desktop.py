from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from vendoo_studio import desktop
from vendoo_studio.routes import desktop as desktop_routes


class StudioWindowChromeTest(unittest.TestCase):
    def test_enable_editable_context_menus_keeps_paste(self):
        class FakeMenu:
            def __init__(self, items):
                self._items = list(items)

            def itemArray(self):
                return list(self._items)

            def removeAllItems(self):
                self._items.clear()

            def addItem_(self, item):
                self._items.append(item)

        paste = SimpleNamespace(action=lambda: "paste:", title=lambda: "Paste")
        inspect = SimpleNamespace(action=lambda: "inspectElement:", title=lambda: "Inspect Element")
        menu = FakeMenu([paste, inspect])

        host = SimpleNamespace()
        cocoa = SimpleNamespace(BrowserView=SimpleNamespace(WebKitHost=host))
        with patch.dict(sys.modules, {
            "Foundation": SimpleNamespace(NSStringFromSelector=lambda action: str(action)),
            "webview": SimpleNamespace(),
            "webview.platforms": SimpleNamespace(),
            "webview.platforms.cocoa": cocoa,
        }):
            desktop.enable_editable_context_menus()
            self.assertTrue(callable(host.willOpenMenu_withEvent_))
            host.willOpenMenu_withEvent_(host, menu, None)
        titles = [item.title() for item in menu.itemArray()]
        self.assertEqual(titles, ["Paste"])

    def test_start_kwargs_use_chrome_extension_icon(self):
        with patch.object(desktop, "studio_app_menu", return_value=["menu"]):
            kwargs = desktop.studio_start_kwargs()
        icon = desktop.extension_app_icon_path()
        self.assertIsNotNone(icon)
        self.assertEqual(kwargs["icon"], str(icon))
        self.assertEqual(icon.name, "icon128.png")
        self.assertEqual(kwargs["menu"], ["menu"])

    def test_studio_app_menu_includes_update_actions(self):
        menu_mod = SimpleNamespace(
            Menu=lambda title, items=None: SimpleNamespace(title=title, items=items or []),
            MenuAction=lambda title, function: SimpleNamespace(title=title, function=function),
            MenuSeparator=lambda: SimpleNamespace(kind="separator"),
        )
        with patch.dict(sys.modules, {"webview": SimpleNamespace(), "webview.menu": menu_mod}):
            # Force re-import path inside studio_app_menu via ImportError-safe stub
            menus = desktop.studio_app_menu()
        titles = [menu.title for menu in menus]
        self.assertIn("__app__", titles)
        self.assertIn("Studio", titles)
        app_menu = next(menu for menu in menus if menu.title == "__app__")
        action_titles = [
            item.title for item in app_menu.items if getattr(item, "title", None)
        ]
        self.assertIn("Check for Updates…", action_titles)
        self.assertIn("Update and Restart…", action_titles)
        self.assertIn("Reinstall from GitHub…", action_titles)

    def test_update_status_message_up_to_date(self):
        self.assertEqual(
            desktop._update_status_message({"available": False}),
            f"{desktop.APP_NAME} is up to date.",
        )

    def test_menu_update_and_restart_applies_when_available(self):
        status = {"available": True, "short_sha": "abc1234", "summary": "Fix black screen"}
        applied = {"ok": True, "updated": True}
        with (
            patch.object(desktop, "studio_is_up", return_value=True),
            patch.object(desktop, "_http_check_updates", return_value=status),
            patch.object(desktop, "confirm_update_dialog", return_value=True),
            patch.object(desktop, "_http_apply_update", return_value=applied) as apply,
            patch.object(desktop, "notify") as notify,
            patch.object(desktop.threading.Thread, "start", lambda self: self.run()),
        ):
            desktop.menu_update_and_restart()
        apply.assert_called_once()
        self.assertTrue(any("Restarting" in str(call.args[0]) for call in notify.call_args_list))

    def test_menu_reinstall_app_force_replaces(self):
        applied = {"ok": True, "updated": True, "reinstalled": True}
        with (
            patch.object(desktop, "studio_is_up", return_value=True),
            patch.object(desktop, "confirm_update_dialog", return_value=True) as confirm,
            patch.object(desktop, "_http_reinstall_app", return_value=applied) as reinstall,
            patch.object(desktop, "notify") as notify,
            patch.object(desktop.threading.Thread, "start", lambda self: self.run()),
        ):
            desktop.menu_reinstall_app()
        confirm.assert_called_once()
        self.assertEqual(confirm.call_args.kwargs.get("confirm_label"), "Reinstall")
        reinstall.assert_called_once()
        self.assertTrue(any("Restarting" in str(call.args[0]) for call in notify.call_args_list))

    def test_install_bundle_icon_copies_chrome_extension_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            resources = Path(tmp) / "Resources"
            name = desktop.install_bundle_icon(resources)
            copied = resources / "AppIcon.png"
            source = desktop.extension_app_icon_path()
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.read_bytes(), source.read_bytes())
            if (resources / "AppIcon.icns").is_file():
                self.assertEqual(name, "AppIcon")
            else:
                self.assertEqual(name, "AppIcon.png")

    def test_titlebar_matches_t3_code(self):
        self.assertEqual(desktop.TITLEBAR_HEIGHT_PX, 52)

    def test_stamp_modern_chrome_skips_when_already_modern(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "python"
            binary.write_bytes(b"\x00")
            with (
                patch.object(desktop.sys, "platform", "darwin"),
                patch.object(desktop, "macos_major", return_value=26),
                patch.object(desktop, "_linked_sdk_major", return_value=26),
            ):
                self.assertIsNone(desktop.stamp_modern_chrome_binary(binary))

    def test_stamp_modern_chrome_skips_off_macos(self):
        with patch.object(desktop.sys, "platform", "linux"):
            self.assertIsNone(desktop.stamp_modern_chrome_binary(Path("/usr/bin/python")))

    def test_create_studio_window_applies_chrome_before_show(self):
        class Event:
            def __init__(self) -> None:
                self.handlers: list = []

            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self

        events = SimpleNamespace(
            before_show=Event(),
            shown=Event(),
            maximized=Event(),
            restored=Event(),
            resized=Event(),
        )
        window = SimpleNamespace(events=events)
        webview = SimpleNamespace(create_window=MagicMock(return_value=window))

        created = desktop.create_studio_window(webview)

        self.assertIs(created, window)
        webview.create_window.assert_called_once()
        _, kwargs = webview.create_window.call_args
        self.assertTrue(kwargs["frameless"])
        self.assertNotIn("icon", kwargs)
        self.assertEqual(kwargs["background_color"], desktop.WINDOW_BACKGROUND)
        self.assertEqual(events.before_show.handlers, [desktop.apply_unified_macos_chrome])
        self.assertEqual(events.shown.handlers, [desktop.apply_unified_macos_chrome])
        # macOS Spaces fullscreen arrives as maximized; restore on exit.
        self.assertEqual(events.maximized.handlers, [desktop.apply_unified_macos_chrome])
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
        container.frame.return_value.size.height = 52.0
        close.superview.return_value = container
        toolbar = MagicMock()
        native = MagicMock()
        native.styleMask.return_value = 0
        native.collectionBehavior.return_value = 0
        native.toolbar.return_value = None
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
            NSWindowStyleMaskTitled=1 << 0,
            NSWindowStyleMaskClosable=1 << 1,
            NSWindowStyleMaskMiniaturizable=1 << 2,
            NSWindowStyleMaskResizable=1 << 3,
            NSWindowStyleMaskFullSizeContentView=1 << 15,
            NSFullScreenWindowMask=1 << 14,
            NSWindowCollectionBehaviorFullScreenNone=1 << 9,
            NSWindowCollectionBehaviorFullScreenPrimary=1 << 7,
            NSAppearanceNameDarkAqua="dark",
            NSWindowToolbarStyleUnified=1,
            NSToolbar=SimpleNamespace(
                alloc=lambda: SimpleNamespace(initWithIdentifier_=lambda identifier: toolbar)
            ),
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
        native.setCollectionBehavior_.assert_called_once_with(1 << 7)
        close.setHidden_.assert_called_once_with(False)
        miniaturize.setHidden_.assert_called_once_with(False)
        zoom.setHidden_.assert_called_once_with(False)
        close.setEnabled_.assert_called_once_with(True)
        miniaturize.setEnabled_.assert_called_once_with(True)
        zoom.setEnabled_.assert_called_once_with(True)
        # AppKit owns the buttons' size and position: the empty unified toolbar
        # is what insets them into T3 Code's 52pt band.
        close.setControlSize_.assert_not_called()
        close.setFrame_.assert_not_called()
        miniaturize.setFrame_.assert_not_called()
        zoom.setFrame_.assert_not_called()
        native.setToolbar_.assert_called_once_with(toolbar)
        toolbar.setShowsBaselineSeparator_.assert_called_once_with(False)
        native.setToolbarStyle_.assert_called_once_with(1)
        # Close, minimize, and zoom only respond when the mask carries their bits.
        native.setStyleMask_.assert_called_once_with(
            (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 15)
        )
        titlebar.setBackgroundColor_.assert_called_once_with("clear")

    def test_apply_chrome_keeps_titlebar_clear_in_fullscreen(self):
        """Fullscreen must not leave AppKit's opaque titlebar covering the HTML chrome."""
        close = MagicMock()
        miniaturize = MagicMock()
        zoom = MagicMock()
        titlebar = MagicMock()
        native = MagicMock()
        native.styleMask.return_value = 1 << 14
        native.toolbar.return_value = object()
        native.contentView.return_value.superview.return_value.subviews.return_value = [titlebar]
        native.standardWindowButton_.side_effect = lambda button: {
            0: close,
            1: miniaturize,
            2: zoom,
        }[button]
        appkit = SimpleNamespace(
            NSWindowTitleHidden=1,
            NSFullScreenWindowMask=1 << 14,
            NSWindowCollectionBehaviorFullScreenNone=1 << 9,
            NSWindowCollectionBehaviorFullScreenPrimary=1 << 7,
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

        # Do not flip collection behavior or style bits mid-fullscreen.
        native.setCollectionBehavior_.assert_not_called()
        native.setStyleMask_.assert_not_called()
        native.setToolbar_.assert_not_called()
        # Do re-clear the titlebar so the HTML topbar is visible again.
        native.setTitlebarAppearsTransparent_.assert_called_once_with(True)
        native.setTitleVisibility_.assert_called_once_with(1)
        titlebar.setBackgroundColor_.assert_called_once_with("clear")
        close.setHidden_.assert_called_once_with(False)
        close.setEnabled_.assert_called_once_with(True)
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
