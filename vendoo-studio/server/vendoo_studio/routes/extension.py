"""HTTP/WebSocket registration for the extension bridge service."""
from fastapi import APIRouter

from vendoo_studio.services import extension_connection as bridge

router = APIRouter(tags=["extension"])

router.add_api_route('/api/extension/pairing-token', bridge.get_pairing_token, methods=['GET'])
router.add_api_route('/api/extension/status', bridge.extension_status, methods=['GET'])
router.add_api_route('/api/extension/reload', bridge.reload_extension, methods=['POST'])
router.add_api_route('/api/marketplaces/sessions', bridge.marketplace_sessions, methods=['GET'])
router.add_api_route('/api/marketplaces/{marketplace}/connect', bridge.connect_marketplace, methods=['POST'])
router.add_api_route('/api/marketplaces/{marketplace}/record', bridge.record_marketplace_requests, methods=['POST'], status_code=202)
router.add_api_route('/api/marketplaces/{marketplace}/record', bridge.recorded_marketplace_requests, methods=['GET'])
router.add_api_websocket_route('/api/extension/ws', bridge.extension_websocket)
