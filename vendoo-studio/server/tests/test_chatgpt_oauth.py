from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

from vendoo_studio.providers.chatgpt_codex import _messages_to_input, _responses_text
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


class ListingProviderPrefersChatGPTTest(unittest.TestCase):
    def test_prefers_chatgpt_when_signed_in(self):
        from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider
        from vendoo_studio.services import listing_provider

        with patch("vendoo_studio.services.listing_provider.chatgpt_signed_in", return_value=True):
            provider = listing_provider.get_listing_provider()
        self.assertIsInstance(provider, ChatGPTCodexProvider)


if __name__ == "__main__":
    unittest.main()
