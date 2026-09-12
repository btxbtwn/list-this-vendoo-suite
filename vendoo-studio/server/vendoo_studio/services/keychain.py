from __future__ import annotations

import json
import threading

KEYRING_SERVICE = "vendoo-studio"
KEYRING_ACCOUNT = "xiaomi-mimo-api-key"
CHATGPT_ACCOUNT = "chatgpt-codex-oauth"

_lock = threading.Lock()
_loaded = False
_cached_key: str | None = None
_chatgpt_loaded = False
_cached_chatgpt: dict | None = None


def get_api_key() -> str | None:
    global _loaded, _cached_key
    with _lock:
        if _loaded:
            return _cached_key
        try:
            import keyring
            _cached_key = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        except Exception:
            _cached_key = None
        _loaded = True
        return _cached_key


def set_api_key(key: str):
    global _loaded, _cached_key
    import keyring
    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
    with _lock:
        _cached_key = key
        _loaded = True


def delete_api_key():
    global _loaded, _cached_key
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        pass
    with _lock:
        _cached_key = None
        _loaded = True


def get_chatgpt_tokens() -> dict | None:
    global _chatgpt_loaded, _cached_chatgpt
    with _lock:
        if _chatgpt_loaded:
            return dict(_cached_chatgpt) if _cached_chatgpt else None
        try:
            import keyring
            raw = keyring.get_password(KEYRING_SERVICE, CHATGPT_ACCOUNT)
            _cached_chatgpt = json.loads(raw) if raw else None
            if not isinstance(_cached_chatgpt, dict):
                _cached_chatgpt = None
        except Exception:
            _cached_chatgpt = None
        _chatgpt_loaded = True
        return dict(_cached_chatgpt) if _cached_chatgpt else None


def set_chatgpt_tokens(tokens: dict):
    global _chatgpt_loaded, _cached_chatgpt
    import keyring
    payload = json.dumps(tokens)
    keyring.set_password(KEYRING_SERVICE, CHATGPT_ACCOUNT, payload)
    with _lock:
        _cached_chatgpt = dict(tokens)
        _chatgpt_loaded = True


def delete_chatgpt_tokens():
    global _chatgpt_loaded, _cached_chatgpt
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, CHATGPT_ACCOUNT)
    except Exception:
        pass
    with _lock:
        _cached_chatgpt = None
        _chatgpt_loaded = True
