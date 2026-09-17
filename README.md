# List This Vendoo Suite

[![CI](https://github.com/btxbtwn/list-this-vendoo-suite/actions/workflows/ci.yml/badge.svg)](https://github.com/btxbtwn/list-this-vendoo-suite/actions/workflows/ci.yml)

Local tools for turning product photos into marketplace listing drafts. Automation stops at saved Vendoo drafts. A person always reviews and publishes.

**List This Studio** is the app you give someone else. It is a Mac app: unzip, open, sign in, list. The Chrome extension and listing skills stay in this repo for development.

## Install on a Mac

You need **macOS 13+** and **Google Chrome**. Python is already inside the app.

1. Get `List-This-Studio-macos.zip` from https://github.com/btxbtwn/list-this-vendoo-suite/releases/tag/studio-macos, or from whoever built it.
2. Unzip it. Read **How to Open.txt**.
3. Drag **List This Studio.app** into Applications.
4. Control-click the app and choose **Open**. Click Open again if macOS warns that the developer is unidentified. You only do this once.
5. In **Settings**, sign in with ChatGPT or paste a Xiaomi MiMo API key.
6. Click **Connect Chrome**. Studio opens Vendoo in your everyday Chrome. Load the unpacked listing extension there once (`chrome://extensions/` → Developer mode → Load unpacked; zip users pick `~/Library/Application Support/List This Studio/vendoo-extension`), then sign in to Vendoo.

Listings and photos stay on that Mac in `~/Library/Application Support/List This Studio`.

## Run from this repo

```bash
./setup.sh
./start.sh
```

That installs Python and Node packages for Studio, then opens http://127.0.0.1:5173. Use `vendoo-studio/scripts/doctor.sh` if anything is missing.

Requirements: macOS, Python 3.12+, Node.js 20+, Google Chrome.

## What's in the repo

| Path | Role |
|---|---|
| `vendoo-studio/` | List This Studio (FastAPI + React). See `vendoo-studio/README.md`. |
| `vendoo-extension/` | Chrome MV3 extension. **Connect Chrome** opens everyday Chrome; load this folder unpacked there once. |
| `skills/list-this/` | Canonical listing rules used by Studio. |

## Manual extension fallback

If the Studio window does not have the extension yet, load unpacked from `vendoo-extension/` in `chrome://extensions/` (Developer mode → Load unpacked). Paste listing JSON into the popup and fill a Vendoo draft. Prefer Studio when you can; it owns photos, chat, and the fill job.

## JSON contract

Studio and the extension share this payload. `ebay_specifics` keys must use these names.

```json
{
  "title": "Vintage Levi's Denim Jacket 90s",
  "description": "Classic Levi's denim jacket...",
  "price": 45.00,
  "brand": "Levi's",
  "size": "M",
  "condition": "Good",
  "category": "Clothing > Jackets",
  "color": "Blue",
  "sku": "DENIM-001",
  "quantity": 1,
  "weight_lb": 0,
  "weight_oz": 8,
  "package_dimensions_in": "13x10x3",
  "images": ["..."],
  "ebay_specifics": {
    "type": "T-Shirt",
    "department": "Men",
    "sizeType": "Regular",
    "size": "M",
    "brand": "Levi's",
    "fit": "Regular",
    "material": "Cotton",
    "pattern": "Solid",
    "style": "Basic",
    "features": "All Seasons",
    "neckline": "Crew Neck",
    "closure": "Pullover",
    "countryOfOrigin": "United States",
    "fabricType": "Jersey",
    "garmentCare": "Machine Wash",
    "handmade": "No",
    "personalize": "No",
    "vintage": "No",
    "occasion": "Casual",
    "season": "Summer",
    "unitQuantity": "1",
    "unitType": "Unit"
  },
  "depop_specifics": {},
  "etsy_specifics": {},
  "poshmark_specifics": {}
}
```

These five eBay fields are commonly skipped and must be present: **Features**, **Neckline**, **Season**, **Unit Quantity**, **Unit Type**.

## Build a zip to share

```bash
cd vendoo-studio
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[package]"
./scripts/package-macos-app.sh
```

That writes `vendoo-studio/release/List-This-Studio-macos.zip`. Publish it with `./scripts/publish-macos-release.sh`.

## Development

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for PR checks and [`AGENTS.md`](AGENTS.md) for product invariants.

CI on pull requests and `main` lints, tests, and builds Studio, lints and tests the backend, syntax-checks and unit-tests the extension, validates skill JSON, and scans the tree for secrets. The macOS app is packaged separately by `.github/workflows/studio-macos.yml`.
