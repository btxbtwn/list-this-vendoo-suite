"""Exercise the actual HTTP/WebSocket boundary with a deterministic assistant."""
import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.routes.extension import ExtensionManager


class Assistant:
    async def chat(self, messages, stream=True):
        yield json.dumps({"fields": [{"marketplace": "ebay", "field": "Material", "value": "Cotton",
                                       "evidence": "The tag says cotton."}]})


class CompletionTransportTest(unittest.TestCase):
    def test_saved_readback_drives_repair_and_completion_over_websocket(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        conv = ConversationRepo(db).create(title="Tee")
        ConversationRepo(db).add_message(conv.id, "user", "The tag says cotton.")
        listing = {"title": "Tee", "category_path": "Clothing > Tops", "platforms": ["ebay"]}
        revision = ListingRepo(db).save_revision(conv.id, listing, source="user")
        job = JobRepo(db).create(conv_id=conv.id, approved_revision_id=revision.id,
            listing_snapshot=listing, vendoo_item_id="draft-123", status="queued")
        job_id = job.id
        manager = ExtensionManager()

        def get_test_db():
            with Session() as session:
                yield session

        async def handshake(ws, *_):
            await ws.send_json({"type": "studio.ready"})
            return True

        verification = {"readback": True, "verified": True, "schema": {
            "general": {"category": {"path": "Clothing > Tops"}, "fields": [{"label": "Title", "value": "Tee"}]},
            "ebay": {"category": {"path": "Clothing > Shirts"}, "fields": [{"label": "Material", "value": "", "required": True}]},
        }}
        app.dependency_overrides[get_db] = get_test_db
        try:
            with patch("vendoo_studio.routes.extension.SessionLocal", Session), \
                 patch("vendoo_studio.services.listing_completion.SessionLocal", Session), \
                 patch("vendoo_studio.routes.extension.extension_manager", manager), \
                 patch.object(manager, "verify_token", return_value=True), \
                 patch("vendoo_studio.routes.extension._websocket_allowed", return_value=True), \
                 patch("vendoo_studio.routes.extension.handshake_extension", side_effect=handshake), \
                 patch("vendoo_studio.services.listing_completion.get_listing_provider", return_value=Assistant()):
                client = TestClient(app)
                with client.websocket_connect("/api/extension/ws") as ws:
                    ws.send_json({"type": "extension.ready", "payload": {"token": "test"}})
                    self.assertEqual(ws.receive_json()["type"], "studio.ready")
                    self.assertEqual(ws.receive_json()["type"], "job.start")
                    ws.send_json({"type": "job.completed", "job_id": job_id, "payload": {
                        "vendoo_item_id": "draft-123", "verification": verification,
                    }})
                    repair = ws.receive_json()
                    self.assertEqual(repair["type"], "job.fill_fields")
                    self.assertEqual(repair["payload"]["fields"][0]["value"], "Cotton")
                    self.assertEqual(repair["payload"]["platforms"], ["ebay"])
                    self.assertEqual(repair["payload"]["listing"]["ebay_specifics"]["material"], "Cotton")
                    self.assertNotEqual(client.get(f"/api/jobs/{job_id}").json()["status"], "completed")
                    verification["schema"]["ebay"]["fields"][0]["value"] = "Cotton"
                    ws.send_json({"type": "job.step_completed", "job_id": job_id, "payload": {
                        "step": "filling_fields", "vendoo_item_id": "draft-123", "verification": verification,
                    }})
                    for _ in range(100):
                        response = client.get(f"/api/jobs/{job_id}").json()
                        if response["status"] == "completed":
                            break
                        time.sleep(0.01)
                    self.assertEqual(response["current_step"], "verified_complete", response)
                    catalog = client.get("/api/catalog/categories").json()
                    self.assertFalse(catalog["complete"])
                    self.assertIn("Clothing > Tops", [node["path"] for node in catalog["nodes"]])
        finally:
            app.dependency_overrides.pop(get_db, None)
            db.close()
            engine.dispose()
