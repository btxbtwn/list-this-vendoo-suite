from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import AsyncMock, patch

from vendoo_studio.providers.chatgpt_codex import (
    MODELS_CLIENT_VERSION,
    USER_AGENT,
    ChatGPTCodexProvider,
    _messages_to_input,
    _responses_text,
    clamp_reasoning_effort,
    resolved_chatgpt_models,
    resolved_chatgpt_reasoning,
    visible_model_slugs,
)
from vendoo_studio.services.chatgpt_oauth import jwt_auth_claims, profile_from_tokens


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

    def test_visible_model_slugs_skip_hidden(self):
        slugs = visible_model_slugs({
            "models": [
                {"slug": "gpt-6-astra", "visibility": "list", "priority": 1},
                {"slug": "gpt-reserve", "visibility": "hide", "priority": 3},
                {"slug": "gpt-5.5", "visibility": "list", "priority": 12},
            ]
        })
        self.assertEqual(slugs, ["gpt-6-astra", "gpt-5.5"])


class ChatGPTModelChoiceTest(unittest.TestCase):
    def test_resolved_models_use_saved_prefs(self):
        with patch(
            "vendoo_studio.providers.chatgpt_codex.get_chatgpt_models",
            return_value={"vision_model": "gpt-5.6-sol", "listing_model": "gpt-6-astra", "reasoning_effort": "high"},
        ):
            self.assertEqual(resolved_chatgpt_models(), ("gpt-5.6-sol", "gpt-6-astra"))
            self.assertEqual(resolved_chatgpt_reasoning(), "high")
            provider = ChatGPTCodexProvider()
        self.assertEqual(provider.vision_model, "gpt-5.6-sol")
        self.assertEqual(provider.listing_model, "gpt-6-astra")
        self.assertEqual(provider.reasoning_effort, "high")
        self.assertEqual(provider._payload([{"role": "user", "content": "hi"}], "gpt-5.5", True)["reasoning"]["effort"], "high")
        self.assertEqual(clamp_reasoning_effort("none", "gpt-6-astra"), "low")
        self.assertEqual(clamp_reasoning_effort("max", "gpt-5.5"), "xhigh")


class ChatGPTCatalogFetchTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_sends_client_version(self):
        captured: dict = {}

        class _Resp:
            status_code = 200
            text = '{"models":[]}'

            def json(self):
                return {
                    "models": [
                        {"slug": "gpt-5.6-sol", "visibility": "list", "priority": 4},
                        {"slug": "codex-auto-review", "visibility": "hide", "priority": 43},
                    ]
                }

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url, params=None, headers=None):
                captured["url"] = url
                captured["params"] = params
                captured["headers"] = headers
                return _Resp()

        tokens = {
            "access_token": _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"}}),
            "refresh_token": "r",
        }
        from vendoo_studio.providers import chatgpt_codex

        with (
            patch("vendoo_studio.providers.chatgpt_codex.refresh_chatgpt_tokens", new=AsyncMock(return_value=tokens)),
            patch("vendoo_studio.providers.chatgpt_codex.httpx.AsyncClient", _Client),
        ):
            slugs = await chatgpt_codex.fetch_codex_models(force=True)
        self.assertEqual(slugs, ["gpt-5.6-sol"])
        self.assertTrue(str(captured["url"]).endswith("/models"))
        self.assertEqual(captured["params"], {"client_version": MODELS_CLIENT_VERSION})
        self.assertEqual(captured["headers"]["User-Agent"], USER_AGENT)
        self.assertEqual(captured["headers"]["ChatGPT-Account-ID"], "acct_123")


class ListingProviderPrefersChatGPTTest(unittest.TestCase):
    def test_prefers_chatgpt_when_signed_in(self):
        from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider
        from vendoo_studio.services import listing_provider

        with (
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={}),
        ):
            provider = listing_provider.get_listing_provider()
        self.assertIsInstance(provider, ChatGPTCodexProvider)


if __name__ == "__main__":
    unittest.main()
