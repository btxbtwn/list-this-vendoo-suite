from __future__ import annotations

import json
import logging
import threading

log = logging.getLogger("vendoo_studio.keychain")

KEYRING_SERVICE = "vendoo-studio"
# Every Studio secret lives in this one Keychain item. When a build's code
# signature changes (ad-hoc builds, or a new signing certificate), every item
# it touches asks for the login password again. One item means one prompt.
SECRETS_ACCOUNT = "studio-secrets"
# Pre-consolidation items. Read once to migrate, never written or deleted so
# the migration itself doesn't add prompts.
KEYRING_ACCOUNT = "xiaomi-mimo-api-key"
BRAVE_ACCOUNT = "brave-search-api-key"
CURSOR_ACCOUNT = "cursor-api-key"
CHATGPT_ACCOUNT = "chatgpt-codex-oauth"
CHATGPT_MODELS_ACCOUNT = "chatgpt-models"
LEGACY_ACCOUNTS = (KEYRING_ACCOUNT, BRAVE_ACCOUNT, CHATGPT_ACCOUNT, CHATGPT_MODELS_ACCOUNT)
# Set once the legacy sweep has run. Without it a consolidated item written
# while the Keychain was unreadable — carrying only what was set at that
# moment — would hide the secrets still in the old items for good. With it the
# sweep happens once, so steady-state launches still read a single item.
MIGRATION_MARKER = "legacy-migrated"

_lock = threading.RLock()
_store: dict[str, str] | None = None
_store_readable = False
_warmed = False


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) > 12:
        return value[:8] + "..." + value[-4:]
    return "***"


def _keyring():
    """The keyring module, with a backend chosen rather than discovered.

    Packaged, this app has no usable backend: keyring finds one by reading
    entry points from installed distributions, and a frozen bundle does not
    expose them — the packaging step even strips *.dist-info, because codesign
    treats those directories as bundles. keyring then falls back to its "fail"
    backend and every secret reads as absent, which looks exactly like the
    seller never entered one. Name the macOS backend instead; there is only
    ever one right answer here.
    """
    import keyring

    try:
        from keyring.backends import fail, macOS

        if isinstance(keyring.get_keyring(), fail.Keyring):
            keyring.set_keyring(macOS.Keyring())
    except Exception:  # noqa: BLE001 - a keyring we cannot inspect is used as-is
        pass
    return keyring


def _read_password(account: str) -> str | None:
    try:
        return _keyring().get_password(KEYRING_SERVICE, account)
    except Exception:
        log.warning("keychain read failed for %s", account, exc_info=True)
        return None


def _write_password(account: str, value: str) -> bool:
    try:
        _keyring().set_password(KEYRING_SERVICE, account, value)
        return True
    except Exception:
        log.warning("keychain write failed for %s", account, exc_info=True)
        return False


class _Unavailable(Exception):
    """Keychain refused or failed the read (e.g. Deny), as opposed to not found."""


def _read_item(account: str) -> str | None:
    try:
        return _keyring().get_password(KEYRING_SERVICE, account)
    except Exception as exc:
        log.warning("keychain read failed for %s", account, exc_info=True)
        raise _Unavailable(account) from exc


def _parse_store(raw: str) -> dict[str, str]:
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    if not isinstance(parsed, dict):
        log.warning("keychain secrets item is not a JSON object; starting empty")
        return {}
    return {k: v for k, v in parsed.items() if isinstance(k, str) and isinstance(v, str)}


def _secrets() -> dict[str, str]:
    """Load the secrets item once, migrating the old per-secret items if needed."""
    global _store, _store_readable
    with _lock:
        if _store is not None:
            return _store
        try:
            raw = _read_item(SECRETS_ACCOUNT)
        except _Unavailable:
            # Never overwrite an item we couldn't read; retry on the next write.
            _store, _store_readable = {}, False
            return _store
        _store_readable = True
        _store = _parse_store(raw) if raw is not None else {}
        if _store.get(MIGRATION_MARKER) != "1":
            for account in LEGACY_ACCOUNTS:
                if account in _store:
                    continue
                value = _read_password(account)
                if value:
                    _store[account] = value
            _store[MIGRATION_MARKER] = "1"
            _save_store()
        return _store


def _save_store() -> bool:
    global _store, _store_readable
    with _lock:
        if not _store_readable:
            try:
                raw = _read_item(SECRETS_ACCOUNT)
            except _Unavailable:
                return False
            _store = {**(_parse_store(raw) if raw else {}), **(_store or {})}
            _store_readable = True
        return _write_password(SECRETS_ACCOUNT, json.dumps(_store or {}))


