# Vendoo Extension Location Reference

## Purpose
Document where the Vendoo Crosslist Extension (v3) lives on this machine, and the generic path pattern for finding it on macOS Chrome.

## Extension ID on this machine

- **Extension ID:** `mnampbajndaipakjhcbbaihllmghlcdf`
- **Version:** 3.1.10
- **Name:** Vendoo Crosslist Extension v3
- **Path:** `~/Library/Application Support/Google/Chrome/Default/Extensions/mnampbajndaipakjhcbbaihllmghlcdf/3.1.10_0/`

## How to locate it

Chrome extensions on macOS are stored under:
```
~/Library/Application Support/Google/Chrome/<PROFILE>/Extensions/<EXTENSION_ID>/<VERSION>/
```

Where:
- `<PROFILE>` = `Default` or another profile name
- `<EXTENSION_ID>` = the 32-character Chrome Web Store ID
- `<VERSION>` = version folder (e.g. `3.1.10_0`)

To inspect what extensions are installed:
```bash
for ext in "$HOME/Library/Application Support/Google/Chrome/Default/Extensions/"*; do
  id=$(basename "$ext")
  for ver in "$ext"/*; do
    if [ -d "$ver" ]; then
      name=$(cat "$ver"/*.json 2>/dev/null | grep -o '"name"\s*:\s*"[^"]*"' | head -1)
      echo "$id => $name"
    fi
  done
done
```

To read the extension manifest:
```bash
cat "$HOME/Library/Application Support/Google/Chrome/Default/Extensions/mnampbajndaipakjhcbbaihllmghlcdf/3.1.10_0/manifest.json"
```

## Why this matters

- The `list-this-direct` skill purposely avoids using the Vendoo extension, but knowing it exists helps diagnose cases where Vendoo web content may behave differently (e.g., the extension injecting scripts into `web.vendoo.co`).
- Useful for cross-referencing version when debugging Vendoo UI changes.
- The `list-this` skill itself may reference this to understand what the extension populates vs what the live form exposes.
