from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ProviderConfig(BaseModel):
    api_key: str | None = None


class ProviderStatus(BaseModel):
    provider: str
    configured: bool
    masked_key: str | None
    vision_model: str
    listing_model: str
    base_url: str


@router.get("/provider")
def get_provider():
    from vendoo_studio.services.keychain import get_api_key

    key = get_api_key()
    masked = None
    if key:
        masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"

    return ProviderStatus(
        provider="xiaomi-mimo",
        configured=bool(key),
        masked_key=masked,
        vision_model="mimo-v2.5",
        listing_model="mimo-v2.5-pro",
        base_url="https://api.xiaomimimo.com/v1",
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
    from vendoo_studio.services.keychain import get_api_key
    from vendoo_studio.providers.xiaomi_mimo import MiMoProvider

    key = get_api_key()
    if not key:
        raise HTTPException(400, "No API key configured")

    provider = MiMoProvider(api_key=key)
    ok = await provider.test_connection()
    return {"ok": ok, "provider": "xiaomi-mimo"}
