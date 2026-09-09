from __future__ import annotations

import threading

KEYRING_SERVICE = "vendoo-studio"
KEYRING_ACCOUNT = "xiaomi-mimo-api-key"

_lock = threading.Lock()
_loaded = False
_cached_key: str | None = None


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
