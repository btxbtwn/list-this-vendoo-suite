from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation, Photo
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.listing import Listing, ListingRevision
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.models.validation import validate_listing
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services.safe_fetch import UnsafeURLError, validate_fetch_url
from vendoo_studio.services.vendoo_import import listing_from_vendoo, merge_notes


REPO = Path(__file__).resolve().parents[3]
EXTENSION_DIR = REPO / "vendoo-extension"
JPEG_BYTES = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
])

VALID_LISTING = {
    "title": "Notations XL Retro Blouse Black Relaxed",
    "description": (
        "Notations blouse with a visible XL size tag.\n\n"
        "Size: XL\n"
        "Condition: Pre-Owned - Good; no major flaws visible in photos.\n"
        "Measurements: Pit to pit: 22.5\"; Length: 27\"; Sleeve: 9\"\n\n"
        "Material tag is not shown. Garment care is unknown.\n"
        "OFFERS WELCOME! Ships in 1-2 business days."
    ),
    "price": 14,
    "brand": "Notations",
    "size": "XL",
    "sku": "NOT-XL-1",
    "weight_lb": 0,
    "weight_oz": 8,
    "package_dimensions_in": "13x10x3",
    "department": "Women",
    "condition": "Pre-Owned - Good",
    "category_path": "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
    "ebay_specifics": {
        "type": "Blouse",
        "department": "Women",
        "sizeType": "Regular",
        "size": "XL",
        "brand": "Notations",
    },
    "depop_specifics": {
        "source": "Preloved",
        "age": "Modern",
        "style": ["Casual"],
        "parcelSize": "Medium",
    },
    "etsy_specifics": {
        "who_made": "Another company or person",
        "what_is": "A finished product",
        "when_made": "",
    },
}


