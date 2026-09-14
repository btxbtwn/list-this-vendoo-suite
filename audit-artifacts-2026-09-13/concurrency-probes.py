"""Audit-only isolated database; no browser or live extension dispatch."""
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

root = Path(__file__).parent
with tempfile.TemporaryDirectory(prefix="vendoo-concurrency-audit-") as tmp:
    os.environ["VENDOO_STUDIO_DATA_DIR"] = tmp
    from fastapi.testclient import TestClient
    from PIL import Image
    from vendoo_studio.database import init_db
    from vendoo_studio.main import app
    init_db()
    client = TestClient(app, raise_server_exceptions=False)
    listing = json.loads((root / "approved-studio-snapshot.json").read_text())["listing"]
    data = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(data, "PNG")
    ids = []
    for name in ["Audit A", "Audit B"]:
        conv = client.post("/api/conversations", json={"title": name}).json()["id"]
        client.put(f"/api/conversations/{conv}/listing", json={"listing": listing})
        client.post(f"/api/conversations/{conv}/photos", files={"files": ("audit.png", data.getvalue(), "image/png")})
        ids.append(conv)
    results = []
    with patch("vendoo_studio.routes.extension.dispatch_queued_jobs", new=AsyncMock()):
        a = client.post("/api/jobs", json={"conversation_id": ids[0]})
        blocked = client.post("/api/jobs", json={"conversation_id": ids[1]})
        results.append({"probe": "create second active job", "first_status": a.status_code, "second_status": blocked.status_code})
        aid = a.json()["id"]
        from vendoo_studio.database import SessionLocal
        from vendoo_studio.repositories.queries import JobRepo
        with SessionLocal() as db:
            JobRepo(db).update_status(aid, "failed", current_step="opening_vendoo", error="Isolated audit simulated failure")
        b = client.post("/api/jobs", json={"conversation_id": ids[1]})
        client.put(f"/api/conversations/{ids[0]}/listing", json={"listing": {**listing, "title": ""}})
        retry = client.post(f"/api/jobs/{aid}/retry")
        jobs = client.get("/api/jobs").json()
        results.append({"probe": "retry invalid listing while another job active", "second_create_status": b.status_code, "retry_status": retry.status_code, "response": retry.json(), "active_count": sum(j["status"] in ["queued", "dispatched", "awaiting_extension"] for j in jobs)})
    (root / "concurrency-probes.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
