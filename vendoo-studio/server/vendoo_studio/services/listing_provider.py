from __future__ import annotations

from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider
from vendoo_studio.providers.xiaomi_mimo import MiMoProvider
from vendoo_studio.services.chatgpt_oauth import chatgpt_signed_in
from vendoo_studio.services.keychain import get_api_key


def get_listing_provider():
    if chatgpt_signed_in():
        return ChatGPTCodexProvider()
    key = get_api_key()
    if key:
        return MiMoProvider(api_key=key)
    return None


def provider_is_configured() -> bool:
    return chatgpt_signed_in() or bool(get_api_key())