def _client(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    return TestClient(app)


class SafeFetchTest(unittest.TestCase):
    def test_rejects_loopback_and_file_urls(self):
        for url in (
            "http://127.0.0.1/secret.jpg",
            "http://localhost/photo.png",
            "file:///etc/passwd",
            "ftp://example.com/a.jpg",
            "http://169.254.169.254/latest/meta-data/",
        ):
            with self.assertRaises(UnsafeURLError):
                validate_fetch_url(url)

    def test_import_download_requires_https(self):
        with self.assertRaises(UnsafeURLError):
            validate_fetch_url("http://example.com/photo.jpg", allow_http=False)


class WebSocketOriginTest(unittest.TestCase):
    def test_rejects_loopback_lookalike_origins(self):
        from vendoo_studio.routes.extension import _ws_origin_allowed

        self.assertTrue(_ws_origin_allowed("http://127.0.0.1:4318"))
        self.assertTrue(_ws_origin_allowed("http://127.0.0.1:5173"))
        self.assertTrue(_ws_origin_allowed("chrome-extension://abcdefghijklmnop"))
        self.assertFalse(_ws_origin_allowed("http://127.0.0.1.evil.example:4318"))
        self.assertFalse(_ws_origin_allowed("http://localhost.evil.example:4318"))
        self.assertFalse(_ws_origin_allowed("https://web.vendoo.co"))


class PairingTokenTest(unittest.TestCase):
    def test_rejects_direct_and_writes_restricted_file(self):
        from vendoo_studio.routes.extension import ExtensionManager

        with tempfile.TemporaryDirectory() as tmp:
            pairing = Path(tmp) / "pairing_token.txt"
            with patch("vendoo_studio.routes.extension.PAIRING_FILE", str(pairing)):
                manager = ExtensionManager()
                token = manager.generate_pairing_token()
                self.assertEqual(len(token), 32)
                self.assertNotEqual(token, "direct")
                self.assertFalse(manager.verify_token("direct"))
                self.assertTrue(manager.verify_token(token))
                mode = stat.S_IMODE(pairing.stat().st_mode)
                self.assertEqual(mode, 0o600)


class ValidationCasesTest(unittest.TestCase):
    def test_missing_title_and_photos(self):
        result = validate_listing({}, 0, selected_marketplaces=["ebay"])
        fields = {err["field"] for err in result.errors}
        self.assertIn("title", fields)
        self.assertIn("photos", fields)
        self.assertFalse(result.can_send)

    def test_title_too_long_and_wrong_formula(self):
        listing = dict(VALID_LISTING)
        listing["title"] = "x" * 81
        result = validate_listing(listing, 5, selected_marketplaces=["ebay", "poshmark", "mercari", "depop"])
        self.assertTrue(any("80" in err["message"] for err in result.errors if err["field"] == "title"))
        listing["title"] = "Hello World Shirt"
        result = validate_listing(listing, 5, selected_marketplaces=["ebay", "poshmark", "mercari", "depop"])
        self.assertTrue(
            any("brand size vibe" in err["message"].lower() for err in result.errors if err["field"] == "title"),
            result.errors,
        )

    def test_modern_blouse_is_not_etsy_eligible(self):
        result = validate_listing(VALID_LISTING, 5, selected_marketplaces=["etsy"])
        self.assertFalse(result.can_send)
        self.assertTrue(any("not Etsy eligible" in err["message"] for err in result.errors))

    def test_modern_blouse_fails_etsy_without_etsy_specifics(self):
        listing = {key: value for key, value in VALID_LISTING.items() if key != "etsy_specifics"}
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertFalse(result.can_send)
        self.assertTrue(any("not Etsy eligible" in err["message"] for err in result.errors))

    def test_etsy_requires_who_what_and_when(self):
        listing = dict(VALID_LISTING)
        listing["etsy_specifics"] = {
            "who_made": "I did",
            "what_is": "",
            "when_made": "",
        }
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        fields = {err["field"] for err in result.errors}
        self.assertIn("etsy_specifics.what_is", fields)
        self.assertIn("etsy_specifics.when_made", fields)

    def test_digital_item_listing_is_etsy_eligible(self):
        listing = {
            "title": "Teal Abstract Grid Instant Download Wall Art Print Digital PNG",
            "description": (
                "Clean teal geometric grid print for modern walls.\n\n"
                "Minimal line art with a warm accent circle.\n\n"
                "Size: 1200x1500 PNG included.\n\n"
                "Instant download after purchase. No physical item will be shipped."
            ),
            "price": 4.99,
            "brand": "List This Audit",
            "sku": "AUDIT-ETSY-DIGITAL-001",
            "etsy_specifics": {
                "who_made": "I did",
                "what_is": "A finished product",
                "when_made": "2020 - 2026 (Recently)",
                "listingType": "Digital Item",
                "renewalOption": "Manual",
                "tags": ["digital download", "wall art", "printable"],
                "materials": ["digital download", "PNG"],
            },
        }
        result = validate_listing(listing, 1, selected_marketplaces=["etsy"])
        self.assertTrue(result.can_send, result.errors)
        self.assertFalse(any("not Etsy eligible" in err["message"] for err in result.errors))

    def test_supported_marketplaces_can_send_without_etsy(self):
        result = validate_listing(
            VALID_LISTING,
            5,
            selected_marketplaces=["ebay", "poshmark", "mercari", "depop"],
        )
        self.assertTrue(result.can_send)

    def test_unsupported_marketplace_is_an_error(self):
        result = validate_listing(VALID_LISTING, 5, selected_marketplaces=["facebook"])
        self.assertFalse(result.can_send)
        self.assertTrue(any("not supported" in err["message"] for err in result.errors))

    def test_invalid_depop_and_etsy_limits(self):
        listing = dict(VALID_LISTING)
        listing["depop_specifics"] = {
            "source": "Garage",
            "age": "Yesterday",
            "style": ["Casual", "Streetwear", "Retro", "Punk"],
            "material": ["Unobtanium"],
            "occasion": ["Brunch"],
            "parcelSize": "Spaceship",
            "sizeGrouping": "Petite",
        }
        listing["sizeType"] = "Regular"
        listing["etsy_specifics"] = {
            "who_made": "A factory",
            "what_is": "A mystery",
            "when_made": "Tomorrow",
            "tags": [f"t{i}" for i in range(14)],
            "materials": [f"m{i}" for i in range(11)],
        }
        result = validate_listing(listing, 5, selected_marketplaces=["depop", "etsy"])
        fields = {err["field"] for err in result.errors}
        self.assertIn("depop_specifics.source", fields)
        self.assertIn("depop_specifics.age", fields)
        self.assertIn("depop_specifics.style", fields)
        self.assertIn("depop_specifics.material", fields)
        self.assertIn("depop_specifics.occasion", fields)
        self.assertIn("depop_specifics.parcelSize", fields)
        self.assertIn("depop_specifics.sizeGrouping", fields)
        self.assertIn("etsy_specifics.who_made", fields)
        self.assertIn("etsy_specifics.tags", fields)
        self.assertIn("etsy_specifics.materials", fields)

    def test_dropdown_validation_does_not_accept_ambiguous_prefix(self):
        listing = dict(VALID_LISTING)
        listing["ebay_specifics"] = {**VALID_LISTING["ebay_specifics"], "season": "S"}
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertTrue(any(error["field"] == "ebay_specifics.season" for error in result.errors))


class ExtensionSafetySourceTest(unittest.TestCase):
    def test_existing_item_safety_check_runs_before_photo_upload(self):
        source = (EXTENSION_DIR / "background.js").read_text()
        safety = source.index("checking_draft_safety")
        upload = source.index("uploading_photos", safety)
        self.assertLess(safety, upload)
        self.assertIn("payload.options?.publish !== false", source)

        refill_start = source.index("async function runFillFields")
        refill_end = source.index("function groupFillFieldBatches", refill_start)
        refill = source[refill_start:refill_end]
        self.assertLess(refill.index("CHECK_DRAFT_SAFETY"), refill.index("groupFillFieldBatches"))

    def test_etsy_live_state_needs_explicit_draft_nav_status(self):
        source = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text()
        self.assertIn("const navConfirmsDraft =", source)
        self.assertIn("if (navConfirmsDraft)", source)
        self.assertIn("Refusing to update a published Vendoo item", source)

    def test_existing_item_preflight_fails_closed_for_live_or_missing_status(self):
        source = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text()
        start = source.index("  function marketplaceStatusIsPublished")
        end = source.index("  function marketplaceNameToId", start)
        script = source[start:end] + """
let testStatuses = {};
function scrapeMarketplaceStatusesFromDom() { return testStatuses; }
const results = [];
testStatuses = { etsy: 'LIVE' };
results.push(checkDraftSafety(['etsy']));
testStatuses = {};
results.push(checkDraftSafety(['etsy']));
testStatuses = { etsy: 'NOT LISTED' };
results.push(checkDraftSafety(['etsy']));
testStatuses = { general: 'COMPLETE' };
results.push(checkDraftSafety([]));
testStatuses = { etsy: 'PENDING' };
results.push(checkDraftSafety(['etsy']));
testStatuses = { etsy: 'DRAFT LISTING' };
results.push(checkDraftSafety(['etsy']));
console.log(JSON.stringify(results));
"""
        result = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        live, missing, draft, general_only, pending, draft_listing = json.loads(result.stdout)
        self.assertFalse(live["ok"])
        self.assertIn("published Vendoo item", live["error"])
        self.assertFalse(missing["ok"])
        self.assertIn("verify draft status", missing["error"])
        self.assertTrue(draft["ok"])
        self.assertFalse(general_only["ok"])
        self.assertFalse(pending["ok"])
        self.assertTrue(draft_listing["ok"])

    def test_invalid_dropdown_has_a_distinct_fill_status(self):
        source = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text()
        self.assertIn("status: 'invalid'", source)
        frontend = (REPO / "vendoo-studio" / "src" / "components" / "FillLogPanel.tsx").read_text()
        self.assertIn('if (entry.status === "invalid") return "invalid-dropdown";', frontend)


class ListingIntegrityRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.conv = Conversation(title="A")
        self.other = Conversation(title="B")
        self.db.add_all([self.conv, self.other])
        self.db.commit()
        self.client = _client(self.db)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_rejects_corrupt_nested_json(self):
        response = self.client.put(
            f"/api/conversations/{self.conv.id}/listing",
            json={"listing": {"title": "X", "ebay_specifics": "oops"}},
        )
        self.assertEqual(response.status_code, 422)

    def test_restore_rejects_cross_conversation_revision(self):
        listing_repo = ListingRepo(self.db)
        revision = listing_repo.save_revision(self.conv.id, {"title": "Keep"}, source="user_form")
        response = self.client.post(
            f"/api/conversations/{self.other.id}/revisions/{revision.id}/restore",
        )
        self.assertEqual(response.status_code, 404)


class JobSafetyRouteTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.conv = Conversation(title="A")
        self.other = Conversation(title="B")
        self.db.add_all([self.conv, self.other])
        self.db.commit()
        ListingRepo(self.db).save_revision(self.conv.id, VALID_LISTING, source="user_form")
        self.photo = Photo(
            conversation_id=self.conv.id,
            original_filename="a.jpg",
            stored_filename="a.jpg",
            mime_type="image/jpeg",
            size_bytes=10,
            display_order=0,
        )
        self.db.add(self.photo)
        self.db.commit()
        self.client = _client(self.db)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()

    def test_retry_requires_validation_and_one_active_job(self):
        failed = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot=VALID_LISTING,
            status="failed",
        )
        active = Job(
            conversation_id=self.other.id,
            approved_revision_id="rev2",
            listing_snapshot=VALID_LISTING,
            status="dispatched",
        )
        self.db.add_all([failed, active])
        self.db.commit()
        with patch("vendoo_studio.models.validation.get_selected_marketplaces", return_value=["ebay", "poshmark", "mercari", "depop"]):
            response = self.client.post(f"/api/jobs/{failed.id}/retry")
        self.assertEqual(response.status_code, 409)

    def test_terminal_status_is_not_overwritten(self):
        job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot=VALID_LISTING,
            status="cancelled",
        )
        self.db.add(job)
        self.db.commit()
        updated = JobRepo(self.db).update_status(job.id, "failed", error="late")
        self.assertEqual(updated.status, "cancelled")
        self.assertIsNone(updated.last_error)

    def test_merge_notes_keeps_vendoo_binding(self):
        existing = json.dumps({"vendooItemId": "abc123", "vendooUrl": "https://web.vendoo.co/app/item/abc123", "condition": "Good"})
        merged = json.loads(merge_notes(existing, {"condition": "Fair", "vendooItemId": "", "vendooUrl": ""}))
        self.assertEqual(merged["vendooItemId"], "abc123")
        self.assertEqual(merged["condition"], "Fair")


