from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from vendoo_studio.providers.cursor_agent import (
    CursorProvider,
    _flatten_messages,
    uvloop_safe_subprocess_env,
)


class FlattenMessagesTest(unittest.TestCase):
    def test_flattens_roles_and_images(self):
        messages = [
            {"role": "system", "content": "Be careful."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abcd"},
                    },
                ],
            },
        ]
        with patch("vendoo_studio.providers.cursor_agent._image_from_data_url", return_value="img"):
            prompt, images = _flatten_messages(messages)
        self.assertIn("SYSTEM:", prompt)
        self.assertIn("Be careful.", prompt)
        self.assertIn("USER:", prompt)
        self.assertIn("What is this?", prompt)
        self.assertIn("assistant text only", prompt.lower())
        self.assertEqual(images, ["img"])


class UvloopSafeEnvTest(unittest.TestCase):
    def test_coerces_path_and_drops_none(self):
        cleaned = uvloop_safe_subprocess_env(
            {
                "OK": "yes",
                "PATH_VAL": Path("/tmp/cursor"),
                "NONE_VAL": None,
                "INT_VAL": 7,
            }
        )
        self.assertEqual(cleaned["OK"], "yes")
        self.assertEqual(cleaned["PATH_VAL"], "/tmp/cursor")
        self.assertEqual(cleaned["INT_VAL"], "7")
        self.assertNotIn("NONE_VAL", cleaned)
        self.assertTrue(all(isinstance(v, str) for v in cleaned.values()))

    def test_uvloop_accepts_sanitized_env(self):
        import uvloop

        dirty = dict(os.environ)
        dirty["CURSOR_TEST_PATH"] = Path("/tmp/cursor-bridge")
        cleaned = uvloop_safe_subprocess_env(dirty)

        async def _spawn() -> int:
            process = await asyncio.create_subprocess_exec("/bin/true", env=cleaned)
            return await process.wait()

        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        try:
            self.assertEqual(asyncio.run(_spawn()), 0)
        finally:
            asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())


class CursorProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_streams_text(self):
        provider = CursorProvider(api_key="cursor_test")

        class FakeRun:
            def __init__(self):
                self.id = "run-1"

            def iter_text(self):
                yield "Hello"
                yield " world"

            def wait(self):
                return MagicMock(status="finished", result="Hello world", id=self.id)

        fake_agent = MagicMock()
        fake_agent.send = MagicMock(return_value=FakeRun())
        fake_agent.__enter__ = MagicMock(return_value=fake_agent)
        fake_agent.__exit__ = MagicMock(return_value=None)

        fake_agents = MagicMock()
        fake_agents.create = MagicMock(return_value=fake_agent)

        fake_client = MagicMock()
        fake_client.agents = fake_agents
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=None)

        with (
            patch("cursor_sdk.Client.launch_bridge", return_value=fake_client),
            patch("vendoo_studio.providers.cursor_agent.listing_scratch_dir") as scratch,
        ):
            scratch.return_value = MagicMock(__str__=lambda self: "/tmp/cursor-scratch")
            chunks = []
            async for chunk in provider.chat([{"role": "user", "content": "Hi"}], stream=True):
                chunks.append(chunk)

        self.assertEqual("".join(chunks), "Hello world")
        fake_agent.send.assert_called_once()

    async def test_connection_lists_models(self):
        provider = CursorProvider(api_key="cursor_test")

        fake_client = MagicMock()
        fake_client.list_models = MagicMock(return_value=[MagicMock(id="composer-2.5")])
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=None)

        with (
            patch("cursor_sdk.Client.launch_bridge", return_value=fake_client),
            patch("vendoo_studio.providers.cursor_agent.listing_scratch_dir") as scratch,
        ):
            scratch.return_value = MagicMock(__str__=lambda self: "/tmp/cursor-scratch")
            self.assertTrue(await provider.test_connection())
        fake_client.list_models.assert_called_once_with(api_key="cursor_test")

    async def test_connection_auth_failure(self):
        from cursor_sdk import CursorAgentError

        provider = CursorProvider(api_key="bad")

        fake_client = MagicMock()
        fake_client.list_models = MagicMock(side_effect=CursorAgentError("Invalid User API Key"))
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=None)

        with (
            patch("cursor_sdk.Client.launch_bridge", return_value=fake_client),
            patch("vendoo_studio.providers.cursor_agent.listing_scratch_dir") as scratch,
        ):
            scratch.return_value = MagicMock(__str__=lambda self: "/tmp/cursor-scratch")
            with self.assertRaises(RuntimeError) as ctx:
                await provider.test_connection()
        self.assertIn("Invalid User API Key", str(ctx.exception))

    def test_normalize_cursor_api_key(self):
        from vendoo_studio.providers.cursor_agent import normalize_cursor_api_key

        self.assertEqual(normalize_cursor_api_key('  "cursor_abc"  '), "cursor_abc")
        self.assertEqual(normalize_cursor_api_key("Bearer cursor_abc"), "cursor_abc")


class ListingProviderCursorTest(unittest.TestCase):
    def test_uses_cursor_when_primary(self):
        from vendoo_studio.providers.cursor_agent import CursorProvider
        from vendoo_studio.services import listing_provider

        with (
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("cursor", "chatgpt"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value="sk-test"),
            patch(
                "vendoo_studio.services.listing_provider.get_cursor_api_key",
                return_value="cursor_test",
            ),
        ):
            provider = listing_provider.get_listing_provider()
            self.assertIsInstance(provider, CursorProvider)
        from vendoo_studio.providers.cursor_agent import CursorProvider
        from vendoo_studio.services import listing_provider

        with (
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("chatgpt", "cursor"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=False),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value=None),
            patch(
                "vendoo_studio.services.listing_provider.get_cursor_api_key",
                return_value="cursor_test",
            ),
        ):
            provider = listing_provider.get_listing_provider()
            self.assertIsInstance(provider, CursorProvider)
            self.assertTrue(listing_provider.provider_is_configured())


class CursorSettingsRouteTest(unittest.TestCase):
    def test_put_and_get_cursor_key(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

        with (
            patch("vendoo_studio.services.keychain.set_cursor_api_key") as set_key,
            patch(
                "vendoo_studio.services.keychain.get_cursor_api_key",
                return_value="cursor_secret_key",
            ),
        ):
            client = TestClient(app)
            resp = client.put("/api/settings/cursor", json={"api_key": "cursor_secret_key"})
            self.assertEqual(resp.status_code, 200)
            set_key.assert_called_once_with("cursor_secret_key")
            body = resp.json()
            self.assertTrue(body["configured"])
            self.assertTrue(body["masked_key"])

            get_resp = client.get("/api/settings/cursor")
            self.assertEqual(get_resp.status_code, 200)
            self.assertTrue(get_resp.json()["configured"])


class UserSettingsCursorOrderTest(unittest.TestCase):
    def test_accepts_cursor_primary(self):
        import tempfile
        from pathlib import Path

        from vendoo_studio.services import user_settings

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(user_settings, "settings_path", return_value=Path(tmp) / "settings.json"):
                order = user_settings.set_listing_provider_order("cursor", "mimo")
                self.assertEqual(order["primary"], "cursor")
                self.assertEqual(order["fallback"], "mimo")
                primary, fallback = user_settings.get_listing_provider_order()
                self.assertEqual((primary, fallback), ("cursor", "mimo"))


if __name__ == "__main__":
    unittest.main()
