"""Read-only audit collection with account/credential field redaction."""
import json
import re
import urllib.request
from pathlib import Path

root = Path(__file__).parent
sensitive = re.compile(r"token|cookie|password|secret|api.?key|authorization|email|zip.?code|postal|address|ships.?from|ship.?from|account|user.?id|shop.?id|seller.?id|billing|policy|profile|local.?information|location|shippingTemplate", re.I)
def clean(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if sensitive.search(k) else clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value if not (isinstance(v, dict) and sensitive.search(str(v.get("label", ""))))]
    if isinstance(value, str):
        value = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[REDACTED EMAIL]", value, flags=re.I)
        return re.sub(r"data:image/[^\s\"]+", "[IMAGE OMITTED]", value)
    return value
def read(path, post=False):
    req = urllib.request.Request("http://127.0.0.1:4318/api/" + path, method="POST" if post else "GET")
    return json.load(urllib.request.urlopen(req, timeout=50))
for job in ["eb8bad1d1e1f", "0093f5d1dd0f"]:
    for suffix in ["", "/events", "/fill-log"]:
        result = clean(read("jobs/" + job + suffix))
        (root / ("final-" + job + (suffix.replace("/", "-") or "-job") + ".json")).write_text(json.dumps(result, indent=2))
for conv in ["9a64e584adee", "842b7f1762be"]:
    for suffix in ["listing", "photos"]:
        (root / ("final-" + conv + "-" + suffix + ".json")).write_text(json.dumps(clean(read("conversations/" + conv + "/" + suffix)), indent=2))
draft = clean(read("jobs/eb8bad1d1e1f/vendoo-item?cache_only=true", post=True))
(root / "final-saved-draft.json").write_text(json.dumps(draft, indent=2))
print({"draft_read_ok": draft.get("ok"), "item_id": draft.get("item_id"), "source": draft.get("source"), "photo_count": len((draft.get("item") or {}).get("generalDetails", {}).get("images", []))})
print({"active_jobs": sum(j["status"] in ["queued", "dispatched", "awaiting_extension"] for j in read("jobs"))})
