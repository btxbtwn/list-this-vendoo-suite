find_python() {
  local candidate resolved
  for candidate in \
    "${ROOT}/.venv/bin/python" \
    python3.13 python3.12 \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3.12 \
    /usr/local/bin/python3.13 \
    /usr/local/bin/python3.12 \
    python3
  do
    resolved=""
    if [[ -x "$candidate" ]]; then
      resolved="$candidate"
    else
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
    fi
    if [[ -n "$resolved" ]] && "$resolved" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

find_chrome() {
  local root relative candidate
  for root in "/Applications" "${HOME}/Applications"; do
    for relative in \
      "Google Chrome.app/Contents/MacOS/Google Chrome" \
      "Chromium.app/Contents/MacOS/Chromium" \
      "Brave Browser.app/Contents/MacOS/Brave Browser" \
      "Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    do
      candidate="${root}/${relative}"
      if [[ -x "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  done
  return 1
}
