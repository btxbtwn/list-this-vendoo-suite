#!/bin/bash
set -euo pipefail

readonly HTTPS_PORT=8445
readonly TARGET='http://127.0.0.1:5173'

for command in tailscale python3 curl; do
  command -v "$command" >/dev/null 2>&1 || { echo "Required command not found: $command" >&2; exit 1; }
done

HOST="$(python3 -c '
import json, subprocess, sys
raw = subprocess.check_output(["tailscale", "status", "--json"], text=True)
name = str((json.loads(raw).get("Self") or {}).get("DNSName") or "").rstrip(".")
if not name:
    raise SystemExit("Could not read this machine Tailscale DNS name. Is Tailscale logged in?")
print(name)
')"
export BACKGROUND_STUDIO_TAILNET_HOST="$HOST"

health_json="$(curl --silent --show-error --fail --max-time 3 "$TARGET/api/health" || true)"
if ! python3 -c '
import json, sys
try:
    health = json.load(sys.stdin)
except (json.JSONDecodeError, TypeError):
    raise SystemExit(1)
if health.get("ok") is not True or not isinstance(health.get("jobs"), int) or not isinstance(health.get("disk_bytes"), int):
    raise SystemExit(1)
' <<<"$health_json"; then
  echo "Background Studio must already be listening at $TARGET; its /api/health response was missing or invalid." >&2
  exit 1
fi

status_json="$(tailscale serve status --json)"
route_state="$(python3 -c '
import json, os, sys
config = json.load(sys.stdin)
port, host, target = "8445", os.environ["BACKGROUND_STUDIO_TAILNET_HOST"], "http://127.0.0.1:5173"
tcp = config.get("TCP", {}).get(port)
web = config.get("Web", {}).get(f"{host}:{port}")
allow_funnel = config.get("AllowFunnel", {})
funnel_enabled = isinstance(allow_funnel, dict) and bool(allow_funnel.get(f"{host}:{port}"))
if funnel_enabled:
    print("funnel")
elif tcp is None and web is None:
    print("free")
elif tcp == {"HTTPS": True} and web == {"Handlers": {"/": {"Proxy": target}}}:
    print("configured")
else:
    print("conflict")
' <<<"$status_json")"

case "$route_state" in
  configured)
    echo "Private Serve route is already configured: https://$HOST:$HTTPS_PORT"
    exit 0
    ;;
  conflict)
    echo "Refusing to replace the existing Tailscale Serve configuration on HTTPS port $HTTPS_PORT." >&2
    echo "Inspect it with: tailscale serve status" >&2
    exit 1
    ;;
  funnel)
    echo "Refusing to use HTTPS port $HTTPS_PORT because Tailscale Funnel is enabled for this route." >&2
    echo "Disable Funnel for this specific route, then run this helper again." >&2
    exit 1
    ;;
  free) ;;
  *) echo "Could not interpret Tailscale Serve status." >&2; exit 1 ;;
esac

tailscale serve --bg --https "$HTTPS_PORT" "$TARGET"

updated_json="$(tailscale serve status --json)"
python3 -c '
import json, os, sys
config = json.load(sys.stdin)
host = os.environ["BACKGROUND_STUDIO_TAILNET_HOST"]
expected = {"Handlers": {"/": {"Proxy": "http://127.0.0.1:5173"}}}
allow_funnel = config.get("AllowFunnel", {})
funnel_enabled = isinstance(allow_funnel, dict) and bool(allow_funnel.get(f"{host}:8445"))
if funnel_enabled or config.get("TCP", {}).get("8445") != {"HTTPS": True} or config.get("Web", {}).get(f"{host}:8445") != expected:
    raise SystemExit("Tailscale reported success but the expected route was not present.")
' <<<"$updated_json"

echo "Private Serve route ready: https://$HOST:$HTTPS_PORT"
