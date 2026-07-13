from __future__ import annotations

KEYRING_SERVICE = "vendoo-studio"
KEYRING_ACCOUNT = "xiaomi-mimo-api-key"


def get_api_key() -> str | None:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        return None


def set_api_key(key: str):
    import keyring
    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)


def delete_api_key():
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        pass
