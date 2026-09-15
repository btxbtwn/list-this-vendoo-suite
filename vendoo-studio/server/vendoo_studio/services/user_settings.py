from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal

from vendoo_studio.config import user_data_root

_lock = threading.Lock()
SETUP_GUIDE_DISMISSED_KEY = "setup_guide_dismissed"
LISTING_PROVIDER_KEY = "listing_provider"
LISTING_PROVIDER_CHOICES = frozenset({"chatgpt", "mimo"})
LISTING_FALLBACK_CHOICES = frozenset({"chatgpt", "mimo", "none"})
DEFAULT_LISTING_PROVIDER: Literal["chatgpt", "mimo"] = "chatgpt"
DEFAULT_LISTING_FALLBACK: Literal["chatgpt", "mimo", "none"] = "mimo"

ListingProviderChoice = Literal["chatgpt", "mimo"]
ListingFallbackChoice = Literal["chatgpt", "mimo", "none"]


def settings_path() -> Path:
    return user_data_root() / "settings.json"


def _read_unlocked() -> dict:
    path = settings_path()
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_unlocked(payload: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def read_settings() -> dict:
    with _lock:
        return _read_unlocked()


def write_settings(payload: dict) -> None:
    with _lock:
        _write_unlocked(payload)


def update_settings(mutator) -> dict:
    with _lock:
        payload = _read_unlocked()
        mutator(payload)
        _write_unlocked(payload)
        return payload


def setup_guide_dismissed() -> bool:
    return bool(read_settings().get(SETUP_GUIDE_DISMISSED_KEY))


def dismiss_setup_guide() -> dict:
    def mutator(payload: dict) -> None:
        payload[SETUP_GUIDE_DISMISSED_KEY] = True

    update_settings(mutator)
    return {"ok": True, "dismissed": True}


def normalize_listing_provider(value: object) -> ListingProviderChoice:
    if isinstance(value, str):
        choice = value.strip().lower()
        if choice in LISTING_PROVIDER_CHOICES:
            return choice  # type: ignore[return-value]
    return DEFAULT_LISTING_PROVIDER


def normalize_listing_fallback(value: object, *, primary: ListingProviderChoice) -> ListingFallbackChoice:
    if isinstance(value, str):
        choice = value.strip().lower()
        if choice == "none":
            return "none"
        if choice in LISTING_PROVIDER_CHOICES and choice != primary:
            return choice  # type: ignore[return-value]
    return _other_provider(primary)


def _other_provider(primary: ListingProviderChoice) -> ListingProviderChoice:
    return "mimo" if primary == "chatgpt" else "chatgpt"


def get_listing_provider_order() -> tuple[ListingProviderChoice, ListingFallbackChoice]:
    raw = read_settings().get(LISTING_PROVIDER_KEY)
    if isinstance(raw, dict):
        primary = normalize_listing_provider(raw.get("primary"))
        fallback = normalize_listing_fallback(raw.get("fallback"), primary=primary)
        return primary, fallback
    # Legacy: listing_provider was a single preferred string.
    primary = normalize_listing_provider(raw)
    return primary, _other_provider(primary)


def get_preferred_listing_provider() -> ListingProviderChoice:
    """Compatibility alias for the primary listing provider."""
    return get_listing_provider_order()[0]


def set_listing_provider_order(
    primary: object,
    fallback: object | None = None,
) -> dict[str, str]:
    if not isinstance(primary, str) or primary.strip().lower() not in LISTING_PROVIDER_CHOICES:
        raise ValueError('Primary listing provider must be "chatgpt" or "mimo".')
    primary_choice = normalize_listing_provider(primary)

    if fallback is None:
        fallback_choice: ListingFallbackChoice = _other_provider(primary_choice)
    elif isinstance(fallback, str):
        cleaned = fallback.strip().lower()
        if cleaned == "none":
            fallback_choice = "none"
        elif cleaned in LISTING_PROVIDER_CHOICES:
            if cleaned == primary_choice:
                raise ValueError('Fallback must differ from primary, or be "none".')
            fallback_choice = cleaned  # type: ignore[assignment]
        else:
            raise ValueError('Fallback must be "chatgpt", "mimo", or "none".')
    else:
        raise ValueError('Fallback must be "chatgpt", "mimo", or "none".')

    def mutator(payload: dict) -> None:
        payload[LISTING_PROVIDER_KEY] = {
            "primary": primary_choice,
            "fallback": fallback_choice,
        }

    update_settings(mutator)
    return {"primary": primary_choice, "fallback": fallback_choice}


def set_preferred_listing_provider(preferred: object) -> ListingProviderChoice:
    """Set primary and keep the other provider as fallback."""
    order = set_listing_provider_order(preferred, fallback=None)
    return order["primary"]  # type: ignore[return-value]