class ImportIntegrityTest(unittest.TestCase):
    def test_keeps_root_label_ids_and_names(self):
        item = {
            "itemID": "abc123",
            "labels": ["UOYZA8oYMxY5fwBzyP2Q"],
            "labelDetails": [{"id": "UOYZA8oYMxY5fwBzyP2Q", "name": "To List"}],
            "generalDetails": {
                "title": "Imported blouse",
                "description": "Size: XL\nCondition: Good\nMeasurements: 22.5",
                "price": 14,
                "primaryColor": "Multi",
                "labels": ["A19"],
            },
        }
        listing = listing_from_vendoo(item, None)
        self.assertIn("UOYZA8oYMxY5fwBzyP2Q", listing["labels"])
        self.assertIn("To List", listing["labels"])
        self.assertIn("A19", listing["labels"])
        self.assertEqual(listing["primaryColor"], "Multi")


class PhotoMimeTest(unittest.TestCase):
    def test_rejects_non_image_bytes_claiming_jpeg(self):
        from vendoo_studio.services.photos import process_bytes

        with tempfile.TemporaryDirectory() as tmp:
            with patch("vendoo_studio.services.photos.PHOTOS_DIR", tmp):
                with self.assertRaises(ValueError):
                    process_bytes(b"not-an-image", "fake.jpg", "image/jpeg")


