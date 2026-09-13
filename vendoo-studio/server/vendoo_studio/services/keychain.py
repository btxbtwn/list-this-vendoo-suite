from __future__ import annotations

import json
import threading

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


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) > 12:
        return value[:8] + "..." + value[-4:]
    return "***"


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


def get_brave_api_key() -> str | None:
    global _brave_loaded, _cached_brave_key
    with _lock:
        if _brave_loaded:
            return _cached_brave_key
        try:
            import keyring
            _cached_brave_key = keyring.get_password(KEYRING_SERVICE, BRAVE_ACCOUNT)
        except Exception:
            _cached_brave_key = None
        _brave_loaded = True
        return _cached_brave_key


def set_brave_api_key(key: str):
    global _brave_loaded, _cached_brave_key
    import keyring
    keyring.set_password(KEYRING_SERVICE, BRAVE_ACCOUNT, key)
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
        try:
            import keyring
            raw = keyring.get_password(KEYRING_SERVICE, CHATGPT_MODELS_ACCOUNT)
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
    import keyring
    keyring.set_password(KEYRING_SERVICE, CHATGPT_MODELS_ACCOUNT, json.dumps(current))
    with _lock:
        _cached_chatgpt_models = dict(current)
        _chatgpt_models_loaded = True
