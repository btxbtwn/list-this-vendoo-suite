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
    _responses_thinking,
    clamp_reasoning_effort,
    resolved_chatgpt_models,
    resolved_chatgpt_reasoning,
    visible_model_slugs,
    web_search_answer,
    web_search_sources,
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

    def test_responses_thinking_delta(self):
        self.assertEqual(
            _responses_thinking({"type": "response.reasoning_summary_text.delta", "delta": "checking the photos"}),
            "checking the photos",
        )
        self.assertEqual(
            _responses_thinking({"type": "response.output_text.delta", "delta": "hello"}),
            "",
        )

    def test_messages_to_input_splits_system(self):
        instructions, items = _messages_to_input([
            {"role": "system", "content": "Be careful."},
            {"role": "user", "content": [{"type": "text", "text": "Look"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,xx"}}]},
        ])
        self.assertEqual(instructions, "Be careful.")
        self.assertEqual(items[0]["role"], "user")
        self.assertEqual(items[0]["content"][0]["type"], "input_text")
        self.assertEqual(items[0]["content"][1]["type"], "input_image")

    def test_messages_to_input_uses_output_text_for_assistant(self):
        instructions, items = _messages_to_input([
            {"role": "system", "content": "Be careful."},
            {"role": "user", "content": "Fill empty fields."},
            {"role": "assistant", "content": '{"title":"Nike tee"}'},
            {"role": "user", "content": "SKU next"},
        ])
        self.assertEqual(instructions, "Be careful.")
        self.assertEqual([item["role"] for item in items], ["user", "assistant", "user"])
        self.assertEqual(items[0]["content"][0]["type"], "input_text")
        self.assertEqual(items[1]["content"][0]["type"], "output_text")
        self.assertEqual(items[1]["content"][0]["text"], '{"title":"Nike tee"}')
        self.assertEqual(items[2]["content"][0]["type"], "input_text")

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

    def test_search_payload_includes_web_search_tool(self):
        with patch(
            "vendoo_studio.providers.chatgpt_codex.get_chatgpt_models",
            return_value={"listing_model": "gpt-5.5", "reasoning_effort": "medium"},
        ):
            provider = ChatGPTCodexProvider()
        payload = provider._payload(
            [{"role": "user", "content": "Levi's shorts sold comps"}],
            "gpt-5.5",
            True,
            tools=[{"type": "web_search", "external_web_access": True}],
            tool_choice="required",
            include=["web_search_call.action.sources"],
            reasoning_effort="low",
        )
        self.assertEqual(payload["tools"], [{"type": "web_search", "external_web_access": True}])
        self.assertEqual(payload["tool_choice"], "required")
        self.assertEqual(payload["include"], ["web_search_call.action.sources"])
        self.assertEqual(payload["reasoning"]["effort"], "low")


class WebSearchExtractTest(unittest.TestCase):
    def test_reads_answer_citations_and_sources(self):
        output = [
            {
                "type": "web_search_call",
                "action": {
                    "sources": [{"title": "eBay sold", "url": "https://www.ebay.com/itm/1"}],
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Sold recently for $22.",
                        "annotations": [
                            {"type": "url_citation", "url": "https://www.ebay.com/itm/2", "title": "Another sold listing"},
                        ],
                    }
                ],
            },
        ]
        self.assertEqual(web_search_answer(output), "Sold recently for $22.")
        sources = web_search_sources(output)
        self.assertEqual(
            [item["url"] for item in sources],
            ["https://www.ebay.com/itm/1", "https://www.ebay.com/itm/2"],
        )


class WebSearchRequestTest(unittest.IsolatedAsyncioTestCase):
    async def test_comp_search_requests_high_context_and_strict_evidence(self):
        with patch(
            "vendoo_studio.providers.chatgpt_codex.get_chatgpt_models",
            return_value={"listing_model": "gpt-5.5"},
        ):
            provider = ChatGPTCodexProvider()
        provider._web_search_once = AsyncMock(return_value={"answer": "{}", "sources": []})

        await provider.web_search("Patagonia Nano Puff jacket M blue sold comps")

        messages = provider._web_search_once.await_args.args[0]
        tools = provider._web_search_once.await_args.kwargs["tools"]
        self.assertEqual(tools[0]["search_context_size"], "high")
        instructions = messages[0]["content"]
        self.assertIn("Require explicit evidence that the item sold", instructions)
        self.assertIn("exact listing URL you observed", instructions)


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
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("chatgpt", "mimo"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value="sk-test"),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={}),
        ):
            provider = listing_provider.get_listing_provider()
        self.assertIsInstance(provider, ChatGPTCodexProvider)

    def test_uses_mimo_when_primary(self):
        from vendoo_studio.providers.xiaomi_mimo import MiMoProvider
        from vendoo_studio.services import listing_provider

        with (
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("mimo", "chatgpt"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value="sk-test"),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={}),
        ):
            provider = listing_provider.get_listing_provider()
        self.assertIsInstance(provider, MiMoProvider)

    def test_falls_back_to_chatgpt_when_mimo_primary_but_missing_key(self):
        from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider
        from vendoo_studio.services import listing_provider

        with (
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("mimo", "chatgpt"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value=None),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={}),
        ):
            provider = listing_provider.get_listing_provider()
        self.assertIsInstance(provider, ChatGPTCodexProvider)

    def test_no_fallback_when_fallback_is_none(self):
        from vendoo_studio.services import listing_provider

        with (
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("mimo", "none"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value=None),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={}),
        ):
            self.assertIsNone(listing_provider.get_listing_provider())

    def test_falls_back_to_mimo_key(self):
        from vendoo_studio.providers.xiaomi_mimo import MiMoProvider
        from vendoo_studio.services import listing_provider

        with (
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("chatgpt", "mimo"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=False),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value="sk-test"),
        ):
            provider = listing_provider.get_listing_provider()
        self.assertIsInstance(provider, MiMoProvider)

    def test_unconfigured_without_chatgpt_or_key(self):
        from vendoo_studio.services import listing_provider

        with (
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("chatgpt", "mimo"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=False),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value=None),
            patch("vendoo_studio.services.listing_provider.get_cursor_api_key", return_value=None),
        ):
            self.assertIsNone(listing_provider.get_listing_provider())
            self.assertFalse(listing_provider.provider_is_configured())


