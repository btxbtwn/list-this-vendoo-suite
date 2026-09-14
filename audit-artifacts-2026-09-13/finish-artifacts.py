"""Sanitize retained audit evidence and add coverage appendices; no app writes."""
import hashlib
import json
import re
import urllib.request
from pathlib import Path

root = Path(__file__).parent
repo = root.parent
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

# Remove only this audit's provisional screenshots with misleading requested-size
# names or potentially unrelated sidebar content. No original photo/user file.
removed = []
for name in ["layout-1920x1080.png", "layout-1440x900.png", "layout-1280x800.png", "layout-820x1180.png", "layout-390x844.png", "layout-820-verified.png"]:
    p = root / name
    if p.exists():
        p.unlink()
        removed.append(name)
old = root / "hidden-menu-clipped.png"
if old.exists():
    old.rename(root / "hidden-menu-working.png")
for p in root.glob("*.json"):
    try:
        p.write_text(json.dumps(clean(json.loads(p.read_text())), indent=2) + "\n")
    except json.JSONDecodeError:
        pass
for p in root.glob("*.log"):
    s = p.read_text(errors="replace")
    s = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[REDACTED EMAIL]", s, flags=re.I)
    p.write_text(s)

jobs = json.load(urllib.request.urlopen("http://127.0.0.1:4318/api/jobs"))
convs = json.load(urllib.request.urlopen("http://127.0.0.1:4318/api/conversations"))
state = {
    "active_automation_jobs": sum(j["status"] in ["queued", "dispatched", "awaiting_extension"] for j in jobs),
    "audit_conversations": [{k: c.get(k) for k in ["id", "status", "updated_at"]} for c in convs if c["id"] in ["9a64e584adee", "842b7f1762be"]],
    "removed_provisional_audit_screenshots": removed,
    "publication_observed": False,
    "note": "Primary conversation remains in_progress after cancelled chat; no active automation job.",
}
(root / "final-state.json").write_text(json.dumps(state, indent=2))

def cell(v):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    if len(s) > 190:
        s = s[:187] + "…"
    return s.replace("|", "\\|").replace("\n", "<br>")
def flatten(obj, prefix=""):
    for key, value in obj.items():
        path = prefix + key
        if isinstance(value, dict) and value:
            yield from flatten(value, path + ".")
        else:
            yield path, value

draft = json.loads((root / "final-saved-draft.json").read_text())
approved = json.loads((root / "approved-studio-snapshot.json").read_text())["listing"]
rows = ["# Saved-field evidence appendix", "", "This appendix enumerates every non-account General and selected marketplace field returned by the final independent read. It preserves raw dropdown identifiers; a raw identifier is not a verified label. Description is shortened here only; complete text remains in the JSON. The main report contains the semantic approved-versus-saved comparison.", ""]
for platform, obj in [("General", draft["item"]["generalDetails"])] + [(p, draft["item"]["listings"][p]) for p in ["ebay", "poshmark", "mercari", "depop", "etsy"]]:
    rows += [f"## {platform}", "", "| Saved field | Saved value |", "|---|---|"]
    for key, value in flatten(obj):
        if value == "[REDACTED]" or sensitive.search(key):
            continue
        rows.append(f"| `{key}` | {cell(value)} |")
    rows.append("")
rows += ["## Approved fields", "", "Every approved field is listed below; no missing field is silently counted as correct. Consult the report's platform comparison and the saved-field tables above for mapping/verification outcomes.", "", "| Approved key | Approved value |", "|---|---|"]
for key, value in flatten(approved):
    if value == "[REDACTED]" or sensitive.search(key):
        continue
    rows.append(f"| `{key}` | {cell(value)} |")
(root / "saved-field-evidence.md").write_text("\n".join(rows) + "\n")

report = repo / "FULL_SYSTEM_AUDIT.md"
text = report.read_text()
text += "\n## Appendix A — independent strict-validation cases\n\nEach case started from the approved fixture and changed one condition. These results are current-code validation, not proof that each invalid case was actually transmitted to the live extension. Accepted means the backend validator allowed it; UI focus/duplicate behavior was not exercised separately for every row.\n\n"
matrix = json.loads((root / "validation-matrix.json").read_text())
text += "| Case | Result | Errors / warnings or exception |\n|---|---|---|\n"
for x in matrix:
    name = x.get("case", x.get("name", ""))
    allowed = x.get("can_send", x.get("valid"))
    result = "EXCEPTION" if x.get("exception") else ("ACCEPTED" if allowed else "BLOCKED")
    detail = x.get("exception") or {k: x[k] for k in ["errors", "warnings"] if k in x}
    text += f"| {cell(name)} | {result} | {cell(detail)} |\n"
text += "\n## Appendix B — field-level evidence and retained artifacts\n\n"
text += "[Saved-field evidence appendix](audit-artifacts-2026-09-13/saved-field-evidence.md) enumerates General and every returned field in eBay, Poshmark, Mercari, Depop and Etsy, alongside the complete approved-key inventory. Raw dropdown IDs and unresolved labels remain explicitly unverified. The full sanitized API/form snapshot remains the authoritative detailed artifact.\n\n"
text += "Screenshots are representative, not a continuous recording. Exact-size screenshots supersede provisional native-window captures. The hidden-field menu screenshot was renamed `hidden-menu-working.png`: it showed a working menu, not clipping. Mercari's early blank brand/carrier capture is retained as a loading observation and superseded by `mercari-settled-after-save.json`.\n\n"
text += "Audit scripts only exercised disposable database state or collected read-only evidence. `oversized.jpg` is a 21 MB synthetic rejected-upload fixture, not a user photo. Original product photos were not copied into this artifact directory. Logs and JSON have account/address/policy fields redacted; no credentials are required to review them. Artifact hashes are listed in `artifact-manifest.json`.\n\n"
text += "## Appendix C — remaining acceptance work\n\nThe coverage gaps in section 14 remain open. This report must not be represented as a completed execution of every requested test. The next meaningful acceptance run requires correcting the documented workflow defects, then repeating the five-photo save/reopen comparison, all selected marketplace forms, the missing fault-injection/repair/import cases, and a separately eligible Etsy fixture. The user's instruction prohibited fixes during this audit, so no implementation work was started.\n\n"
text += "PARTIAL: A Vendoo draft was created but one or more fields or marketplace forms were incomplete or incorrect; no marketplace listing was published.\n"
report.write_text(text)

manifest = []
for p in sorted(root.iterdir()):
    if p.is_file() and p.name != "artifact-manifest.json":
        data = p.read_bytes()
        manifest.append({"file": p.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
(root / "artifact-manifest.json").write_text(json.dumps(manifest, indent=2))
print({"artifact_files": len(manifest), "active_jobs": state["active_automation_jobs"], "report_bytes": report.stat().st_size})