class ExtensionRouteSafetyTest(unittest.TestCase):
    def test_rejects_item_id_new_and_requires_verification(self):
        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        self.assertIn("nonDurable.has(id.toLowerCase())", content)
        self.assertIn("VERIFY_SAVED_DRAFT", content)
        self.assertIn("Draft Listing", content)
        self.assertIn("Women > Tops & Blouses > Blouse", content)
        self.assertIn("waitForPostSaveForm", content)
        self.assertIn("nearestMarketplaceCategoryClickable", content)
        self.assertIn("findCategoryControlNearHeading", content)
        self.assertNotIn("btn.getAttribute('role') === 'category-input') continue", content)
        self.assertNotIn("token || 'direct'", background)
        self.assertNotIn("identPayload('direct'", background)
        self.assertNotIn("Draft ${job.vendoo_item_id} already exists, skipping photo upload", background)
        self.assertIn("type: 'VERIFY_SAVED_DRAFT'", background)
        self.assertIn("files: ['diagnostic-collector.js']", background)
        self.assertIn("PROHIBITED_TERMS", content)
        self.assertIn("LISTED|LIVE|ACTIVE|SOLD|PUBLISHED", content)
        self.assertIn("Another automation job is already running", background)
        self.assertIn("Another leftover field fill is already running", background)

    def test_extract_item_id_from_url_drops_route_ids(self):
        text = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        start = text.index("const NON_DURABLE_ITEM_IDS")
        end = text.index("async function findTabByDraft")
        script = text[start:end] + """
const result = {
  saved: extractItemIdFromUrl('https://web.vendoo.co/app/item/abc123'),
  created: extractItemIdFromUrl('https://web.vendoo.co/app/item/new'),
  edited: extractItemIdFromUrl('https://web.vendoo.co/app/item/edit'),
  createRoute: extractItemIdFromUrl('https://web.vendoo.co/app/item/create'),
};
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertEqual(result["saved"], "abc123")
        self.assertEqual(result["created"], "")
        self.assertEqual(result["edited"], "")
        self.assertEqual(result["createRoute"], "")

    def test_marketplace_nav_matches_status_suffix(self):
        text = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        start = text.index("function marketplaceNavBareLabel")
        end = text.index("function marketplaceSectionButtonMatches")
        script = """
