from __future__ import annotations

from vendoo_studio.providers.chatgpt_codex import ChatGPTCodexProvider
from vendoo_studio.providers.cursor_agent import CursorProvider
from vendoo_studio.providers.xiaomi_mimo import MiMoProvider
from vendoo_studio.services.chatgpt_oauth import chatgpt_signed_in
from vendoo_studio.services.keychain import get_api_key, get_cursor_api_key
from vendoo_studio.services.user_settings import (
    AUTO_LISTING_PROVIDER_ORDER,
    get_listing_provider_order,
)


def _mimo_provider():
    key = get_api_key()
    if not key:
        return None
    return MiMoProvider(api_key=key)


def _chatgpt_provider():
    if not chatgpt_signed_in():
        return None
    return ChatGPTCodexProvider()


def _cursor_provider():
    key = get_cursor_api_key()
    if not key:
        return None
    return CursorProvider(api_key=key)


def _provider_for(choice: str):
    if choice == "mimo":
        return _mimo_provider()
    if choice == "chatgpt":
        return _chatgpt_provider()
    if choice == "cursor":
        return _cursor_provider()
    return None


def get_listing_provider():
    """Return the active listing provider.

    Primary \"auto\" tries ChatGPT, then MiMo, then Cursor for the first ready
    provider. Otherwise tries the user's primary choice, then the configured fallback.
    """
    primary, fallback = get_listing_provider_order()
    if primary == "auto":
        for choice in AUTO_LISTING_PROVIDER_ORDER:
            provider = _provider_for(choice)
            if provider is not None:
                return provider
        return None

    provider = _provider_for(primary)
    if provider is not None:
        return provider
    if fallback != "none":
        return _provider_for(fallback)
    return None


def provider_is_configured() -> bool:
    return chatgpt_signed_in() or bool(get_api_key()) or bool(get_cursor_api_key())
