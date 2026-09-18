from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import patch

from vendoo_studio.services import keychain


class FakeKeyring:
    def __init__(self, items: dict[str, str] | None = None, denied: set[str] | None = None):
        self.items = dict(items or {})
        self.denied = set(denied or ())
        self.reads: list[str] = []
        self.writes: list[str] = []

    def get_password(self, service: str, account: str):
        assert service == keychain.KEYRING_SERVICE
        self.reads.append(account)
        if account in self.denied:
            raise RuntimeError("user denied")
        return self.items.get(account)

    def set_password(self, service: str, account: str, value: str):
        assert service == keychain.KEYRING_SERVICE
        self.writes.append(account)
        self.items[account] = value

    def store(self) -> dict:
        return json.loads(self.items[keychain.SECRETS_ACCOUNT])


class KeychainTest(unittest.TestCase):
    def setUp(self):
        keychain._store = None
        keychain._store_readable = False
        keychain._warmed = False

    def use(self, fake: FakeKeyring):
        module = types.ModuleType("keyring")
        module.get_password = fake.get_password
        module.set_password = fake.set_password
        patcher = patch.dict(sys.modules, {"keyring": module})
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_migrates_legacy_items_into_one_item(self):
        tokens = {"access_token": "a", "refresh_token": "r"}
        fake = self.use(FakeKeyring({
            keychain.KEYRING_ACCOUNT: "sk-mimo",
            keychain.BRAVE_ACCOUNT: "BSA-test",
            keychain.CHATGPT_ACCOUNT: json.dumps(tokens),
            keychain.CHATGPT_MODELS_ACCOUNT: json.dumps({"listing_model": "gpt-5"}),
        }))

        found = keychain.warm_keychain()

        self.assertEqual(found, {"api_key": True, "brave": True, "chatgpt": True, "chatgpt_models": True})
        self.assertEqual(keychain.get_api_key(), "sk-mimo")
        self.assertEqual(keychain.get_brave_api_key(), "BSA-test")
        self.assertEqual(keychain.get_chatgpt_tokens(), tokens)
        self.assertEqual(keychain.get_chatgpt_models()["listing_model"], "gpt-5")
        self.assertEqual(set(fake.writes), {keychain.SECRETS_ACCOUNT})
        self.assertEqual(fake.store()[keychain.BRAVE_ACCOUNT], "BSA-test")

    def test_a_partial_item_does_not_shadow_the_legacy_ones(self):
        """A consolidated item written while the Keychain was unreadable carries
        only what was set at that moment. The secrets still in the legacy items
        must survive it, or a key the seller set looks deleted."""
        fake = self.use(FakeKeyring({
            keychain.SECRETS_ACCOUNT: json.dumps({
                keychain.CHATGPT_MODELS_ACCOUNT: json.dumps({"listing_model": "gpt-5"}),
            }),
            keychain.KEYRING_ACCOUNT: "sk-mimo",
            keychain.BRAVE_ACCOUNT: "BSA-test",
        }))

        self.assertEqual(keychain.get_api_key(), "sk-mimo")
        self.assertEqual(keychain.get_brave_api_key(), "BSA-test")
        # what the partial item did carry is kept, not clobbered
        self.assertEqual(keychain.get_chatgpt_models()["listing_model"], "gpt-5")
        # and the repair is written back, so the next read needs no legacy item
        self.assertEqual(fake.store()[keychain.KEYRING_ACCOUNT], "sk-mimo")

    def test_a_complete_item_reads_no_legacy_item(self):
        """Once every secret is consolidated, nothing re-reads the old items."""
        fake = self.use(FakeKeyring({
            keychain.SECRETS_ACCOUNT: json.dumps({
                keychain.KEYRING_ACCOUNT: "sk-mimo",
                keychain.BRAVE_ACCOUNT: "BSA-test",
                keychain.CHATGPT_ACCOUNT: json.dumps({"access_token": "a"}),
                keychain.CHATGPT_MODELS_ACCOUNT: json.dumps({"listing_model": "gpt-5"}),
                keychain.MIGRATION_MARKER: "1",
            }),
        }))

        self.assertEqual(keychain.get_api_key(), "sk-mimo")
        self.assertEqual(fake.reads, [keychain.SECRETS_ACCOUNT])
        self.assertEqual(fake.writes, [])

    def test_launch_touches_only_the_secrets_item(self):
        fake = self.use(FakeKeyring({
            keychain.SECRETS_ACCOUNT: json.dumps({
                keychain.KEYRING_ACCOUNT: "sk-new",
                keychain.MIGRATION_MARKER: "1",
            }),
            keychain.KEYRING_ACCOUNT: "sk-old",
        }))

        keychain.warm_keychain()
        keychain.warm_keychain()
        keychain.get_api_key()

        self.assertEqual(keychain.get_api_key(), "sk-new")
        self.assertEqual(fake.reads, [keychain.SECRETS_ACCOUNT])
        # warm_keychain re-saves once to rebind the item to this binary.
        self.assertEqual(fake.writes, [keychain.SECRETS_ACCOUNT])

    def test_set_and_delete_update_the_one_item(self):
        fake = self.use(FakeKeyring())

        keychain.set_api_key("sk-mimo")
        keychain.set_chatgpt_models(reasoning_effort="High")
        keychain.delete_api_key()

        self.assertEqual(fake.store(), {
            keychain.CHATGPT_MODELS_ACCOUNT: json.dumps({"reasoning_effort": "high"}),
            # an empty Keychain has nothing to sweep, but it is still swept once
            keychain.MIGRATION_MARKER: "1",
        })
        self.assertIsNone(keychain.get_api_key())

    def test_denied_read_never_overwrites_the_item(self):
        stored = json.dumps({keychain.BRAVE_ACCOUNT: "BSA-kept"})
        fake = self.use(FakeKeyring({keychain.SECRETS_ACCOUNT: stored}, denied={keychain.SECRETS_ACCOUNT}))

        keychain.warm_keychain()
        keychain.set_api_key("sk-mimo")

        self.assertEqual(fake.items[keychain.SECRETS_ACCOUNT], stored)
        self.assertEqual(keychain.get_api_key(), "sk-mimo")
        self.assertNotIn(keychain.KEYRING_ACCOUNT, fake.reads)

        fake.denied.clear()
        keychain.set_brave_api_key("BSA-new")
        self.assertEqual(fake.store(), {keychain.KEYRING_ACCOUNT: "sk-mimo", keychain.BRAVE_ACCOUNT: "BSA-new"})


if __name__ == "__main__":
    unittest.main()
