"""Audit observations only: disposable DB, stub provider, no live browser/socket."""
import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import AsyncMock, patch

root = Path(__file__).parent
results = []
started = time.monotonic()

class Provider:
    name = "audit-stub"
    listing_model = "audit-stub"
    def __init__(self, mode):
        self.mode = mode
    async def analyze_photos(self, paths, **kwargs):
        return {"evidence":{"brand":"Audit","size":"XL","category":"Women's blouse","condition":"Good"}}
    async def chat(self, messages, stream=True):
        if self.mode == "unavailable":
            raise ConnectionError("Audit simulated provider unavailable")
        if self.mode == "timeout":
            raise TimeoutError("Audit simulated provider timeout")
        if self.mode == "malformed":
            yield '```json\n{"title":\n```'
        if self.mode == "empty":
            return
        if self.mode == "partial_then_error":
            yield "Partial audit response."
            raise ConnectionError("Audit simulated connection interruption")

with tempfile.TemporaryDirectory(prefix="vendoo-recovery-audit-") as tmp:
    os.environ["VENDOO_STUDIO_DATA_DIR"] = tmp
    from fastapi.testclient import TestClient
    from vendoo_studio.database import init_db, SessionLocal
    from vendoo_studio.main import app
    from vendoo_studio.repositories.queries import ConversationRepo, JobRepo
    init_db()
    baseline = json.loads((root.parent / "approved-studio-snapshot.json").read_text())["listing"]
    with TestClient(app, raise_server_exceptions=False) as client:
        for mode in ["unavailable", "timeout", "empty", "malformed", "partial_then_error"]:
            cid = client.post("/api/conversations", json={"title": "Audit " + mode}).json()["id"]
            client.put(f"/api/conversations/{cid}/listing", json={"listing": baseline})
            before = client.get(f"/api/conversations/{cid}/listing").json()
            t = time.monotonic()
            with patch("vendoo_studio.routes.chat.get_listing_provider", return_value=Provider(mode)), patch("vendoo_studio.routes.chat._apply_listing_payload_with_repair", new=AsyncMock(return_value=None)), patch("vendoo_studio.routes.chat._maybe_resolve_vendoo_category", new=AsyncMock()):
                response = client.post(f"/api/conversations/{cid}/messages", json={"text": "Preserve this audit prompt: " + mode})
            after = client.get(f"/api/conversations/{cid}/listing").json()
            messages = client.get(f"/api/conversations/{cid}/messages").json()
            results.append({"probe": "Ask Chat " + mode, "http_status": response.status_code,
                "stream": response.text, "duration_seconds": round(time.monotonic()-t, 3),
                "prompt_persisted": any(m["role"] == "user" and mode in m["text"] for m in messages),
                "assistant_messages": [m["text"] for m in messages if m["role"] == "assistant"],
                "listing_unchanged": before["listing"] == after["listing"],
                "revision_unchanged": before["current_revision_id"] == after["current_revision_id"],
                "final_status": client.get(f"/api/conversations/{cid}").json()["status"],
                "scope": "Real streaming route; provider stub; JSON repair/category side effects disabled."})

        from PIL import Image
        img=io.BytesIO()
        Image.new("RGB",(2,2),"white").save(img,"PNG")
        for mode in ["unavailable","timeout","empty","malformed"]:
            cid=client.post("/api/conversations",json={"title":"Audit generation "+mode}).json()["id"]
            client.put(f"/api/conversations/{cid}/listing",json={"listing":baseline})
            client.post(f"/api/conversations/{cid}/photos",files={"files":("audit.png",img.getvalue(),"image/png")})
            before=client.get(f"/api/conversations/{cid}/listing").json()
            with patch("vendoo_studio.routes.chat.get_listing_provider",return_value=Provider(mode)), patch("vendoo_studio.routes.chat.comps_search_available",return_value=False), patch("vendoo_studio.services.schema_probe.kickoff_schema_probe",new=AsyncMock()):
                response=client.post(f"/api/conversations/{cid}/generate")
            after=client.get(f"/api/conversations/{cid}/listing").json()
            results.append({"probe":"Generate "+mode,"http_status":response.status_code,"stream":response.text,
                "listing_unchanged":before["listing"]==after["listing"],
                "revision_unchanged":before["current_revision_id"]==after["current_revision_id"],
                "photos_preserved":len(client.get(f"/api/conversations/{cid}/photos").json())==1,
                "final_status":client.get(f"/api/conversations/{cid}").json()["status"],
                "scope":"Real generation and JSON repair code; provider stub; comp network and browser kickoff disabled."})

        cid = client.post("/api/conversations", json={"title":"Audit stale notes", "notes":json.dumps({"condition":"Good","pitToPit":22.5})}).json()["id"]
        stale = client.get(f"/api/conversations/{cid}").json()["notes"]
        binding = {**json.loads(stale), "vendooItemId":"audit-existing-draft", "vendooUrl":"https://web.vendoo.co/app/item/audit-existing-draft"}
        client.patch(f"/api/conversations/{cid}", json={"notes":json.dumps(binding)})
        client.patch(f"/api/conversations/{cid}", json={"notes":json.dumps({**json.loads(stale),"length":27})})
        final = json.loads(client.get(f"/api/conversations/{cid}").json()["notes"])
        results.append({"probe":"stale seller autosave after draft binding", "draft_binding_survives": "vendooItemId" in final, "final_keys": list(final), "scope":"Two clients represented by captured old and new notes through real PATCH route."})

        with SessionLocal() as db:
            repo=JobRepo(db)
            for state in ["dispatched", "cancelled", "completed", "failed"]:
                job=repo.create(conv_id=cid,approved_revision_id="audit-revision",listing_snapshot=baseline,
                    vendoo_item_id="audit-existing-draft",vendoo_url="https://web.vendoo.co/app/item/audit-existing-draft",
                    status=state,current_step="saving_general")
                before=json.loads(json.dumps(job.listing_snapshot))
                repo.requeue_interrupted()
                db.refresh(job)
                results.append({"probe":"restart reconciliation "+state,"final_status":job.status,
                    "final_step":job.current_step,"binding_preserved":job.vendoo_item_id=="audit-existing-draft",
                    "snapshot_preserved":job.listing_snapshot==before,
                    "scope":"Real repository reconciliation in disposable DB; no Chrome restart or remote send."})

root.joinpath("recovery-probes.json").write_text(json.dumps({"duration_seconds":round(time.monotonic()-started,3),"observations":results},indent=2))
print(json.dumps(results,indent=2))
