from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ChatGPTModelsConfig(BaseModel):
    vision_model: str | None = None
    listing_model: str | None = None
    reasoning_effort: str | None = None


class CursorModelsConfig(BaseModel):
    vision_model: str | None = None
    listing_model: str | None = None


class ProviderConfig(BaseModel):
    api_key: str | None = None


class MarketplacesConfig(BaseModel):
    selected: list[str]


class HiddenFieldConfig(BaseModel):
    marketplace: str
    field: str
    label: str | None = None
    scope: Literal["always", "listing"]
    conversation_id: str | None = None


class ChatGPTStatus(BaseModel):
    signed_in: bool
    email: str | None = None
    plan: str | None = None
    pending: dict | None = None
    error: str | None = None


class ProviderStatus(BaseModel):
    provider: str
    primary: Literal["chatgpt", "mimo", "cursor"]
    fallback: Literal["chatgpt", "mimo", "cursor", "none"]
    configured: bool
    masked_key: str | None
    masked_cursor_key: str | None = None
    vision_model: str
    listing_model: str
    base_url: str
    chatgpt: ChatGPTStatus


class PreferredProviderConfig(BaseModel):
    primary: Literal["chatgpt", "mimo", "cursor"]
    fallback: Literal["chatgpt", "mimo", "cursor", "none"] | None = None


def _chatgpt_status() -> ChatGPTStatus:
    from vendoo_studio.services import chatgpt_oauth
    from vendoo_studio.services.keychain import get_chatgpt_tokens

    tokens = get_chatgpt_tokens() if chatgpt_oauth.chatgpt_signed_in() else None
    profile = chatgpt_oauth.profile_from_tokens(tokens)
    return ChatGPTStatus(
        signed_in=bool(tokens),
        email=profile.get("email"),
        plan=profile.get("plan"),
        pending=chatgpt_oauth.pending_login(),
        error=None if tokens else chatgpt_oauth.login_error(),
    )


@router.get("/provider")
def get_provider():
    from vendoo_studio.services.keychain import get_api_key, get_cursor_api_key, mask_secret
    from vendoo_studio.services.listing_provider import get_listing_provider
    from vendoo_studio.services.user_settings import get_listing_provider_order

    chatgpt = _chatgpt_status()
    key = get_api_key()
    masked = mask_secret(key)
    masked_cursor = mask_secret(get_cursor_api_key())
    primary, fallback = get_listing_provider_order()
    active = get_listing_provider()
    active_name = getattr(active, "name", None)

    if active_name == "chatgpt":
        from vendoo_studio.providers.chatgpt_codex import resolved_chatgpt_models

        vision_model, listing_model = resolved_chatgpt_models()
        return ProviderStatus(
            provider="chatgpt",
            primary=primary,
            fallback=fallback,
            configured=True,
            masked_key=masked,
            masked_cursor_key=masked_cursor,
            vision_model=vision_model,
            listing_model=listing_model,
            base_url="https://chatgpt.com/backend-api/codex",
            chatgpt=chatgpt,
        )

    if active_name == "cursor":
        from vendoo_studio.services.user_settings import resolved_cursor_models

        vision_model, listing_model = resolved_cursor_models()
        return ProviderStatus(
            provider="cursor",
            primary=primary,
            fallback=fallback,
            configured=True,
            masked_key=masked,
            masked_cursor_key=masked_cursor,
            vision_model=vision_model,
            listing_model=listing_model,
            base_url="cursor-sdk://local",
            chatgpt=chatgpt,
        )

    return ProviderStatus(
        provider="xiaomi-mimo",
        primary=primary,
        fallback=fallback,
        configured=bool(active),
        masked_key=masked,
        masked_cursor_key=masked_cursor,
        vision_model="mimo-v2.5",
        listing_model="mimo-v2.5-pro",
        base_url="https://api.xiaomimimo.com/v1",
        chatgpt=chatgpt,
    )


@router.put("/provider")
def set_provider(config: ProviderConfig):
    from vendoo_studio.providers.xiaomi_mimo import normalize_mimo_api_key
    from vendoo_studio.services.keychain import set_api_key

    key = normalize_mimo_api_key(config.api_key or "")
    if not key:
        raise HTTPException(400, "API key is required")
    set_api_key(key)
    return {"ok": True}


@router.put("/provider/preferred")
def set_preferred_provider(config: PreferredProviderConfig):
    from vendoo_studio.services.user_settings import set_listing_provider_order

    try:
        order = set_listing_provider_order(config.primary, config.fallback)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **order}


@router.delete("/provider/key")
def delete_key():
    from vendoo_studio.services.keychain import delete_api_key

    delete_api_key()
    return {"ok": True}


