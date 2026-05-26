# Extracting and Loading a Chrome Extension Unpacked

## Why
When working with the Vendoo (or any) Chrome extension source, the installed copy lives under `~/Library/Application Support/Google/Chrome/Default/Extensions/<id>/<version>/`. Copying that folder directly and choosing "Load unpacked" in `chrome://extensions/` **silently fails** because Chrome rejects Web Store-installed extensions that still carry their `_metadata` folder.

## Steps

1. Find the extension ID via Chrome or the filesystem:
   ```bash
   ls ~/Library/Application\ Support/Google/Chrome/Default/Extensions/
   ```
2. Copy the versioned folder to your workspace:
   ```bash
   cp -R "~/Library/Application Support/Google/Chrome/Default/Extensions/<id>/<version>" ~/workspace/vendoo-extension
   ```
3. **Clean the copy** before loading:
   ```bash
   cd ~/workspace/vendoo-extension && rm -rf _metadata .DS_Store
   ```
4. Load in Chrome:
   - Navigate to `chrome://extensions/`
   - Toggle **Developer mode** ON
   - Click **Load unpacked**
   - Select the cleaned folder

## Pitfalls
- `_metadata` is injected by the Chrome Web Store for update tracking and licensing. Chrome will refuse to load unpacked if it exists.
- `.DS_Store` files (macOS) won't block loading but clutter the folder.
- The extension may not show a toolbar icon; background/service-worker extensions only appear on the `chrome://extensions/` page.
- If the manifest has `"update_url": "https://clients2.google.com/service/update2/crx"`, Chrome may try to phone home for updates. This generally doesn't prevent loading but is worth noting for offline analysis.

## Quick verification
After loading, check `chrome://extensions/` for the extension name and ID. If it doesn't appear, re-check that `_metadata` was fully removed.