function normalizeText(text) {
  return (text || '')
    .toString()
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\\s+/g, ' ')
    .trim()
    .toLowerCase();
}
""" + text[start:end] + """
const cases = [
  ['eBay', 'ebay', true],
  ['eBay NOT LISTED', 'ebay', true],
  ['eBay\\nNOT LISTED', 'ebay', true],
  ['Depop BETA', 'depop', true],
  ['List on eBay', 'ebay', false],
  ['Copy eBay title', 'ebay', false],
];
const result = cases.map(([label, platform, expected]) => ({
  label, platform, expected, actual: marketplaceNavLabelMatches(label, platform),
}));
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        for row in result:
            self.assertEqual(row["actual"], row["expected"], row)

    def test_complete_general_status_is_not_published(self):
        text = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        start = text.index("function marketplaceStatusIsPublished")
        end = text.index("function publishedMarketplaceStatuses")
        script = text[start:end] + """
const cases = [
  ['COMPLETE', false],
  ['NOT LISTED', false],
  ['DRAFT', false],
  ['LISTED', true],
  ['LIVE', true],
];
const result = cases.map(([status, expected]) => ({
  status, expected, actual: marketplaceStatusIsPublished(status),
}));
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        for row in result:
            self.assertEqual(row["actual"], row["expected"], row)


class MercariCategoryAndDepopAuditTest(unittest.TestCase):
    def test_previous_category_input_skip_misses_mercari_picker(self):
        """Regression: skipping role=category-input hid the live Mercari Category button."""
        script = r"""
function previousFind(el) {
  if (el.id === 'categoryV2' || el.getAttribute('role') === 'category-input') return false;
  const aria = String(el.getAttribute('aria-label') || '').toLowerCase();
  const text = String(el.innerText || '').toLowerCase();
  const looksNamed = aria === 'category' || text.startsWith('category');
  const looksBreadcrumb = /\bwomen\b/.test(text) && /tops|blouses|shirts|tees/.test(text);
  return looksNamed || looksBreadcrumb;
}
function currentFind(el) {
  if (el.id === 'categoryV2') return false;
  const aria = String(el.getAttribute('aria-label') || '').toLowerCase();
  const labelled = String(el.getAttribute('aria-labelledby-text') || '').toLowerCase();
  const text = String(el.innerText || '').toLowerCase();
  const role = el.getAttribute('role');
  const looksNamed = aria === 'category' || labelled === 'category' || text === 'category' || text.startsWith('category');
  const looksBreadcrumb = /\bwomen\b/.test(text) && /tops|blouses|shirts|tees/.test(text);
  return role === 'category-input' || looksNamed || looksBreadcrumb;
}
const fixture = {
  id: '',
  innerText: 'Women ‣ Tops & Blouses ‣ T-Shirts',
  getAttribute(name) {
    if (name === 'role') return 'category-input';
    if (name === 'aria-label') return 'Category';
    if (name === 'aria-labelledby-text') return 'Category';
    return '';
  },
};
const result = { previous: previousFind(fixture), current: currentFind(fixture) };
console.log(JSON.stringify(result));
"""
        proc = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertFalse(result["previous"])
        self.assertTrue(result["current"])

    def test_prefix_id_query_finds_mercari_category_label(self):
        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        self.assertIn("V2-formGroupLabel", content)
        self.assertIn("nearestMarketplaceCategoryClickable", content)

    def test_blouse_leaf_outranks_tshirts_under_tops_and_blouses(self):
        text = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        start = text.index("function escapeRegExp(value)")
        end = text.index("async function clickCategoryOption(option)")
        helpers = text[start:end]
        display_start = text.index("function categoryDisplayMatches(shown, path)")
        display_end = text.index("function queryDeepAll(selector, root)")
        script = """