class SettingsChatGPTRouteTest(unittest.TestCase):
    def test_provider_keeps_masked_mimo_key_while_chatgpt_is_signed_in(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

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
            patch(
                "vendoo_studio.services.user_settings.get_listing_provider_order",
                return_value=("chatgpt", "mimo"),
            ),
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("chatgpt", "mimo"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={}),
        ):
            resp = TestClient(app).get("/api/settings/provider")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["provider"], "chatgpt")
        self.assertEqual(body["primary"], "chatgpt")
        self.assertEqual(body["fallback"], "mimo")
        self.assertTrue(body["configured"])
        self.assertEqual(body["listing_model"], "gpt-5.5")
        self.assertEqual(body["chatgpt"]["email"], "seller@example.com")
        self.assertEqual(body["chatgpt"]["plan"], "plus")
        self.assertEqual(body["masked_key"], "sk-mimo-...1234")

    def test_provider_uses_mimo_when_primary(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

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
            patch(
                "vendoo_studio.services.user_settings.get_listing_provider_order",
                return_value=("mimo", "chatgpt"),
            ),
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("mimo", "chatgpt"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value="sk-mimo-key-1234"),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={}),
        ):
            resp = TestClient(app).get("/api/settings/provider")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["provider"], "xiaomi-mimo")
        self.assertEqual(body["primary"], "mimo")
        self.assertEqual(body["fallback"], "chatgpt")
        self.assertEqual(body["listing_model"], "mimo-v2.5-pro")
        self.assertTrue(body["chatgpt"]["signed_in"])

    def test_provider_hides_mimo_key_when_missing(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

        with (
            patch("vendoo_studio.services.chatgpt_oauth.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.keychain.get_chatgpt_tokens", return_value={"access_token": "a", "refresh_token": "r"}),
            patch("vendoo_studio.services.keychain.get_api_key", return_value=None),
            patch(
                "vendoo_studio.services.user_settings.get_listing_provider_order",
                return_value=("chatgpt", "mimo"),
            ),
            patch(
                "vendoo_studio.services.listing_provider.get_listing_provider_order",
                return_value=("chatgpt", "mimo"),
            ),
            patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True),
            patch("vendoo_studio.services.listing_provider.get_api_key", return_value=None),
            patch("vendoo_studio.providers.chatgpt_codex.get_chatgpt_models", return_value={}),
        ):
            resp = TestClient(app).get("/api/settings/provider")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["masked_key"])

    def test_login_returns_device_code(self):
        from fastapi.testclient import TestClient

        from vendoo_studio.main import app

        pending = {
            "verification_url": "https://auth.openai.com/codex/device",
            "user_code": "ABCD-1234",
        }
        with patch(
            "vendoo_studio.services.chatgpt_oauth.start_login",
            new=AsyncMock(return_value=pending),
        ):
            resp = TestClient(app).post("/api/settings/chatgpt/login")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), pending)


if __name__ == "__main__":
    unittest.main()