@router.post("/provider/test")
async def test_connection():
    from vendoo_studio.services.listing_provider import get_listing_provider

    provider = get_listing_provider()
    if provider is None:
        raise HTTPException(
            400,
            "Sign in with ChatGPT in Settings, or add a MiMo or Cursor API key.",
        )

    name = getattr(provider, "name", "xiaomi-mimo")
    try:
        ok = await provider.test_connection()
    except Exception as exc:
        return {"ok": False, "provider": name, "error": str(exc)}
    return {"ok": ok, "provider": name, "error": None if ok else "Connection failed"}


@router.post("/provider/mimo/test")
async def test_mimo():
    """Always exercise the saved MiMo key, even when another provider is primary."""
    from vendoo_studio.providers.xiaomi_mimo import MiMoProvider
    from vendoo_studio.services.keychain import get_api_key

    key = get_api_key()
    if not key:
        raise HTTPException(400, "Add a MiMo API key in Settings.")
    provider = MiMoProvider(api_key=key)
    try:
        ok = await provider.test_connection()
    except Exception as exc:
        return {"ok": False, "provider": "xiaomi-mimo", "error": str(exc)}
    return {
        "ok": ok,
        "provider": "xiaomi-mimo",
        "error": None if ok else "Connection failed",
    }


@router.get("/chatgpt/models")
async def chatgpt_models():
    from vendoo_studio.providers.chatgpt_codex import (
        clamp_reasoning_effort,
        fetch_codex_models,
        resolved_chatgpt_models,
        resolved_chatgpt_reasoning,
        supported_reasoning_efforts,
    )
    from vendoo_studio.services.chatgpt_oauth import chatgpt_signed_in

    if not chatgpt_signed_in():
        raise HTTPException(400, "Sign in with ChatGPT first.")

    vision_model, listing_model = resolved_chatgpt_models()
    error = None
    try:
        slugs = await fetch_codex_models()
    except Exception as exc:
        slugs = []
        error = str(exc)
    for slug in (vision_model, listing_model):
        if slug and slug not in slugs:
            slugs.append(slug)
    reasoning_efforts = list(supported_reasoning_efforts(listing_model))
    reasoning_effort = clamp_reasoning_effort(resolved_chatgpt_reasoning(), listing_model)
    return {
        "models": slugs,
        "vision_model": vision_model,
        "listing_model": listing_model,
        "reasoning_effort": reasoning_effort,
        "reasoning_efforts": reasoning_efforts,
        "error": error,
    }


@router.put("/chatgpt/models")
def set_chatgpt_models(config: ChatGPTModelsConfig):
    from vendoo_studio.providers.chatgpt_codex import resolved_chatgpt_models
    from vendoo_studio.services.chatgpt_oauth import chatgpt_signed_in
    from vendoo_studio.services.keychain import set_chatgpt_models as persist_chatgpt_models

    if not chatgpt_signed_in():
        raise HTTPException(400, "Sign in with ChatGPT first.")

    vision = (config.vision_model or "").strip()
    listing = (config.listing_model or "").strip()
    reasoning = (config.reasoning_effort or "").strip()
    if not vision and not listing and not reasoning:
        raise HTTPException(400, "Choose a vision model, listing model, or reasoning mode.")
    persist_chatgpt_models(
        vision_model=vision or None,
        listing_model=listing or None,
        reasoning_effort=reasoning or None,
    )
    vision_model, listing_model = resolved_chatgpt_models()
    from vendoo_studio.providers.chatgpt_codex import clamp_reasoning_effort, resolved_chatgpt_reasoning

    return {
        "ok": True,
        "vision_model": vision_model,
        "listing_model": listing_model,
        "reasoning_effort": clamp_reasoning_effort(resolved_chatgpt_reasoning(), listing_model),
    }


@router.get("/cursor/models")
async def cursor_models():
    """Return saved Cursor model prefs and catalog IDs when a key is present."""
    import asyncio

    from vendoo_studio.providers.cursor_agent import CursorProvider
    from vendoo_studio.services.keychain import get_cursor_api_key
    from vendoo_studio.services.user_settings import (
        AUTO_CURSOR_MODEL,
        DEFAULT_CURSOR_MODEL,
        resolved_cursor_models,
    )

    vision_model, listing_model = resolved_cursor_models()
    slugs = [AUTO_CURSOR_MODEL, DEFAULT_CURSOR_MODEL]
    error = None
    key = get_cursor_api_key()
    if key:
        try:
            provider = CursorProvider(api_key=key)
            for model_id in await asyncio.to_thread(provider.list_model_ids):
                if model_id not in slugs:
                    slugs.append(model_id)
        except Exception as exc:
            error = str(exc)
    for slug in (vision_model, listing_model):
        if slug and slug not in slugs:
            slugs.append(slug)
    return {
        "models": slugs,
        "vision_model": vision_model,
        "listing_model": listing_model,
        "error": error,
    }


