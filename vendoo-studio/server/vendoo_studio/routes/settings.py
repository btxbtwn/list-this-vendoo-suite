from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ChatGPTModelsConfig(BaseModel):
    vision_model: str | None = None
    listing_model: str | None = None
    reasoning_effort: str | None = None


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
    configured: bool
    masked_key: str | None
    vision_model: str
    listing_model: str
    base_url: str
    chatgpt: ChatGPTStatus


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
    from vendoo_studio.services.chatgpt_oauth import chatgpt_signed_in
    from vendoo_studio.services.keychain import get_api_key, mask_secret

    chatgpt = _chatgpt_status()
    key = get_api_key()
    masked = mask_secret(key)

    if chatgpt_signed_in():
        from vendoo_studio.providers.chatgpt_codex import resolved_chatgpt_models

        vision_model, listing_model = resolved_chatgpt_models()
        return ProviderStatus(
            provider="chatgpt",
            configured=True,
            masked_key=masked,
            vision_model=vision_model,
            listing_model=listing_model,
            base_url="https://chatgpt.com/backend-api/codex",
            chatgpt=chatgpt,
        )

    return ProviderStatus(
        provider="xiaomi-mimo",
        configured=bool(key),
        masked_key=masked,
        vision_model="mimo-v2.5",
        listing_model="mimo-v2.5-pro",
        base_url="https://api.xiaomimimo.com/v1",
        chatgpt=chatgpt,
    )


@router.put("/provider")
def set_provider(config: ProviderConfig):
    from vendoo_studio.services.keychain import set_api_key

    if not config.api_key:
        raise HTTPException(400, "API key is required")

    set_api_key(config.api_key)
    return {"ok": True}


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
        raise HTTPException(400, "Sign in with ChatGPT in Settings, or add a MiMo API key.")

    name = getattr(provider, "name", "xiaomi-mimo")
    try:
        ok = await provider.test_connection()
    except Exception as exc:
        return {"ok": False, "provider": name, "error": str(exc)}
    return {"ok": ok, "provider": name}


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


def _brave_payload() -> dict:
    from vendoo_studio.services.keychain import get_brave_api_key, mask_secret

    key = get_brave_api_key()
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


@router.post("/setup-guide/dismiss")
def dismiss_setup_guide():
    from vendoo_studio.services.user_settings import dismiss_setup_guide as persist_setup_guide_dismissed

    return persist_setup_guide_dismissed()
