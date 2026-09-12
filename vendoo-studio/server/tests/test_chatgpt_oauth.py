from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from vendoo_studio.main import app
from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider, _messages_to_input, _responses_text
from vendoo_studio.providers.xiaomi_mimo import MiMoProvider
from vendoo_studio.services.chatgpt_oauth import jwt_auth_claims, profile_from_tokens
from vendoo_studio.services import listing_provider


def _jwt(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"aaa.{raw}.sig"


class ChatGPTOAuthTest(unittest.TestCase):
    def test_profile_from_id_token(self):
        token = _jwt({
            "email": "seller@example.com",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct_123",
                "chatgpt_plan_type": "plus",
            },
        })
        profile = profile_from_tokens({"id_token": token, "access_token": "a", "refresh_token": "r"})
        self.assertEqual(profile["email"], "seller@example.com")
        self.assertEqual(profile["plan"], "plus")
        self.assertEqual(profile["account_id"], "acct_123")
        self.assertEqual(jwt_auth_claims(token)["chatgpt_account_id"], "acct_123")

    def test_responses_text_delta(self):
        self.assertEqual(
            _responses_text({"type": "response.output_text.delta", "delta": "hello"}),
            "hello",
        )

    def test_messages_to_input_splits_system(self):
        instructions, items = _messages_to_input([
            {"role": "system", "content": "Be careful."},
            {"role": "user", "content": [{"type": "text", "text": "Look"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,xx"}}]},
        ])
        self.assertEqual(instructions, "Be careful.")
        self.assertEqual(items[0]["content"][0]["type"], "input_text")
        self.assertEqual(items[0]["content"][1]["type"], "input_image")


class ListingProviderPrefersChatGPTTest(unittest.TestCase):
    def test_prefers_chatgpt_when_signed_in(self):
        with patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True):
            provider = listing_provider.get_listing_provider()
        self.assertIsInstance(provider, ChatGPTCodexProvider)

    def test_falls_back_to_mimo_key(self):
        with (
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=False),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value="sk-test"),
        ):
            provider = listing_provider.get_listing_provider()
        self.assertIsInstance(provider, MiMoProvider)

    def test_unconfigured_without_chatgpt_or_key(self):
        with (
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=False),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value=None),
        ):
            self.assertIsNone(listing_provider.get_listing_provider())
            self.assertFalse(listing_provider.provider_is_configured())


class SettingsChatGPTRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_provider_prefers_chatgpt_profile(self):
        token = _jwt({
            "email": "seller@example.com",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct_123",
                "chatgpt_plan_type": "plus",
            },
        })
        tokens = {"id_token": token, "access_token": "a", "refresh_token": "r"}
        with (
            patch("vendoo_studio.services.chatgpt_oauth.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.keychain.get_chatgpt_tokens", return_value=tokens),
            patch("vendoo_studio.services.keychain.get_api_key", return_value="sk-mimo-key-1234"),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/settings/provider")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["provider"], "chatgpt")
        self.assertTrue(body["configured"])
        self.assertEqual(body["listing_model"], "gpt-5.5")
        self.assertEqual(body["chatgpt"]["email"], "seller@example.com")
        self.assertEqual(body["chatgpt"]["plan"], "plus")
        self.assertEqual(body["masked_key"], "sk-mimo-...1234")

    async def test_login_returns_device_code(self):
        pending = {
            "verification_url": "https://auth.openai.com/codex/device",
            "user_code": "ABCD-EFGH",
        }
        with patch("vendoo_studio.services.chatgpt_oauth.start_login", new=AsyncMock(return_value=pending)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/settings/chatgpt/login")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_code"], "ABCD-EFGH")


if __name__ == "__main__":
    unittest.main()
