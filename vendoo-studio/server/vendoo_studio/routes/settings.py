from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ChatGPTModelsConfig(BaseModel):
    vision_model: str | None = None
    listing_model: str | None = None


class ProviderConfig(BaseModel):
    api_key: str | None = None


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
    from vendoo_studio.services.keychain import get_api_key

    chatgpt = _chatgpt_status()
    key = get_api_key()
    masked = None
    if key:
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"

    if chatgpt_signed_in():
        from vendoo_studio.providers.chatgpt_codex import resolved_chatgpt_models

        vision_model, listing_model = resolved_chatgpt_models()
        return ProviderStatus(
            provider="chatgpt",
            configured=True,
            masked_key=None,
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
    from vendoo_studio.providers.chatgpt_codex import fetch_codex_models, resolved_chatgpt_models
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
    return {
        "models": slugs,
        "vision_model": vision_model,
        "listing_model": listing_model,
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
    if not vision and not listing:
        raise HTTPException(400, "Choose a vision or listing model.")
    persist_chatgpt_models(
        vision_model=vision or None,
        listing_model=listing or None,
    )
    vision_model, listing_model = resolved_chatgpt_models()
    return {"ok": True, "vision_model": vision_model, "listing_model": listing_model}


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