@router.put("/cursor/models")
def set_cursor_models(config: CursorModelsConfig):
    from vendoo_studio.services.keychain import get_cursor_api_key
    from vendoo_studio.services.user_settings import (
        resolved_cursor_models,
        set_cursor_models as persist_cursor_models,
    )

    if not get_cursor_api_key():
        raise HTTPException(400, "Add a Cursor API key in Settings.")

    vision = (config.vision_model or "").strip()
    listing = (config.listing_model or "").strip()
    if not vision and not listing:
        raise HTTPException(400, "Choose a vision model or listing model.")
    try:
        persist_cursor_models(vision_model=vision or None, listing_model=listing or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    vision_model, listing_model = resolved_cursor_models()
    return {"ok": True, "vision_model": vision_model, "listing_model": listing_model}


def _marketplaces_payload(selected: list[str]) -> dict:
    from vendoo_studio.services.marketplaces import catalog_payload, selected_fillable_platforms

    return {
        "available": catalog_payload(),
        "selected": selected,
        "fillable": selected_fillable_platforms(selected),
    }


@router.get("/marketplaces")
def get_marketplaces():
    from vendoo_studio.services.marketplaces import get_selected_marketplaces

    return _marketplaces_payload(get_selected_marketplaces())


@router.put("/marketplaces")
def set_marketplaces(config: MarketplacesConfig):
    from vendoo_studio.services.marketplaces import set_selected_marketplaces

    try:
        selected = set_selected_marketplaces(config.selected)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **_marketplaces_payload(selected)}


@router.get("/hidden-fields")
def get_hidden_fields(conversation_id: str | None = None):
    from vendoo_studio.services.hidden_fields import hidden_fields

    return hidden_fields(conversation_id)


