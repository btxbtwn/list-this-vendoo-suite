from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from vendoo_studio.providers.xiaomi_mimo import (
    MIMO_BASE_URL,
    MIMO_TOKEN_PLAN_BASE_URL,
    MiMoProvider,
    mimo_base_url_for_key,
    normalize_mimo_api_key,
)


class NormalizeMimoKeyTest(unittest.TestCase):
    def test_strips_quotes_and_bearer(self):
        self.assertEqual(normalize_mimo_api_key('  "sk-abc"  '), "sk-abc")
        self.assertEqual(normalize_mimo_api_key("Bearer sk-abc"), "sk-abc")

    def test_token_plan_uses_plan_host(self):
        self.assertEqual(mimo_base_url_for_key("tp-plan"), MIMO_TOKEN_PLAN_BASE_URL)
        self.assertEqual(mimo_base_url_for_key("sk-paygo"), MIMO_BASE_URL)
        provider = MiMoProvider(api_key="tp-xyz")
        self.assertEqual(provider.base_url, MIMO_TOKEN_PLAN_BASE_URL)


class MiMoConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_connection_success(self):
        provider = MiMoProvider(api_key="sk-good")
        response = MagicMock(status_code=200)

        fake_client = MagicMock()
        fake_client.get = AsyncMock(return_value=response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)

        with patch("vendoo_studio.providers.xiaomi_mimo.httpx.AsyncClient", return_value=fake_client):
            self.assertTrue(await provider.test_connection())
        fake_client.get.assert_awaited_once()
        args, kwargs = fake_client.get.await_args
        self.assertTrue(str(args[0]).endswith("/models"))
        self.assertEqual(kwargs["headers"]["api-key"], "sk-good")

    async def test_connection_surfaces_api_error(self):
        provider = MiMoProvider(api_key="sk-bad")
        response = MagicMock(status_code=401)
        response.text = '{"error":{"message":"Invalid API Key","code":"401"}}'
        response.json = MagicMock(
            return_value={"error": {"message": "Invalid API Key", "code": "401"}}
        )

        fake_client = MagicMock()
        fake_client.get = AsyncMock(return_value=response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)

        with patch("vendoo_studio.providers.xiaomi_mimo.httpx.AsyncClient", return_value=fake_client):
            with self.assertRaises(RuntimeError) as ctx:
                await provider.test_connection()
        self.assertIn("Invalid API Key", str(ctx.exception))

    async def test_connection_surfaces_transport_error(self):
        provider = MiMoProvider(api_key="sk-good")
        fake_client = MagicMock()
        fake_client.get = AsyncMock(side_effect=httpx.ConnectError("dns failed"))
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)

        with patch("vendoo_studio.providers.xiaomi_mimo.httpx.AsyncClient", return_value=fake_client):
            with self.assertRaises(RuntimeError) as ctx:
                await provider.test_connection()
        self.assertIn("MiMo connection failed", str(ctx.exception))


class MiMoSettingsRouteTest(unittest.TestCase):
    def test_mimo_test_returns_api_error(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

        with (
            patch(
                "vendoo_studio.services.keychain.get_api_key",
                return_value="sk-bad",
            ),
            patch(
                "vendoo_studio.providers.xiaomi_mimo.MiMoProvider.test_connection",
                new=AsyncMock(side_effect=RuntimeError("MiMo HTTP 401: Invalid API Key")),
            ),
        ):
            resp = TestClient(app).post("/api/settings/provider/mimo/test")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIn("Invalid API Key", body["error"])

    def test_put_normalizes_key(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

        with patch("vendoo_studio.services.keychain.set_api_key") as set_key:
            resp = TestClient(app).put(
                "/api/settings/provider",
                json={"api_key": '  "sk-trimmed"  '},
            )
        self.assertEqual(resp.status_code, 200)
        set_key.assert_called_once_with("sk-trimmed")


if __name__ == "__main__":
    unittest.main()
