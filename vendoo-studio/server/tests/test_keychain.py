from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from vendoo_studio.services import keychain


class WarmKeychainTest(unittest.TestCase):
    def setUp(self):
        keychain._warmed = False
        keychain._loaded = False
        keychain._cached_key = None
        keychain._brave_loaded = False
        keychain._cached_brave_key = None
        keychain._chatgpt_loaded = False
        keychain._cached_chatgpt = None
        keychain._chatgpt_models_loaded = False
        keychain._cached_chatgpt_models = None

    def test_warm_loads_and_rebinds_all_accounts(self):
        tokens = {"access_token": "a", "refresh_token": "r"}
        models = {"listing_model": "gpt-5"}
        values = {
            keychain.KEYRING_ACCOUNT: "sk-mimo",
            keychain.BRAVE_ACCOUNT: "BSA-test",
            keychain.CHATGPT_ACCOUNT: json.dumps(tokens),
            keychain.CHATGPT_MODELS_ACCOUNT: json.dumps(models),
        }
        writes: list[tuple[str, str]] = []

        def read(account: str):
            return values.get(account)

        def write(account: str, value: str) -> bool:
            writes.append((account, value))
            return True

        with (
            patch.object(keychain, "_read_password", side_effect=read),
            patch.object(keychain, "_write_password", side_effect=write),
        ):
            found = keychain.warm_keychain()
            again = keychain.warm_keychain()

        self.assertEqual(found, {"api_key": True, "brave": True, "chatgpt": True, "chatgpt_models": True})
        self.assertEqual(again, found)
        self.assertEqual(keychain.get_api_key(), "sk-mimo")
        self.assertEqual(keychain.get_brave_api_key(), "BSA-test")
        self.assertEqual(keychain.get_chatgpt_tokens(), tokens)
        self.assertEqual(keychain.get_chatgpt_models()["listing_model"], "gpt-5")
        self.assertEqual(
            {account for account, _ in writes},
            {
                keychain.KEYRING_ACCOUNT,
                keychain.BRAVE_ACCOUNT,
                keychain.CHATGPT_ACCOUNT,
                keychain.CHATGPT_MODELS_ACCOUNT,
            },
        )


if __name__ == "__main__":
    unittest.main()
