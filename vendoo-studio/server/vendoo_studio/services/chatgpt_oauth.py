from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
import webbrowser
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from vendoo_studio.services.keychain import (
    delete_chatgpt_tokens,
    get_chatgpt_tokens,
    set_chatgpt_tokens,
)

log = logging.getLogger("vendoo_studio.chatgpt_oauth")

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
TOKEN_URL = f"{ISSUER}/oauth/token"
DEVICE_USERCODE_URL = f"{ISSUER}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{ISSUER}/api/accounts/deviceauth/token"
DEVICE_CALLBACK = f"{ISSUER}/deviceauth/callback"
DEVICE_VERIFY_URL = f"{ISSUER}/codex/device"
ORIGINATOR = "vendoo-studio"
LOGIN_TIMEOUT_S = 15 * 60


@dataclass
class PendingLogin:
    verification_url: str
    user_code: str
    device_auth_id: str
    interval: int
    task: asyncio.Task | None = None
    error: str | None = None
    done: bool = False


_pending: PendingLogin | None = None
_pending_guard = threading.Lock()


def _b64url_json(segment: str) -> dict[str, Any]:
    padded = segment + "=" * ((4 - len(segment) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def jwt_claims(token: str | None) -> dict[str, Any]:
    if not token or token.count(".") != 2:
        return {}
    return _b64url_json(token.split(".")[1])


def jwt_auth_claims(token: str | None) -> dict[str, Any]:
    claims = jwt_claims(token)
    nested = claims.get("https://api.openai.com/auth")
    return nested if isinstance(nested, dict) else claims


def account_id_from_tokens(tokens: dict) -> str | None:
    for source in (tokens.get("id_token"), tokens.get("access_token")):
        auth = jwt_auth_claims(source if isinstance(source, str) else None)
        account_id = auth.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id.strip():
            return account_id.strip()
    stored = tokens.get("account_id")
    return stored.strip() if isinstance(stored, str) and stored.strip() else None


def profile_from_tokens(tokens: dict | None) -> dict[str, str | None]:
    if not tokens:
        return {"email": None, "plan": None, "account_id": None}
    claims = jwt_claims(tokens.get("id_token"))
    auth = jwt_auth_claims(tokens.get("id_token"))
    email = claims.get("email") or auth.get("email")
    plan = auth.get("chatgpt_plan_type") or claims.get("chatgpt_plan_type")
    return {
        "email": email if isinstance(email, str) else None,
        "plan": plan if isinstance(plan, str) else None,
        "account_id": account_id_from_tokens(tokens),
    }


def _token_payload(data: dict, existing: dict | None = None) -> dict:
    access = data.get("access_token")
    refresh = data.get("refresh_token") or (existing or {}).get("refresh_token")
    if not isinstance(access, str) or not access:
        raise RuntimeError("ChatGPT login did not return an access token")
    if not isinstance(refresh, str) or not refresh:
        raise RuntimeError("ChatGPT login did not return a refresh token")
    expires_in = data.get("expires_in")
    try:
        lifetime = int(expires_in)
    except (TypeError, ValueError):
        lifetime = 3600
    id_token = data.get("id_token") or (existing or {}).get("id_token")
    payload = {
        "access_token": access,
        "refresh_token": refresh,
        "id_token": id_token if isinstance(id_token, str) else "",
        "expires_at": int(time.time()) + max(lifetime - 60, 30),
    }
    payload["account_id"] = account_id_from_tokens(payload) or (existing or {}).get("account_id")
    return payload


async def _exchange_code(code: str, verifier: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urlencode({
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DEVICE_CALLBACK,
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            }),
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"ChatGPT token exchange failed ({resp.status_code})")
        return _token_payload(resp.json())


async def refresh_chatgpt_tokens(force: bool = False) -> dict | None:
    tokens = get_chatgpt_tokens()
    if not tokens:
        return None
    expires_at = tokens.get("expires_at")
    if not force and isinstance(expires_at, (int, float)) and expires_at > time.time() + 30:
        return tokens
    refresh = tokens.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        delete_chatgpt_tokens()
        raise RuntimeError("ChatGPT session expired. Sign in again.")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            content=urlencode({
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": CLIENT_ID,
            }),
        )
        if resp.status_code >= 400:
            delete_chatgpt_tokens()
            raise RuntimeError("ChatGPT session expired. Sign in again.")
        payload = _token_payload(resp.json(), tokens)
        set_chatgpt_tokens(payload)
        return payload


def chatgpt_signed_in() -> bool:
    tokens = get_chatgpt_tokens()
    return bool(tokens and tokens.get("access_token") and tokens.get("refresh_token"))


async def start_login() -> dict:
    global _pending
    with _pending_guard:
        previous = _pending
        _pending = None
    if previous and previous.task and not previous.task.done():
        previous.task.cancel()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            DEVICE_USERCODE_URL,
            headers={"Content-Type": "application/json"},
            json={"client_id": CLIENT_ID},
        )
        if resp.status_code == 404:
            raise RuntimeError(
                "Device-code login is not enabled for this ChatGPT account. "
                "Enable it in ChatGPT security settings, or run `codex login`."
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Could not start ChatGPT login ({resp.status_code})")
        body = resp.json()
    user_code = str(body.get("user_code") or body.get("usercode") or "")
    device_auth_id = str(body.get("device_auth_id") or "")
    if not user_code or not device_auth_id:
        raise RuntimeError("ChatGPT login did not return a device code")
    try:
        interval = int(body.get("interval") or 5)
    except (TypeError, ValueError):
        interval = 5
    pending = PendingLogin(
        verification_url=DEVICE_VERIFY_URL,
        user_code=user_code,
        device_auth_id=device_auth_id,
        interval=max(interval, 1),
    )
    pending.task = asyncio.create_task(_complete_login(pending))
    with _pending_guard:
        _pending = pending
    try:
        webbrowser.open(pending.verification_url)
    except Exception:
        log.debug("could not open ChatGPT login URL", exc_info=True)
    return {
        "verification_url": pending.verification_url,
        "user_code": pending.user_code,
    }


async def _complete_login(pending: PendingLogin) -> None:
    global _pending
    deadline = time.time() + LOGIN_TIMEOUT_S
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            while time.time() < deadline:
                if _pending is not pending:
                    return
                resp = await client.post(
                    DEVICE_TOKEN_URL,
                    headers={"Content-Type": "application/json"},
                    json={
                        "device_auth_id": pending.device_auth_id,
                        "user_code": pending.user_code,
                    },
                )
                if resp.status_code < 400:
                    body = resp.json()
                    tokens = await _exchange_code(
                        str(body["authorization_code"]),
                        str(body["code_verifier"]),
                    )
                    set_chatgpt_tokens(tokens)
                    pending.done = True
                    return
                if resp.status_code not in (403, 404):
                    raise RuntimeError(f"ChatGPT login failed ({resp.status_code})")
                await asyncio.sleep(pending.interval)
        raise RuntimeError("ChatGPT login timed out after 15 minutes")
    except asyncio.CancelledError:
        pending.error = "Login cancelled"
        raise
    except Exception as exc:
        pending.error = str(exc)
        log.warning("ChatGPT login failed: %s", exc)
    finally:
        pending.done = True


async def cancel_login() -> None:
    global _pending
    with _pending_guard:
        previous = _pending
        _pending = None
    if previous and previous.task and not previous.task.done():
        previous.task.cancel()


def pending_login() -> dict | None:
    if not _pending or _pending.done:
        return None
    return {
        "verification_url": _pending.verification_url,
        "user_code": _pending.user_code,
        "error": _pending.error,
    }


def login_error() -> str | None:
    if _pending and _pending.error and _pending.done:
        return _pending.error
    return None


def logout() -> None:
    delete_chatgpt_tokens()
