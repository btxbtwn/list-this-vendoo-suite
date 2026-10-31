from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services.extension_connection import _public_connect, _public_session
from vendoo_studio.services.browser_bridge import BrowserBridgeError


def test_session_summary_drops_cookies_and_tokens():
    summary = _public_session({
        "state": "signed_in",
        "expires_at": 1_900_000_000,
        "label": "  ada  ",
        "expiring": False,
        "access_token": "secret-token",
        "headers": {"authorization": "Bearer secret"},
    })
    assert summary == {"state": "signed_in", "expires_at": 1900000000, "label": "ada", "expiring": False}
    assert "secret" not in str(summary)
    assert _public_session({"state": "signed_out", "label": "ada", "expires_at": 10, "access_token": "secret"}) == {
        "state": "signed_out", "expires_at": None, "label": None, "expiring": False,
    }
    assert _public_connect({"ok": True, "state": "expired", "signed_in": True, "access_token": "secret"})["signed_in"] is False


def test_session_status_returns_only_the_chrome_summaries():
    def request(job, message_type, payload=None, timeout=20):
        assert message_type == "marketplace.sessions"
        assert job.id is None
        return {"ok": True, "sessions": {
            "depop": {"state": "signed_in", "expires_at": 20, "label": "ada", "access_token": "secret-token"},
            "poshmark": {"state": "expired", "expires_at": 10, "label": "x" * 90},
            "mercari": {"state": "nope", "headers": {"authorization": "Bearer secret"}},
            "sellwild": "bad",
            "ebay": {"state": "signed_in", "access_token": "other-secret"},
        }}

    with patch("vendoo_studio.services.browser_bridge.request", new=AsyncMock(side_effect=request)):
        response = TestClient(app).get("/api/marketplaces/sessions")
    assert response.status_code == 200
    body = response.json()
    assert set(body["sessions"]) == {"depop", "poshmark", "mercari", "sellwild", "vinted", "facebook"}
    assert body["sessions"]["depop"]["label"] == "ada"
    assert body["sessions"]["poshmark"]["label"] is None
    assert body["sessions"]["mercari"]["state"] == "unknown"
    assert body["sessions"]["sellwild"]["state"] == "unknown"
    assert body["sessions"]["vinted"]["state"] == "unknown"
    assert "secret" not in response.text


def test_session_status_asks_to_connect_chrome():
    with patch("vendoo_studio.services.browser_bridge.request", new=AsyncMock(side_effect=BrowserBridgeError("Connect Chrome to use the Vendoo browser."))):
        response = TestClient(app).get("/api/marketplaces/sessions")
    assert response.status_code == 409


def test_connect_response_cannot_carry_a_token():
    def request(job, message_type, payload=None, timeout=40):
        assert message_type == "marketplace.connect"
        assert payload["marketplace"] == "depop"
        return {"ok": True, "state": "signed_in", "signed_in": True, "label": "ada", "access_token": "secret-token", "page_read_status": 200}

    with patch("vendoo_studio.services.browser_bridge.request", new=AsyncMock(side_effect=request)):
        response = TestClient(app).post("/api/marketplaces/depop/connect")
    assert response.status_code == 200
    assert response.json()["signed_in"] is True
    assert "secret" not in response.text
    assert "page_read_status" not in response.json()


def test_vinted_connect_is_a_session_summary():
    def request(job, message_type, payload=None, timeout=40):
        assert message_type == "marketplace.connect"
        assert payload["marketplace"] == "vinted"
        assert job.id is None
        return {"ok": True, "state": "signed_in", "label": "ada", "access_token_web": "secret-token"}

    with patch("vendoo_studio.services.browser_bridge.request", new=AsyncMock(side_effect=request)):
        response = TestClient(app).post("/api/marketplaces/vinted/connect")
    assert response.status_code == 200
    assert response.json()["signed_in"] is True
    assert response.json()["label"] == "ada"
    assert "secret" not in response.text


def test_recording_runs_in_anteroom_and_is_saved_for_later(tmp_path):
    import time

    request = AsyncMock(return_value={"ok": True, "goal": "offers", "requests": [{"method": "GET"}]})
    with patch("vendoo_studio.services.browser_bridge.request", new=request), \
            patch("vendoo_studio.services.marketplace_recording.RECORDINGS_DIR", tmp_path), TestClient(app) as client:
        assert client.get("/api/marketplaces/depop/record?goal=offers").json() == {"recording": False, "result": None}
        assert client.post("/api/marketplaces/depop/record?goal=offers").status_code == 202
        for _ in range(50):
            body = client.get("/api/marketplaces/depop/record?goal=offers").json()
            if body["result"]:
                break
            time.sleep(0.02)
        assert body["recording"] is False
        assert body["result"]["requests"] == [{"method": "GET"}]
        assert body["result"]["finished_at"]
        assert client.post("/api/marketplaces/depop/record").status_code == 404
        assert client.post("/api/marketplaces/sellwild/record?goal=offers").status_code == 404
        assert client.post("/api/marketplaces/mercari/record?goal=publish").status_code == 422
    assert request.await_args_list[0].args[2] == {"marketplace": "depop", "goal": "offers"}


def test_only_one_recording_runs_at_a_time(tmp_path):
    import asyncio

    async def slow(*_args, **_kwargs):
        await asyncio.sleep(0.5)
        return {"ok": True, "requests": []}

    with patch("vendoo_studio.services.browser_bridge.request", new=AsyncMock(side_effect=slow)), \
            patch("vendoo_studio.services.marketplace_recording.RECORDINGS_DIR", tmp_path), TestClient(app) as client:
        assert client.post("/api/marketplaces/mercari/record?goal=offers").status_code == 202
        assert client.get("/api/marketplaces/mercari/record?goal=offers").json()["recording"] is True
        assert client.post("/api/marketplaces/depop/record?goal=offers").status_code == 409


def test_unknown_marketplace_connect_is_rejected():
    with patch("vendoo_studio.services.browser_bridge.request", new=AsyncMock()) as request:
        response = TestClient(app).post("/api/marketplaces/ebay/connect")
    assert response.status_code == 404
    request.assert_not_awaited()
