from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from vendoo_studio.main import app
from vendoo_studio.services import chrome_bridge


def test_qa_bridge_stamp_uses_the_isolated_api_port():
    with patch.object(chrome_bridge, "PORT", 4388):
        stamp = chrome_bridge._build_stamp_contents("test-build")
    assert "var STUDIO_API_ORIGIN = 'http://127.0.0.1:4388';" in stamp


def test_bridge_reload_only_syncs_files_and_messages_the_connected_worker():
    with (patch("vendoo_studio.services.chrome_bridge.sync_bundled_extension") as sync,
          patch("vendoo_studio.services.chrome_bridge.relaunch_studio_chrome") as launch,
          patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=True, version="test", reload_generation=None, build="old")),
          patch("vendoo_studio.services.extension_connection.extension_reload_token_if_needed", return_value="reload-token"),
          patch("vendoo_studio.services.extension_connection.request_extension_reload", new_callable=AsyncMock, return_value=True) as reload):
        response = TestClient(app).post("/api/extension/reload")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "sent": True}
    sync.assert_called_once()
    reload.assert_awaited_once_with("reload-token")
    launch.assert_not_called()


def test_bridge_reload_never_opens_chrome_when_disconnected():
    with (patch("vendoo_studio.services.chrome_bridge.sync_bundled_extension"),
          patch("vendoo_studio.services.chrome_bridge.relaunch_studio_chrome") as launch,
          patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False))):
        response = TestClient(app).post("/api/extension/reload")
    assert response.status_code == 409
    launch.assert_not_called()
