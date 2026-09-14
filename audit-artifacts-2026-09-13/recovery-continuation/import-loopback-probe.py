"""Benign SSRF probe: one local image server, disposable Studio DB, no secrets."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from PIL import Image
buf=io.BytesIO()
Image.new("RGB",(2,2),"white").save(buf,"PNG")
requests=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass
    def do_GET(self):
        requests.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type","image/png")
        self.end_headers()
        self.wfile.write(buf.getvalue())

server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True)
thread.start()
start=time.monotonic()
try:
    with tempfile.TemporaryDirectory(prefix="vendoo-import-audit-") as tmp:
        os.environ["VENDOO_STUDIO_DATA_DIR"]=tmp
        from fastapi.testclient import TestClient
        from vendoo_studio.database import init_db
        from vendoo_studio.main import app
        init_db()
        with TestClient(app,raise_server_exceptions=False) as client:
            response=client.post("/api/imports/vendoo",json={"item_id":"audit-local-only","item":{"generalDetails":{"title":"Disposable loopback audit fixture","labels":[]}},"image_urls":[f"http://127.0.0.1:{server.server_port}/audit-image.png"]})
            cid=response.json()["conversation_id"]
            settle=client.post(f"/api/conversations/{cid}/settle")
            result={"http_status":response.status_code,"photo_count":response.json().get("photo_count"),"loopback_requests":requests,
                "imported_conversation_status":client.get(f"/api/conversations/{cid}").json()["status"],
                "settle_status":settle.status_code,"settle_response":settle.json(),
                "duration_seconds":round(time.monotonic()-start,3),"scope":"Unauthenticated real import endpoint in isolated TestClient; benign local PNG only; no production or remote account request."}
            Path(__file__).with_suffix(".json").write_text(json.dumps(result,indent=2))
            print(json.dumps(result))
finally:
    server.shutdown()
    server.server_close()
    thread.join()
