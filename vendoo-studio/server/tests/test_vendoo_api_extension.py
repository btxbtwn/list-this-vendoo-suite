"""Run the extension's Vendoo API executor in Node with stubbed fetch and tabs."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

EXTENSION = Path(__file__).resolve().parents[3] / "vendoo-extension"
MODULE = EXTENSION / "background" / "vendoo-api.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(%(module)r, 'utf8');
const sent = [];
const fetches = [];
const session = %(session)s;
globalThis.send = (m) => sent.push(m);
globalThis.findVisibleVendooTab = async () => ({ id: 7 });
globalThis.openVisibleVendooWindow = async () => ({ tabId: 7 });
globalThis.waitForTabComplete = async () => true;
globalThis.chrome = { scripting: { executeScript: async () => [{ result: session }] } };
globalThis.fetch = async (url, init) => {
  const record = { url: String(url), method: (init && init.method) || 'GET', headers: init && init.headers ? { ...init.headers } : {} };
  if (init && typeof init.body === 'string') record.body = init.body;
  else if (init && init.body instanceof URLSearchParams) record.body = init.body.toString();
  else if (init && init.body && init.body.size !== undefined) record.blob = init.body.size;
  else if (init && init.body) record.body = String(init.body);
  fetches.push(record);
  const u = String(url);
  if (u.includes('securetoken')) return new Response(JSON.stringify({ id_token: 'fresh', refresh_token: 'r2', expires_in: '3600' }), { status: 200 });
  if (u.includes('/inventory/v1/images/url')) return new Response(JSON.stringify({ url: 'https://storage/put/1', imagePath: 'images/u1/x.jpg' }), { status: 200 });
  if (u.includes('/photos/')) return new Response(new Uint8Array([1, 2, 3, 4]), { status: 200, headers: { 'content-type': 'image/jpeg' } });
  if (u.startsWith('https://storage/put/')) return new Response('', { status: 200 });
  if (u.includes('/subscription/details')) return new Response(JSON.stringify({ fields: { version: { stringValue: 'v2' } } }), { status: 200 });
  if (u.includes('cloudfunctions.net/items')) return new Response(JSON.stringify({ result: { ok: true } }), { status: 200 });
  if (u.includes('/api/item/')) return new Response(JSON.stringify({ item: { itemID: 'abc', generalDetails: { title: 'T' } } }), { status: 200 });
  if (u.includes('/api/category/search')) return new Response(JSON.stringify({ hits: { hits: [{ _source: { id: 'c1', is_leaf: false } }, { _source: { id: 'c2', is_leaf: true } }] } }), { status: 200 });
  return new Response('{"error":{"message":"nope"}}', { status: 500 });
};
eval(src);
(async () => {
  const msg = { type: 'job.vendoo_api', job_id: 'job-1', payload: { request_id: 'r1', ops: %(ops)s } };
  await handleVendooApiMessage(msg);
  process.stdout.write(JSON.stringify({ sent, fetches }));
})();
"""

FRESH = {"ok": True, "uid": "u1", "email": "a@b", "api_key": "K", "access_token": "tok", "refresh_token": "r1",
         "expiration_time": 4102444800000}
STALE = {**FRESH, "expiration_time": 0}


def run_node(ops, session=FRESH) -> dict:
    script = HARNESS % {"module": str(MODULE), "ops": json.dumps(ops), "session": json.dumps(session)}
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


class VendooApiExtensionTest(unittest.TestCase):
    def test_full_create_sequence(self):
        out = run_node([
            {"op": "session"}, {"op": "new_item_id"}, {"op": "subscription"},
            {"op": "upload_photo", "photo": {"id": "p1", "url": "http://127.0.0.1:4318/api/jobs/j/photos/p1", "mime_type": "image/jpeg", "extension": "jpg", "max_dimension": 1600}},
            {"op": "create_item", "item": {"itemID": "x"}, "subscription_version": "v2"},
            {"op": "get_item", "item_id": "abc"},
        ])
        reply = out["sent"][0]
        self.assertEqual(reply["type"], "job.vendoo_api_result")
        self.assertEqual(reply["message_id"], "r1")
        self.assertEqual(reply["job_id"], "job-1")
        payload = reply["payload"]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["uid"], "u1")
        results = payload["results"]
        self.assertEqual([r["op"] for r in results], ["session", "new_item_id", "subscription", "upload_photo", "create_item", "get_item"])
        self.assertEqual(len(results[1]["item_id"]), 20)
        self.assertRegex(results[1]["item_id"], r"^[A-Za-z0-9]{20}$")
        self.assertEqual(results[2]["version"], "v2")
        self.assertEqual(results[3]["image"], {"version": 3, "id": "images/u1/x.jpg", "originalMaxDimension": 1600})
        self.assertEqual(results[5]["item"]["itemID"], "abc")

        slot = next(f for f in out["fetches"] if "/inventory/v1/images/url" in f["url"])
        self.assertEqual(slot["method"], "POST")
        self.assertEqual(slot["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(json.loads(slot["body"]), {"fileExtension": "jpg"})
        put = next(f for f in out["fetches"] if f["url"].startswith("https://storage/put/"))
        self.assertEqual(put["method"], "PUT")
        self.assertEqual(put["blob"], 4)
        self.assertEqual(put["headers"]["Content-Type"], "image/jpeg")
        create = next(f for f in out["fetches"] if "cloudfunctions.net/items" in f["url"])
        self.assertEqual(create["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(json.loads(create["body"]), {"data": {"type": "createItem", "payload": {"item": {"itemID": "x"}, "subscriptionVersion": "v2"}}})
        get_item = next(f for f in out["fetches"] if "/api/item/abc" in f["url"])
        self.assertIn("userId=u1", get_item["url"])
        self.assertNotIn("securetoken", " ".join(f["url"] for f in out["fetches"]))

    def test_stale_token_is_refreshed_first(self):
        out = run_node([{"op": "session"}], session=STALE)
        refresh = out["fetches"][0]
        self.assertIn("securetoken.googleapis.com/v1/token?key=K", refresh["url"])
        self.assertIn("grant_type=refresh_token", refresh["body"])
        self.assertTrue(out["sent"][0]["payload"]["ok"])

    def test_category_search_picks_leaf(self):
        out = run_node([{"op": "category_search", "text": "jeans", "marketplace_id": "poshmark"}])
        result = out["sent"][0]["payload"]["results"][0]
        self.assertEqual(result["leaf"], {"id": "c2", "is_leaf": True})
        self.assertEqual(len(result["matches"]), 2)
        search = out["fetches"][-1]
        self.assertEqual(json.loads(search["body"])["marketplace_id"], "poshmark")

    def test_failure_stops_the_sequence(self):
        out = run_node([{"op": "nope"}, {"op": "new_item_id"}])
        payload = out["sent"][0]["payload"]
        self.assertFalse(payload["ok"])
        self.assertEqual(len(payload["results"]), 1)
        self.assertIn("Unknown Vendoo API op", payload["results"][0]["error"])

    def test_signed_out_session_is_an_error(self):
        out = run_node([{"op": "session"}], session={"ok": False, "error": "Not signed in to Vendoo in this Chrome profile"})
        payload = out["sent"][0]["payload"]
        self.assertFalse(payload["ok"])
        self.assertIn("Not signed in", payload["error"])

    def test_background_dispatches_message(self):
        background = (EXTENSION / "background.js").read_text()
        self.assertIn("case 'job.vendoo_api':", background)
        self.assertIn("importScripts('background/vendoo-api.js');", background)


if __name__ == "__main__":
    unittest.main()