@router.put("/hidden-fields")
def hide_hidden_field(config: HiddenFieldConfig):
    from vendoo_studio.services.hidden_fields import hide_field

    try:
        return {
            "ok": True,
            **hide_field(
                marketplace=config.marketplace,
                field=config.field,
                scope=config.scope,
                conversation_id=config.conversation_id,
                label=config.label,
            ),
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/hidden-fields")
def restore_hidden_field(config: HiddenFieldConfig):
    from vendoo_studio.services.hidden_fields import restore_field

    try:
        return {
            "ok": True,
            **restore_field(
                marketplace=config.marketplace,
                field=config.field,
                scope=config.scope,
                conversation_id=config.conversation_id,
            ),
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class RestoreAllHiddenFields(BaseModel):
    conversation_id: str | None = None


class RestoreMatchingHiddenFields(BaseModel):
    conversation_id: str | None = None
    fields: list[dict[str, str]]


@router.post("/hidden-fields/restore-all")
def restore_all_hidden_fields(body: RestoreAllHiddenFields):
    from vendoo_studio.services.hidden_fields import restore_all_fields

    return {"ok": True, **restore_all_fields(body.conversation_id)}


@router.post("/hidden-fields/restore-matching")
def restore_matching_hidden_fields(body: RestoreMatchingHiddenFields):
    from vendoo_studio.services.hidden_fields import restore_matching_fields

    matches = [
        (str(item.get("marketplace") or ""), str(item.get("field") or ""))
        for item in body.fields
        if isinstance(item, dict)
    ]
    return {
        "ok": True,
        **restore_matching_fields(matches, body.conversation_id),
    }


@router.post("/chatgpt/login")
async def chatgpt_login():
    from vendoo_studio.services import chatgpt_oauth

    try:
        pending = await chatgpt_oauth.start_login()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return pending


@router.delete("/chatgpt/login")
async def chatgpt_login_cancel():
    from vendoo_studio.services import chatgpt_oauth

    await chatgpt_oauth.cancel_login()
    return {"ok": True}


@router.delete("/chatgpt")
async def chatgpt_logout():
    from vendoo_studio.services import chatgpt_oauth

    await chatgpt_oauth.cancel_login()
    chatgpt_oauth.logout()
    return {"ok": True}


class BraveConfig(BaseModel):
    api_key: str | None = None


class CursorConfig(BaseModel):
    api_key: str | None = None


def _brave_payload() -> dict:
    from vendoo_studio.services.keychain import get_brave_api_key, mask_secret

    key = get_brave_api_key()
    return {"configured": bool(key), "masked_key": mask_secret(key)}


def _cursor_payload() -> dict:
    from vendoo_studio.services.keychain import get_cursor_api_key, mask_secret

    key = get_cursor_api_key()
    return {"configured": bool(key), "masked_key": mask_secret(key)}


@router.get("/brave")
def get_brave():
    return _brave_payload()


@router.put("/brave")
def set_brave(config: BraveConfig):
    from vendoo_studio.services.keychain import set_brave_api_key

    key = (config.api_key or "").strip()
    if not key:
        raise HTTPException(400, "API key is required")
    set_brave_api_key(key)
    return {"ok": True, **_brave_payload()}


@router.delete("/brave")
def delete_brave():
    from vendoo_studio.services.keychain import delete_brave_api_key

    delete_brave_api_key()
    return {"ok": True, **_brave_payload()}


@router.post("/brave/test")
async def test_brave():
    from vendoo_studio.services.brave_search import test_brave_connection

    ok, error = await test_brave_connection()
    return {"ok": ok, "error": error}


@router.get("/cursor")
def get_cursor():
    return _cursor_payload()


@router.put("/cursor")
def set_cursor(config: CursorConfig):
    from vendoo_studio.providers.cursor_agent import normalize_cursor_api_key
    from vendoo_studio.services.keychain import set_cursor_api_key

    key = normalize_cursor_api_key(config.api_key or "")
    if not key:
        raise HTTPException(400, "API key is required")
    set_cursor_api_key(key)
    return {"ok": True, **_cursor_payload()}


@router.delete("/cursor")
def delete_cursor():
    from vendoo_studio.services.keychain import delete_cursor_api_key

    delete_cursor_api_key()
    return {"ok": True, **_cursor_payload()}


@router.post("/cursor/test")
async def test_cursor():
    from vendoo_studio.providers.cursor_agent import CursorProvider
    from vendoo_studio.services.keychain import get_cursor_api_key

    key = get_cursor_api_key()
    if not key:
        raise HTTPException(400, "Add a Cursor API key in Settings.")
    provider = CursorProvider(api_key=key)
    try:
        ok = await provider.test_connection()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": ok, "error": None if ok else "Connection failed"}


@router.post("/setup-guide/dismiss")
def dismiss_setup_guide():
    from vendoo_studio.services.user_settings import dismiss_setup_guide as persist_setup_guide_dismissed

    return persist_setup_guide_dismissed()


@router.get("/data-folder")
def get_data_folder():
    from vendoo_studio.config import user_data_root

    root = user_data_root()
    return {
        "path": str(root),
        "contains": [
            "vendoo_studio.db",
            "photos/",
            "fill-logs/",
            "settings.json",
            "pairing_token.txt",
            "catalog-index/",
            "vendoo-extension/",
            "logs/",
        ],
        "secrets": "macOS Keychain (API keys and ChatGPT tokens are not stored in this folder)",
    }


class UiPrefsConfig(BaseModel):
    recent_vendoo_labels: list[str] | None = None
    settled_shelf_expanded: bool | None = None
    remember_labels: str | list[str] | None = None


@router.get("/ui")
def get_ui_prefs():
    from vendoo_studio.services.user_settings import get_ui_prefs as read_ui_prefs

    return {"ok": True, **read_ui_prefs()}


@router.put("/ui")
def put_ui_prefs(config: UiPrefsConfig):
    from vendoo_studio.services import user_settings

    try:
        if config.remember_labels is not None:
            user_settings.remember_vendoo_labels(config.remember_labels)
        prefs = user_settings.set_ui_prefs(
            recent_vendoo_labels=config.recent_vendoo_labels,
            settled_shelf_expanded=config.settled_shelf_expanded,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **prefs}


class ListingFormulasConfig(BaseModel):
    title: str | None = None
    description: str | None = None


def _listing_formulas_payload() -> dict:
    from vendoo_studio.services.skill_formulas import DEFAULT_DESCRIPTION_FORMULA, DEFAULT_TITLE_FORMULA
    from vendoo_studio.services.user_settings import get_listing_formulas

    custom = get_listing_formulas()
    return {
        "title": custom.get("title", ""),
        "description": custom.get("description", ""),
        "default_title": DEFAULT_TITLE_FORMULA,
        "default_description": DEFAULT_DESCRIPTION_FORMULA,
    }


@router.get("/formulas")
def get_listing_formulas():
    return {"ok": True, **_listing_formulas_payload()}


@router.put("/formulas")
def put_listing_formulas(config: ListingFormulasConfig):
    from vendoo_studio.services.user_settings import set_listing_formulas

    try:
        set_listing_formulas(title=config.title, description=config.description)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **_listing_formulas_payload()}


@router.get("/tailscale")
def get_tailscale():
    from vendoo_studio.services.tailscale_serve import status as tailscale_status

    return tailscale_status()


@router.post("/tailscale/enable")
def enable_tailscale():
    from vendoo_studio.services.tailscale_serve import TailscaleServeError, enable

    try:
        return enable()
    except TailscaleServeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/tailscale/disable")
def disable_tailscale():
    from vendoo_studio.services.tailscale_serve import TailscaleServeError, disable

    try:
        return disable()
    except TailscaleServeError as exc:
        raise HTTPException(400, str(exc)) from exc
