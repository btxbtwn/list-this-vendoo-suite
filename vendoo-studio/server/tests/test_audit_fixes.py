from __future__ import annotations

import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db
from vendoo_studio.main import app
from vendoo_studio.models.conversation import Conversation, Photo
from vendoo_studio.models.fill_log import FillLogEntry  # noqa: F401
from vendoo_studio.models.job import Job
from vendoo_studio.models.registry import FieldRegistry  # noqa: F401
from vendoo_studio.models.validation import validate_listing
from vendoo_studio.repositories.queries import JobRepo, ListingRepo
from vendoo_studio.services.safe_fetch import UnsafeURLError, validate_fetch_url
from vendoo_studio.services.vendoo_import import listing_from_vendoo, merge_notes
from extension_sources import background_source


REPO = Path(__file__).resolve().parents[3]
EXTENSION_DIR = REPO / "vendoo-extension"
JPEG_BYTES = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xD9,
])

VALID_LISTING = {
    "title": "Notations XL Retro Blouse Black Relaxed",
    "description": (
        "Retro Notations blouse, relaxed fit.\n\n"
        "Flaws: none noted. See photos for details.\n\n"
        "Measurements: Pit to pit: 22.5\"; Length: 27\"; Sleeve: 9\""
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
            "http://[::ffff:127.0.0.1]/secret.jpg",
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
        result = validate_listing(dict(VALID_LISTING), 5, selected_marketplaces=["etsy"])
        self.assertFalse(result.can_send)
        self.assertTrue(any("not Etsy eligible" in item["message"] for item in result.warnings + result.errors))

    def test_modern_blouse_fails_etsy_without_etsy_specifics(self):
        listing = {key: value for key, value in VALID_LISTING.items() if key != "etsy_specifics"}
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertFalse(result.can_send)
        self.assertTrue(any("not Etsy eligible" in item["message"] for item in result.warnings + result.errors))

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

    def test_empty_string_cost_and_weight_are_treated_as_missing(self):
        listing = dict(VALID_LISTING)
        listing["cost"] = ""
        listing["weight_lb"] = ""
        listing["weight_oz"] = ""
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        messages = [err["message"] for err in result.errors]
        self.assertFalse(any("unable to parse" in msg.lower() for msg in messages), messages)
        self.assertTrue(any("Weight is required" in msg for msg in messages), messages)

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
        # parcelSize is not listed: the packaged weight overwrites whatever the model picked.
        self.assertIn("depop_specifics.sizeGrouping", fields)
        self.assertIn("etsy_specifics.who_made", fields)
        self.assertIn("etsy_specifics.tags", fields)
        self.assertIn("etsy_specifics.materials", fields)

    def test_dropdown_validation_does_not_accept_ambiguous_prefix(self):
        listing = dict(VALID_LISTING)
        listing["ebay_specifics"] = {**VALID_LISTING["ebay_specifics"], "season": "S"}
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertTrue(any(error["field"] == "ebay_specifics.season" for error in result.errors))

    def test_ebay_season_does_not_apply_infers_one_season(self):
        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = dict(VALID_LISTING)
        listing["description"] = (
            "Y2K floral ruched blouse, lightweight satin fit.\n\n"
            "Flaws: none noted. See photos for details.\n\n"
            "Measurements: Pit to pit: 18\""
        )
        listing["ebay_specifics"] = {
            **VALID_LISTING["ebay_specifics"],
            "type": "Blouse",
            "season": "Does Not Apply",
        }
        self.assertTrue(normalize_listing_dropdowns(listing))
        self.assertEqual(listing["ebay_specifics"]["season"], "Spring")
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertFalse(any(error["field"] == "ebay_specifics.season" for error in result.errors))
        self.assertTrue(result.can_send, result.errors)

    def test_ebay_season_does_not_apply_list_infers_one_season(self):
        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = dict(VALID_LISTING)
        listing["description"] = (
            "Heavy wool cable knit sweater, warm winter layer.\n\n"
            "Flaws: none noted. See photos for details.\n\n"
            "Measurements: Pit to pit: 22\""
        )
        listing["ebay_specifics"] = {
            **VALID_LISTING["ebay_specifics"],
            "type": "Sweater",
            "material": "Wool",
            "season": ["Does Not Apply"],
        }
        self.assertTrue(normalize_listing_dropdowns(listing))
        self.assertEqual(listing["ebay_specifics"]["season"], "Winter")
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertFalse(any(error["field"] == "ebay_specifics.season" for error in result.errors))
        self.assertTrue(result.can_send, result.errors)

    def test_ebay_missing_season_infers_from_item(self):
        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = dict(VALID_LISTING)
        listing["description"] = (
            "Linen tank for beach summer wear, sleeveless light fit.\n\n"
            "Flaws: none noted. See photos for details.\n\n"
            "Measurements: Pit to pit: 18\""
        )
        listing["ebay_specifics"] = {**VALID_LISTING["ebay_specifics"], "type": "Tank"}
        listing["ebay_specifics"].pop("season", None)
        self.assertTrue(normalize_listing_dropdowns(listing))
        self.assertEqual(listing["ebay_specifics"]["season"], "Summer")
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertFalse(any(error["field"] == "ebay_specifics.season" for error in result.errors))
        self.assertTrue(result.can_send, result.errors)

    def test_ebay_multi_season_chips_are_allowed(self):
        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = dict(VALID_LISTING)
        listing["ebay_specifics"] = {**VALID_LISTING["ebay_specifics"], "season": ["Spring", "Summer"]}
        normalize_listing_dropdowns(listing)
        self.assertEqual(listing["ebay_specifics"]["season"], ["Spring", "Summer"])
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertFalse(any(error["field"] == "ebay_specifics.season" for error in result.errors))
        self.assertTrue(result.can_send, result.errors)

    def test_case_variant_specifics_keys_are_healed(self):
        import copy

        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = copy.deepcopy(VALID_LISTING)
        # Written by an older gap fill that lower-cased the JSON key.
        listing["ebay_specifics"].pop("sizeType")
        listing["ebay_specifics"]["sizetype"] = "Regular"
        listing["depop_specifics"]["parcel_size"] = listing["depop_specifics"].pop("parcelSize")
        self.assertTrue(normalize_listing_dropdowns(listing))
        self.assertEqual(listing["ebay_specifics"]["sizeType"], "Regular")
        self.assertNotIn("sizetype", listing["ebay_specifics"])
        # 8 oz packaged — the weight picks the tier, not the stored value.
        self.assertEqual(listing["depop_specifics"]["parcelSize"], "Small")
        self.assertNotIn("parcel_size", listing["depop_specifics"])
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertFalse(
            [err for err in result.errors if err["field"] == "ebay_specifics.sizeType"],
            result.errors,
        )

    def test_required_ebay_keys_promote_out_of_category_specifics(self):
        import copy

        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = copy.deepcopy(VALID_LISTING)
        size_type = listing["ebay_specifics"].pop("sizeType")
        listing["ebay_specifics"]["category_specifics"] = {"sizeType": size_type}
        self.assertTrue(normalize_listing_dropdowns(listing))
        self.assertEqual(listing["ebay_specifics"]["sizeType"], "Regular")

    def test_unknown_specifics_keys_are_left_alone(self):
        import copy

        from vendoo_studio.models.validation import canonicalize_listing_keys

        listing = copy.deepcopy(VALID_LISTING)
        listing["ebay_specifics"]["somethingCustom"] = "keep"
        listing["ebay_specifics"]["53159_Size Type"] = "Regular"
        canonicalize_listing_keys(listing)
        self.assertEqual(listing["ebay_specifics"]["somethingCustom"], "keep")
        self.assertEqual(listing["ebay_specifics"]["sizeType"], "Regular")

    def test_ebay_category_optionals_are_filled_or_dna(self):
        from vendoo_studio.models.listing_values import DNA_VALUE
        from vendoo_studio.models.ebay_fields import ensure_ebay_category_optionals
        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = dict(VALID_LISTING)
        listing["title"] = "Notations XL Floral Blouse Pink Regular"
        listing["ebay_specifics"] = {**VALID_LISTING["ebay_specifics"]}
        self.assertTrue(ensure_ebay_category_optionals(listing))
        ebay = listing["ebay_specifics"]
        self.assertEqual(ebay["handmade"], "No")
        self.assertEqual(ebay["personalize"], "No")
        self.assertEqual(ebay["unitQuantity"], "1")
        self.assertEqual(ebay["unitType"], "Unit")
        self.assertEqual(ebay["season"], "Spring")
        self.assertEqual(ebay["mpn"], DNA_VALUE)
        self.assertEqual(ebay["upc"], DNA_VALUE)
        self.assertEqual(ebay["character"], DNA_VALUE)
        self.assertNotEqual(str(ebay.get("features") or "").strip(), "")
        self.assertNotEqual(str(ebay.get("neckline") or "").strip(), "")
        # DNA must not be used for must-fill apparel attributes.
        self.assertNotEqual(str(ebay.get("fit") or "").casefold(), DNA_VALUE.casefold())
        normalize_listing_dropdowns(listing)
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        optional_errors = [
            err for err in result.errors
            if str(err.get("field") or "").startswith("ebay_specifics.")
            and err["field"] not in {"ebay_specifics.material", "ebay_specifics.garmentCare", "ebay_specifics.fabricType"}
        ]
        self.assertFalse(optional_errors, optional_errors)
        self.assertTrue(result.can_send, result.errors)

    def test_ebay_optional_rejects_dna_for_must_fill(self):
        listing = dict(VALID_LISTING)
        listing["ebay_specifics"] = {
            **VALID_LISTING["ebay_specifics"],
            "season": "Summer",
            "fit": "Does Not Apply",
            "handmade": "No",
            "personalize": "No",
            "unitQuantity": "1",
            "unitType": "Unit",
            "pattern": "Solid",
            "occasion": "Casual",
            "style": "Basic",
            "closure": "Pullover",
            "neckline": "Crew Neck",
            "features": "Lightweight",
            "sleeveLength": "Short Sleeve",
            "vintage": "No",
            "mpn": "Does Not Apply",
            "upc": "Does Not Apply",
            "character": "Does Not Apply",
            "accents": "Does Not Apply",
            "theme": "Does Not Apply",
            "strapType": "Does Not Apply",
            "fabricWeight": "Does Not Apply",
            "countryOfOrigin": "Does Not Apply",
            "sleeveType": "Does Not Apply",
        }
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertTrue(
            any(error["field"] == "ebay_specifics.fit" for error in result.errors),
            result.errors,
        )

    def test_etsy_category_optionals_are_filled_or_dna(self):
        from vendoo_studio.models.listing_values import DNA_VALUE
        from vendoo_studio.models.etsy_fields import ensure_etsy_category_optionals

        listing = dict(VALID_LISTING)
        listing["title"] = "Notations XL Floral Blouse Pink Regular"
        listing["etsy_specifics"] = {
            **VALID_LISTING["etsy_specifics"],
            "when_made": "2010 - 2019 (Recently)",
        }
        self.assertTrue(ensure_etsy_category_optionals(listing))
        etsy = listing["etsy_specifics"]
        self.assertEqual(etsy["clothingStyle"], "Minimalist")
        self.assertEqual(etsy["neckline"], "Crew")
        self.assertEqual(etsy["closure"], "Pullover")
        self.assertEqual(etsy["fabricPattern"], "Solid")
        self.assertEqual(etsy["sleeveLength"], "Short sleeve")
        self.assertEqual(etsy["holiday"], DNA_VALUE)
        self.assertEqual(etsy["occasion"], DNA_VALUE)
        self.assertEqual(etsy["graphic"], DNA_VALUE)
        self.assertEqual(etsy["sustainability"], DNA_VALUE)
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        optional_errors = [
            err for err in result.errors
            if str(err.get("field") or "").startswith("etsy_specifics.")
            and err["field"] not in {
                "etsy_specifics.who_made",
                "etsy_specifics.what_is",
                "etsy_specifics.when_made",
            }
        ]
        self.assertFalse(optional_errors, optional_errors)

    def test_etsy_optional_rejects_dna_for_must_fill(self):
        listing = dict(VALID_LISTING)
        listing["etsy_specifics"] = {
            **VALID_LISTING["etsy_specifics"],
            "when_made": "2010 - 2019 (Recently)",
            "clothingStyle": "Does Not Apply",
            "sleeveLength": "Short sleeve",
            "neckline": "Crew",
            "closure": "Pullover",
            "fabricPattern": "Solid",
            "pattern": "Solid",
            "graphic": "Does Not Apply",
            "holiday": "Does Not Apply",
            "occasion": "Does Not Apply",
            "collarStyle": "Does Not Apply",
            "sustainability": "Does Not Apply",
        }
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertTrue(
            any(error["field"] == "etsy_specifics.clothingStyle" for error in result.errors),
            result.errors,
        )

    def test_depop_category_optionals_are_filled(self):
        from vendoo_studio.models.depop_fields import ensure_depop_category_optionals

        listing = dict(VALID_LISTING)
        listing["sizeType"] = "Regular"
        listing["depop_specifics"] = {
            "source": "Preloved",
            "age": "Modern",
            "style": ["Casual"],
            "parcelSize": "Medium",
        }
        self.assertTrue(ensure_depop_category_optionals(listing))
        depop = listing["depop_specifics"]
        self.assertEqual(len(depop["style"]), 3)
        self.assertEqual(len(depop["occasion"]), 3)
        self.assertNotIn("sizeGrouping", depop)
        result = validate_listing(listing, 5, selected_marketplaces=["depop"])
        self.assertFalse(any(
            str(err.get("field") or "").startswith("depop_specifics.") and "required" in str(err.get("message") or "").lower()
            for err in result.errors
        ), result.errors)
        self.assertTrue(result.can_send, result.errors)

    def test_depop_size_grouping_required_for_petite(self):
        from vendoo_studio.models.depop_fields import ensure_depop_category_optionals

        listing = dict(VALID_LISTING)
        listing["sizeType"] = "Petite"
        listing["depop_specifics"] = {
            **VALID_LISTING["depop_specifics"],
            "style": ["Casual", "Retro", "Boho"],
            "occasion": ["Casual", "Going out", "Vacation"],
            "parcelSize": "Medium",
        }
        self.assertTrue(ensure_depop_category_optionals(listing))
        self.assertEqual(listing["depop_specifics"]["sizeGrouping"], "Petite")
        result = validate_listing(listing, 5, selected_marketplaces=["depop"])
        self.assertFalse(any(error["field"] == "depop_specifics.sizeGrouping" for error in result.errors))
        self.assertTrue(result.can_send, result.errors)

    def test_ebay_season_comma_list_is_normalized(self):
        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = dict(VALID_LISTING)
        listing["ebay_specifics"] = {**VALID_LISTING["ebay_specifics"], "season": "Spring, Summer"}
        self.assertTrue(normalize_listing_dropdowns(listing))
        self.assertEqual(listing["ebay_specifics"]["season"], ["Spring", "Summer"])
        result = validate_listing(listing, 5, selected_marketplaces=["ebay"])
        self.assertFalse(any(error["field"] == "ebay_specifics.season" for error in result.errors))
        self.assertTrue(result.can_send, result.errors)

    def test_legacy_depop_parcel_size_is_rewritten(self):
        listing = dict(VALID_LISTING)
        listing["depop_specifics"] = {
            **VALID_LISTING["depop_specifics"],
            "parcelSize": "Small (S): Under 12 oz — $6.49",
        }
        result = validate_listing(listing, 5, selected_marketplaces=["depop"])
        self.assertTrue(result.can_send, result.errors)
        self.assertEqual(listing["depop_specifics"]["parcelSize"], "Small")
        self.assertFalse(any(error["field"] == "depop_specifics.parcelSize" for error in result.errors))

    def test_depop_parcel_size_follows_the_packaged_weight(self):
        import copy

        from vendoo_studio.models.validation import normalize_listing_dropdowns

        for weight_lb, weight_oz, expected in (
            (0, 3, "Extra extra small"),
            (0, 8, "Small"),
            (1, 0, "Large"),
            (3, 0, "Extra large"),
        ):
            with self.subTest(weight=(weight_lb, weight_oz)):
                listing = copy.deepcopy(VALID_LISTING)
                listing["weight_lb"] = weight_lb
                listing["weight_oz"] = weight_oz
                # Whatever tier the model picked, the weight decides the Depop price band.
                listing["depop_specifics"]["parcelSize"] = "Medium"
                normalize_listing_dropdowns(listing)
                self.assertEqual(listing["depop_specifics"]["parcelSize"], expected)

    def test_depop_parcel_size_keeps_its_value_without_a_weight(self):
        import copy

        from vendoo_studio.models.validation import normalize_listing_dropdowns

        listing = copy.deepcopy(VALID_LISTING)
        listing["weight_lb"] = 0
        listing["weight_oz"] = 0
        listing["depop_specifics"]["parcelSize"] = "Large"
        normalize_listing_dropdowns(listing)
        self.assertEqual(listing["depop_specifics"]["parcelSize"], "Large")

    def test_legacy_etsy_when_made_aliases_match_current_dropdown(self):
        listing = dict(VALID_LISTING)
        listing["etsy_specifics"] = {
            "who_made": "I did",
            "what_is": "A finished product",
            "when_made": "2010s",
        }
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertTrue(result.can_send, result.errors)
        self.assertEqual(listing["etsy_specifics"]["when_made"], "2010 - 2019 (Recently)")
        self.assertFalse(any("not a current dropdown value" in error["message"] for error in result.errors))

        listing["etsy_specifics"]["when_made"] = "2010-2019"
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertTrue(result.can_send, result.errors)
        self.assertEqual(listing["etsy_specifics"]["when_made"], "2010 - 2019 (Recently)")

    def test_legacy_modern_when_made_warns_but_does_not_block_send(self):
        listing = dict(VALID_LISTING)
        listing["etsy_specifics"] = {
            "who_made": "Another company or person",
            "what_is": "A finished product",
            "when_made": "2010s",
        }
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertTrue(result.can_send, result.errors)
        self.assertEqual(listing["etsy_specifics"]["when_made"], "2010 - 2019 (Recently)")
        self.assertFalse(any("not a current dropdown value" in error["message"] for error in result.errors), result.errors)
        self.assertTrue(any("not Etsy eligible" in item["message"] for item in result.warnings))

    def test_unmapped_etsy_when_made_is_coerced_to_a_current_dropdown(self):
        listing = dict(VALID_LISTING)
        listing["etsy_specifics"] = {
            "who_made": "I did",
            "what_is": "A finished product",
            "when_made": "Does Not Apply",
        }
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertTrue(result.can_send, result.errors)
        self.assertEqual(listing["etsy_specifics"]["when_made"], "2010 - 2019 (Recently)")
        self.assertFalse(any("not a current dropdown value" in error["message"] for error in result.errors))

        listing["etsy_specifics"]["when_made"] = "Tomorrow"
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertTrue(result.can_send, result.errors)
        self.assertFalse(any("not a current dropdown value" in error["message"] for error in result.errors), result.errors)

    def test_etsy_when_made_falls_back_to_ebay_year(self):
        listing = dict(VALID_LISTING)
        listing["ebay_specifics"] = {
            **VALID_LISTING["ebay_specifics"],
            "yearManufactured": "2010-2019",
        }
        listing["etsy_specifics"] = {
            "who_made": "I did",
            "what_is": "A finished product",
        }
        result = validate_listing(listing, 5, selected_marketplaces=["etsy"])
        self.assertTrue(result.can_send, result.errors)
        self.assertEqual(listing["etsy_specifics"]["when_made"], "2010 - 2019 (Recently)")


class ExtensionSafetySourceTest(unittest.TestCase):
    def test_existing_item_safety_check_runs_before_photo_upload(self):
        source = background_source()
        safety = source.index("checking_draft_safety")
        upload = source.index("uploading_photos", safety)
        self.assertLess(safety, upload)
        self.assertIn("payload.options?.publish !== false", source)

        refill_start = source.index("async function runFillFields")
        refill_end = source.index("function groupFillFieldBatches", refill_start)
        refill = source[refill_start:refill_end]
        self.assertIn("CHECK_DRAFT_SAFETY", refill)
        self.assertLess(
            refill.index("CHECK_DRAFT_SAFETY"),
            refill.index("groupFillFieldMarketplaces"),
        )

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
const waitForPostSaveForm = async () => true;
const waitForMarketplaceNavControls = async () => true;
const sleep = async () => {};
const log = () => {};
const CONFIG = {SLEEP_LONG: 0};
const results = [];
(async () => {
testStatuses = { etsy: 'LIVE' };
results.push(await checkDraftSafety(['etsy']));
testStatuses = {};
results.push(await checkDraftSafety(['etsy']));
testStatuses = { etsy: 'NOT LISTED' };
results.push(await checkDraftSafety(['etsy']));
testStatuses = { general: 'COMPLETE' };
results.push(await checkDraftSafety([]));
testStatuses = { etsy: 'PENDING' };
results.push(await checkDraftSafety(['etsy']));
testStatuses = { etsy: 'DRAFT LISTING' };
results.push(await checkDraftSafety(['etsy']));
console.log(JSON.stringify(results));
})();
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

    def test_draft_safety_waits_for_marketplace_statuses_to_paint(self):
        source = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text()
        start = source.index("  async function checkDraftSafety")
        end = source.index("  function marketplaceNameToId", start)
        script = source[start:end] + """
let tick = 0;
function scrapeMarketplaceStatusesFromDom() {
  tick += 1;
  return tick >= 3 ? { ebay: 'NOT LISTED', etsy: 'NOT LISTED', poshmark: 'NOT LISTED',
    mercari: 'NOT LISTED', depop: 'NOT LISTED' } : {};
}
const publishedMarketplaceStatuses = (statuses) => Object.entries(statuses || {})
  .filter(([, status]) => /\\b(LISTED|LIVE|ACTIVE|SOLD|PUBLISHED)\\b/i.test(status)
    && !/NOT LISTED/i.test(status));
const marketplaceStatusConfirmsDraft = (status) => ['NOT LISTED', 'DRAFT', 'DRAFT LISTING', 'INCOMPLETE', 'COMPLETE']
  .includes(String(status || '').toUpperCase());
const waitForPostSaveForm = async () => true;
const waitForMarketplaceNavControls = async () => true;
const sleep = async () => {};
const log = () => {};
const CONFIG = {SLEEP_LONG: 0};
(async () => console.log(JSON.stringify(await checkDraftSafety(['ebay','etsy','poshmark','mercari','depop']))))();
"""
        result = json.loads(subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True,
        ).stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["statuses"]["ebay"], "NOT LISTED")

    def test_invalid_dropdown_has_a_distinct_fill_status(self):
        source = (EXTENSION_DIR / "content-scripts" / "vendoo.js").read_text()
        self.assertIn("status: 'invalid'", source)
        frontend = (REPO / "vendoo-studio" / "src" / "components" / "fillLogForms.ts").read_text()
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

    def test_user_form_refresh_sanitizes_size_and_job_snapshot(self):
        job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot={**VALID_LISTING, "platforms": ["ebay"], "size": "XL"},
            status="failed",
            current_step="completion_blocked",
        )
        self.db.add(job)
        self.db.commit()
        updated = {
            **VALID_LISTING,
            "size": "approx 10",
            "ebay_specifics": {**VALID_LISTING["ebay_specifics"], "size": "M"},
        }
        response = self.client.put(
            f"/api/conversations/{self.conv.id}/listing",
            json={"listing": updated},
        )
        self.assertEqual(response.status_code, 200)
        self.db.refresh(job)
        self.assertEqual(job.listing_snapshot.get("size"), "10")
        self.assertEqual(job.listing_snapshot.get("ebay_specifics", {}).get("size"), "10")
        self.assertEqual(job.listing_snapshot.get("platforms"), ["ebay"])
        latest = ListingRepo(self.db).get_revisions(self.conv.id)[0]
        self.assertEqual(latest.source, "user_form")
        self.assertEqual(latest.listing_json.get("size"), "10")

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
        with patch("vendoo_studio.models.validation.get_selected_marketplaces", return_value=["ebay", "poshmark", "mercari", "depop"]), patch(
            "vendoo_studio.routes.extension.dispatch_queued_jobs", new_callable=AsyncMock
        ):
            response = self.client.post(f"/api/jobs/{failed.id}/retry")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["id"], failed.id)
        self.db.refresh(active)
        self.assertEqual(active.status, "dispatched")

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

    def test_job_response_includes_blocker_fields(self):
        job = Job(
            conversation_id=self.conv.id,
            approved_revision_id="rev1",
            listing_snapshot=VALID_LISTING,
            status="failed",
            current_step="completion_blocked",
            last_error="Could not estimate packaged shipping weight/dimensions for the remaining gaps. Retry verification.",
        )
        self.db.add(job)
        self.db.commit()
        JobRepo(self.db).add_event(
            job.id,
            "completion_blocked",
            "completion_blocked",
            {
                "reason": job.last_error,
                "fields": [
                    {"marketplace": "ebay", "field": "Package weight", "expected": "8 oz"},
                    {"marketplace": "ebay", "field": "Package dimensions"},
                ],
            },
        )
        response = self.client.get(f"/api/jobs/{job.id}")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["current_step"], "completion_blocked")
        self.assertEqual(
            body["blocker_fields"],
            [
                {"marketplace": "ebay", "field": "Package weight", "expected": "8 oz"},
                {"marketplace": "ebay", "field": "Package dimensions"},
            ],
        )

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
        background = background_source()
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
        text = background_source()
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
        self.assertIn("resolveEtsyListingState", content)
        self.assertIn("return 'Live Listing'", content)
        self.assertIn('[aria-label^="Remove "]', content)
        self.assertIn("normalizeComparableText(lab) === normalizeComparableText(want)", content)

    def test_ask_chat_prompt_includes_field_context(self):
        components = Path(__file__).resolve().parents[2] / "src" / "components"
        panel = "\n".join(
            (components / name).read_text(encoding="utf-8")
            for name in ("FillLogPanel.tsx", "fillLogForms.ts")
        )
        self.assertIn("function leftoverFieldPrompt", panel)
        self.assertIn("function askChatGapsPrompt", panel)
        self.assertIn("Listing:", panel)
        self.assertIn("Marketplace:", panel)
        self.assertIn("Current value:", panel)
        self.assertIn("Ask chat for", panel)
        self.assertIn("Apply on Vendoo", panel)
        self.assertIn("Set Vendoo category", panel)
        self.assertIn("function leftoverGeneratedValue", panel)
        self.assertIn("isAlreadySetEntry", panel)
        self.assertIn(
            'const FILL_FAILURE_STATUSES = new Set(["invalid", "failed", "not_found", "uncertain"]);',
            panel,
        )
        self.assertNotIn("Ask chat to retry", panel)

    def test_completion_blocker_ask_chat_prompts(self):
        source = (
            Path(__file__).resolve().parents[2] / "src" / "components" / "CopyableLlmError.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("export function completionBlockerPrompt", source)
        self.assertIn("Estimate packaged shipping", source)
        self.assertIn("Fix marketplace category alignment", source)
        self.assertIn("Fill marketplace optional fields", source)
        self.assertIn("Resolve these remaining listing fields", source)
        editor = (
            Path(__file__).resolve().parents[2] / "src" / "components" / "ListingEditor.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("completionBlockerPrompt", editor)
        self.assertIn("blocker_fields", editor)
        self.assertIn("onAskChat={onAskChat}", editor)


if __name__ == "__main__":
    unittest.main()