function normalizeText(text) {
  return (text || '')
    .toString()
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\\s+/g, ' ')
    .trim()
    .toLowerCase();
}
""" + helpers + text[display_start:display_end] + """
const options = [
  { el: {}, text: 'Women ‣ Tops & Blouses ‣ T-Shirts', lower: normalizeText('Women ‣ Tops & Blouses ‣ T-Shirts') },
  { el: {}, text: 'Blouse', lower: normalizeText('Blouse') },
  { el: {}, text: 'Women ‣ Tops & Blouses ‣ Blouses', lower: normalizeText('Women ‣ Tops & Blouses ‣ Blouses') },
  { el: {}, text: 'Women ‣ Tops & Blouses', lower: normalizeText('Women ‣ Tops & Blouses') },
];
const ranked = rankCategorySearchResults(options, ['Women', 'Tops & Blouses', 'Blouse']);
const displayOk = categoryDisplayMatches('Women ‣ Tops & Blouses ‣ T-Shirts', 'Women > Tops & Blouses > Blouse');
const parentOk = categoryDisplayMatches('Women ‣ Tops & Blouses', 'Women > Tops & Blouses > Blouse');
const blouseOk = categoryDisplayMatches('Women ‣ Tops & Blouses ‣ Blouse', 'Women > Tops & Blouses > Blouse');
const mercariBreadcrumbOk = categoryDisplayMatches('Tops & Blouses ‣ Blouse', 'Women > Tops & Blouses > Blouse');
console.log(JSON.stringify({
  winner: ranked[0] && ranked[0].text,
  displayOk,
  parentOk,
  blouseOk,
  mercariBreadcrumbOk,
}));
"""
        proc = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertIn("Blouse", result["winner"])
        self.assertNotIn("T-Shirt", result["winner"])
        self.assertFalse(result["displayOk"])
        self.assertFalse(result["parentOk"])
        self.assertTrue(result["blouseOk"])
        self.assertTrue(result["mercariBreadcrumbOk"])

    def test_button_up_shirt_maps_to_mercari_blouses(self):
        text = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        start = text.index("function categoryHaystack(data, categoryPath)")
        end = text.index("function explicitPoshmarkCategoryPath(data)")
        hay = text[start:end]
        mercari_start = text.index("function normalizeMercariCategoryPath(data)")
        mercari_end = text.index("async function fillMarketplaceCategory(marketplace, data)")
        script = """
function normalizeText(text) {
  return (text || '')
    .toString()
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\\s+/g, ' ')
    .trim()
    .toLowerCase();
}
""" + hay + text[mercari_start:mercari_end] + """
const blouse = normalizeMercariCategoryPath({
  title: 'Notations XL Retro Short Sleeve Button-Up Shirt Black White Gray Relaxed',
  department: 'Women',
  category_path: "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
  ebay_specifics: { type: 'Blouse', department: 'Women' },
});
const tee = normalizeMercariCategoryPath({
  title: 'Graphic Tee',
  department: 'Women',
  category_path: "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
});
console.log(JSON.stringify({ blouse, tee }));
"""
        proc = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertEqual(result["blouse"], "Women > Tops & Blouses > Blouse")
        self.assertEqual(result["tee"], "Women > Tops & Blouses > T-shirts")

    def test_etsy_listing_state_live_ok_when_not_listed(self):
        content = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text(encoding="utf-8")
        self.assertIn("Unfilled Etsy sections often keep Listing State", content)
        self.assertIn("key === 'listingState' && mp === 'etsy'", content)
        self.assertIn('[aria-label^="Remove "]', content)
        self.assertIn("normalizeComparableText(lab) === normalizeComparableText(want)", content)

    def test_ask_chat_prompt_includes_field_context(self):
        panel = (
            Path(__file__).resolve().parents[2] / "src" / "components" / "FillLogPanel.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("function leftoverFieldPrompt", panel)
        self.assertIn("function leftoverFieldsPrompt", panel)
        self.assertIn("Listing:", panel)
        self.assertIn("Marketplace:", panel)
        self.assertIn("Current value:", panel)
        self.assertIn("Failure reason:", panel)
        self.assertIn("Ask chat about", panel)
        self.assertIn("Fill this field", panel)


if __name__ == "__main__":
    unittest.main()
