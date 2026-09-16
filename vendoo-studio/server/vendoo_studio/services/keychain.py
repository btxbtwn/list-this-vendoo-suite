from __future__ import annotations

import json
import logging
import threading

log = logging.getLogger("vendoo_studio.keychain")

KEYRING_SERVICE = "vendoo-studio"
KEYRING_ACCOUNT = "xiaomi-mimo-api-key"
BRAVE_ACCOUNT = "brave-search-api-key"
CHATGPT_ACCOUNT = "chatgpt-codex-oauth"
CHATGPT_MODELS_ACCOUNT = "chatgpt-models"

_lock = threading.Lock()
_loaded = False
_cached_key: str | None = None
_brave_loaded = False
_cached_brave_key: str | None = None
_chatgpt_loaded = False
_cached_chatgpt: dict | None = None
_chatgpt_models_loaded = False
_cached_chatgpt_models: dict | None = None
_warmed = False


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) > 12:
        return value[:8] + "..." + value[-4:]
    return "***"


def _read_password(account: str) -> str | None:
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, account)
    except Exception:
        log.warning("keychain read failed for %s", account, exc_info=True)
        return None


def _write_password(account: str, value: str) -> bool:
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, account, value)
        return True
    except Exception:
        log.warning("keychain write failed for %s", account, exc_info=True)
        return False


def _rebind_password(account: str, value: str | None) -> None:
    """Re-save so the current app binary is trusted on this Keychain item.

    Ad-hoc signed Mac updates change the binary identity. Without a rebind,
    macOS prompts again on every launch (Allow) unless the user picked
    Always Allow. Rewriting after a successful unlock attaches this process.
    """
    if not value:
        return
    _write_password(account, value)


def get_api_key() -> str | None:
    global _loaded, _cached_key
    with _lock:
        if _loaded:
            return _cached_key
        _cached_key = _read_password(KEYRING_ACCOUNT)
        _loaded = True
        return _cached_key


def set_api_key(key: str):
    global _loaded, _cached_key
    _write_password(KEYRING_ACCOUNT, key)
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


def get_brave_api_key() -> str | None:
    global _brave_loaded, _cached_brave_key
    with _lock:
        if _brave_loaded:
            return _cached_brave_key
        _cached_brave_key = _read_password(BRAVE_ACCOUNT)
        _brave_loaded = True
        return _cached_brave_key


def set_brave_api_key(key: str):
    global _brave_loaded, _cached_brave_key
    _write_password(BRAVE_ACCOUNT, key)
    with _lock:
        _cached_brave_key = key
        _brave_loaded = True


def delete_brave_api_key():
    global _brave_loaded, _cached_brave_key
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, BRAVE_ACCOUNT)
    except Exception:
        pass
    with _lock:
        _cached_brave_key = None
        _brave_loaded = True


def get_chatgpt_tokens() -> dict | None:
    global _chatgpt_loaded, _cached_chatgpt
    with _lock:
        if _chatgpt_loaded:
            return dict(_cached_chatgpt) if _cached_chatgpt else None
        raw = _read_password(CHATGPT_ACCOUNT)
        try:
            _cached_chatgpt = json.loads(raw) if raw else None
            if not isinstance(_cached_chatgpt, dict):
                _cached_chatgpt = None
        except Exception:
            _cached_chatgpt = None
        _chatgpt_loaded = True
        return dict(_cached_chatgpt) if _cached_chatgpt else None


def set_chatgpt_tokens(tokens: dict):
    global _chatgpt_loaded, _cached_chatgpt
    payload = json.dumps(tokens)
    # Keep the in-memory session even if Keychain UI is denied mid-generate.
    _write_password(CHATGPT_ACCOUNT, payload)
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


REASONING_LADDER = ("none", "low", "medium", "high", "xhigh", "max")
DEFAULT_REASONING_EFFORT = "medium"


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
    global _chatgpt_models_loaded, _cached_chatgpt_models
    with _lock:
        if _chatgpt_models_loaded:
            return dict(_cached_chatgpt_models or {})
        raw = _read_password(CHATGPT_MODELS_ACCOUNT)
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
        _cached_chatgpt_models = models
        _chatgpt_models_loaded = True
        return dict(models)


def set_chatgpt_models(
    *,
    vision_model: str | None = None,
    listing_model: str | None = None,
    reasoning_effort: str | None = None,
):
    global _chatgpt_models_loaded, _cached_chatgpt_models
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
    _write_password(CHATGPT_MODELS_ACCOUNT, json.dumps(current))
    with _lock:
        _cached_chatgpt_models = dict(current)
        _chatgpt_models_loaded = True


def warm_keychain() -> dict[str, bool]:
    """Load every Studio secret once at launch and rebind ACLs for this app.

    Call from the desktop main thread before serving requests so Keychain
    prompts happen at launch (when someone can click Always Allow), not
    mid-generate from a phone/iPad remote session.
    """
    global _warmed, _loaded, _cached_key, _brave_loaded, _cached_brave_key
    global _chatgpt_loaded, _cached_chatgpt, _chatgpt_models_loaded, _cached_chatgpt_models

    with _lock:
        if _warmed:
            return {
                "api_key": bool(_cached_key),
                "brave": bool(_cached_brave_key),
                "chatgpt": bool(_cached_chatgpt),
                "chatgpt_models": bool(_cached_chatgpt_models),
            }

    api_key = _read_password(KEYRING_ACCOUNT)
    _rebind_password(KEYRING_ACCOUNT, api_key)

    brave = _read_password(BRAVE_ACCOUNT)
    _rebind_password(BRAVE_ACCOUNT, brave)

    chatgpt_raw = _read_password(CHATGPT_ACCOUNT)
    _rebind_password(CHATGPT_ACCOUNT, chatgpt_raw)
    chatgpt: dict | None = None
    if chatgpt_raw:
        try:
            parsed = json.loads(chatgpt_raw)
            chatgpt = parsed if isinstance(parsed, dict) else None
        except Exception:
            chatgpt = None

    models_raw = _read_password(CHATGPT_MODELS_ACCOUNT)
    _rebind_password(CHATGPT_MODELS_ACCOUNT, models_raw)
    models: dict[str, str] = {}
    if models_raw:
        try:
            payload = json.loads(models_raw)
        except Exception:
            payload = None
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

    with _lock:
        _cached_key = api_key
        _loaded = True
        _cached_brave_key = brave
        _brave_loaded = True
        _cached_chatgpt = chatgpt
        _chatgpt_loaded = True
        _cached_chatgpt_models = models
        _chatgpt_models_loaded = True
        _warmed = True

    found = {
        "api_key": bool(api_key),
        "brave": bool(brave),
        "chatgpt": bool(chatgpt),
        "chatgpt_models": bool(models),
    }
    log.info(
        "keychain warmed api_key=%s brave=%s chatgpt=%s models=%s",
        found["api_key"],
        found["brave"],
        found["chatgpt"],
        found["chatgpt_models"],
    )
    return found
