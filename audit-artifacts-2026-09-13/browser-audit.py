"""Audit-only typed browser CLI; stores field refs without account values."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent
BASE = {
    "target_id": "bt-ff1b81cd-8460-4459-a1e7-8af6a1ca12ea",
    "tab_id": "tab-681b90db-a4c4-49bd-8683-c3d335644ed7",
    "session": "vendoo-audit",
}

def call(tool, **args):
    result = subprocess.run([
        "/Users/cris/.local/bin/cua-driver", "call", tool,
        json.dumps({**BASE, **args}), "--socket", "/tmp/vendoo-audit-cua.sock",
    ], capture_output=True, text=True)
    return json.loads(result.stdout)

if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "query":
        result = call("get_browser_state", snapshot_format="semantic_v2", query=sys.argv[2])
        print(json.dumps(result))
    elif mode == "navigate":
        print(json.dumps(call("browser_navigate", url=sys.argv[2])))
    elif mode == "click":
        print(json.dumps(call("browser_click", ref=sys.argv[2], input_route="dom_event")))
    elif mode == "fields":
        result = call("get_browser_state", snapshot_format="dom_refs_v1")
        fields = [x for x in result.get("refs", [])
                  if x.get("node") in {"input", "textarea", "button", "img"}
                  and not any(word in (x.get("label") or "").lower()
                              for word in ("zipcode", "account", "token", "email", "password"))]
        ROOT.joinpath("vendoo-" + sys.argv[2] + "-fields.json").write_text(json.dumps(fields, indent=2))
        print(json.dumps({"status": result.get("status"), "url": result.get("url"), "fields": fields}))
