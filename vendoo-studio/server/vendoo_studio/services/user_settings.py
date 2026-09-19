from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Literal

from vendoo_studio.config import user_data_root

_lock = threading.Lock()
SETUP_GUIDE_DISMISSED_KEY = "setup_guide_dismissed"
LISTING_PROVIDER_KEY = "listing_provider"
UI_PREFS_KEY = "ui"
RECENT_LABELS_KEY = "recent_vendoo_labels"
SETTLED_SHELF_KEY = "settled_shelf_expanded"
MAX_RECENT_LABELS = 12
LISTING_PROVIDER_CHOICES = frozenset({"chatgpt", "mimo", "cursor"})
LISTING_FALLBACK_CHOICES = frozenset({"chatgpt", "mimo", "cursor", "none"})
DEFAULT_LISTING_PROVIDER: Literal["chatgpt", "mimo", "cursor"] = "chatgpt"
DEFAULT_LISTING_FALLBACK: Literal["chatgpt", "mimo", "cursor", "none"] = "mimo"
DEFAULT_SETTLED_SHELF_EXPANDED = True

ListingProviderChoice = Literal["chatgpt", "mimo", "cursor"]
ListingFallbackChoice = Literal["chatgpt", "mimo", "cursor", "none"]


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
    if primary == "chatgpt":
        return "mimo"
    if primary == "mimo":
        return "chatgpt"
    return "chatgpt"


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
        raise ValueError('Primary listing provider must be "chatgpt", "mimo", or "cursor".')
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
            raise ValueError('Fallback must be "chatgpt", "mimo", "cursor", or "none".')
    else:
        raise ValueError('Fallback must be "chatgpt", "mimo", "cursor", or "none".')

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


def _ui_prefs(settings: dict | None = None) -> dict:
    payload = settings if settings is not None else read_settings()
    raw = payload.get(UI_PREFS_KEY)
    return raw if isinstance(raw, dict) else {}


def _clean_recent_labels(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    labels: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        label = " ".join(item.split()).strip()
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
        if len(labels) >= MAX_RECENT_LABELS:
            break
    return labels


def get_ui_prefs() -> dict:
    ui = _ui_prefs()
    settled = ui.get(SETTLED_SHELF_KEY)
    return {
        RECENT_LABELS_KEY: _clean_recent_labels(ui.get(RECENT_LABELS_KEY)),
        SETTLED_SHELF_KEY: DEFAULT_SETTLED_SHELF_EXPANDED if not isinstance(settled, bool) else settled,
    }


def set_ui_prefs(
    *,
    recent_vendoo_labels: object | None = None,
    settled_shelf_expanded: object | None = None,
) -> dict:
    if recent_vendoo_labels is None and settled_shelf_expanded is None:
        return get_ui_prefs()

    def mutator(payload: dict) -> None:
        ui = dict(_ui_prefs(payload))
        if recent_vendoo_labels is not None:
            ui[RECENT_LABELS_KEY] = _clean_recent_labels(recent_vendoo_labels)
        if settled_shelf_expanded is not None:
            if not isinstance(settled_shelf_expanded, bool):
                raise ValueError("settled_shelf_expanded must be a boolean")
            ui[SETTLED_SHELF_KEY] = settled_shelf_expanded
        payload[UI_PREFS_KEY] = ui

    update_settings(mutator)
    return get_ui_prefs()


def remember_vendoo_labels(raw: object) -> list[str]:
    if isinstance(raw, str):
        candidates: object = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, list):
        candidates = raw
    else:
        candidates = []
    incoming = _clean_recent_labels(candidates)
    if not incoming:
        return get_ui_prefs()[RECENT_LABELS_KEY]

    def mutator(payload: dict) -> None:
        ui = dict(_ui_prefs(payload))
        existing = _clean_recent_labels(ui.get(RECENT_LABELS_KEY))
        remembered = {label.casefold() for label in incoming}
        merged = [
            *incoming,
            *[label for label in existing if label.casefold() not in remembered],
        ]
        ui[RECENT_LABELS_KEY] = merged[:MAX_RECENT_LABELS]
        payload[UI_PREFS_KEY] = ui

    update_settings(mutator)
    return get_ui_prefs()[RECENT_LABELS_KEY]


LISTING_FORMULAS_KEY = "listing_formulas"
MAX_FORMULA_CHARS = 4000


def get_listing_formulas() -> dict[str, str]:
    raw = read_settings().get(LISTING_FORMULAS_KEY)
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key in ("title", "description"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            cleaned[key] = value.strip()
    return cleaned


def set_listing_formulas(*, title: object = None, description: object = None) -> dict[str, str]:
    """Set or clear a custom title/description formula. Pass "" to reset that formula to the default."""

    def clean(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Formula must be text")
        text = value.strip()
        if len(text) > MAX_FORMULA_CHARS:
            raise ValueError(f"Formula must be {MAX_FORMULA_CHARS} characters or fewer")
        return text

    title_clean = clean(title)
    description_clean = clean(description)

    def mutator(payload: dict) -> None:
        raw = payload.get(LISTING_FORMULAS_KEY)
        current = dict(raw) if isinstance(raw, dict) else {}
        if title_clean is not None:
            if title_clean:
                current["title"] = title_clean
            else:
                current.pop("title", None)
        if description_clean is not None:
            if description_clean:
                current["description"] = description_clean
            else:
                current.pop("description", None)
        if current:
            payload[LISTING_FORMULAS_KEY] = current
        else:
            payload.pop(LISTING_FORMULAS_KEY, None)

    update_settings(mutator)
    return get_listing_formulas()