def _get(account: str) -> str | None:
    with _lock:
        return _secrets().get(account)


def _set(account: str, value: str) -> None:
    with _lock:
        _secrets()[account] = value
        _save_store()


def _delete(account: str) -> None:
    with _lock:
        if _secrets().pop(account, None) is not None:
            _save_store()


def get_api_key() -> str | None:
    return _get(KEYRING_ACCOUNT)


def set_api_key(key: str):
    _set(KEYRING_ACCOUNT, key)


def delete_api_key():
    _delete(KEYRING_ACCOUNT)


def get_brave_api_key() -> str | None:
    return _get(BRAVE_ACCOUNT)


def set_brave_api_key(key: str):
    _set(BRAVE_ACCOUNT, key)


def delete_brave_api_key():
    _delete(BRAVE_ACCOUNT)


def get_cursor_api_key() -> str | None:
    return _get(CURSOR_ACCOUNT)


def set_cursor_api_key(key: str):
    _set(CURSOR_ACCOUNT, key)


def delete_cursor_api_key():
    _delete(CURSOR_ACCOUNT)


def get_chatgpt_tokens() -> dict | None:
    raw = _get(CHATGPT_ACCOUNT)
    try:
        tokens = json.loads(raw) if raw else None
    except Exception:
        return None
    return tokens if isinstance(tokens, dict) else None


def set_chatgpt_tokens(tokens: dict):
    # The in-memory store keeps the session even if Keychain UI is denied mid-generate.
    _set(CHATGPT_ACCOUNT, json.dumps(tokens))


def delete_chatgpt_tokens():
    _delete(CHATGPT_ACCOUNT)


REASONING_LADDER = ("none", "low", "medium", "high", "xhigh", "max")
DEFAULT_REASONING_EFFORT = "low"


def _clean_reasoning_effort(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    effort = value.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "off": "none",
        "disabled": "none",
        "minimal": "low",
        "extra-high": "xhigh",
        "extrahigh": "xhigh",
    }
    effort = aliases.get(effort, effort)
    return effort if effort in REASONING_LADDER else None


def _clean_model_slug(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    slug = value.strip()
    return slug or None


def get_chatgpt_models() -> dict[str, str]:
    raw = _get(CHATGPT_MODELS_ACCOUNT)
    try:
        payload = json.loads(raw) if raw else None
    except Exception:
        payload = None
    models: dict[str, str] = {}
    if isinstance(payload, dict):
        vision = _clean_model_slug(payload.get("vision_model"))
        listing = _clean_model_slug(payload.get("listing_model"))
        reasoning = _clean_reasoning_effort(payload.get("reasoning_effort"))
        if vision:
            models["vision_model"] = vision
        if listing:
            models["listing_model"] = listing
        if reasoning:
            models["reasoning_effort"] = reasoning
    return models


def set_chatgpt_models(
    *,
    vision_model: str | None = None,
    listing_model: str | None = None,
    reasoning_effort: str | None = None,
):
    current = get_chatgpt_models()
    vision = _clean_model_slug(vision_model)
    listing = _clean_model_slug(listing_model)
    reasoning = _clean_reasoning_effort(reasoning_effort)
    if vision:
        current["vision_model"] = vision
    if listing:
        current["listing_model"] = listing
    if reasoning:
        current["reasoning_effort"] = reasoning
    _set(CHATGPT_MODELS_ACCOUNT, json.dumps(current))


def warm_keychain() -> dict[str, bool]:
    """Load Studio secrets once at launch and rebind the item to this app.

    Call from the desktop main thread before serving requests so the Keychain
    prompt happens at launch (when someone can click Always Allow), not
    mid-generate from a phone/iPad remote session.
    """
    global _warmed
    with _lock:
        secrets = _secrets()
        if not _warmed and secrets and _store_readable:
            # Re-save so this binary is trusted even if the user clicked Allow
            # instead of Always Allow.
            _save_store()
        _warmed = True

    found = {
        "api_key": bool(get_api_key()),
        "brave": bool(get_brave_api_key()),
        "cursor": bool(get_cursor_api_key()),
        "chatgpt": bool(get_chatgpt_tokens()),
        "chatgpt_models": bool(get_chatgpt_models()),
    }
    log.info(
        "keychain warmed api_key=%s brave=%s cursor=%s chatgpt=%s models=%s",
        found["api_key"],
        found["brave"],
        found["cursor"],
        found["chatgpt"],
        found["chatgpt_models"],
    )
    return found
