from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

EXTENSION_DIR = Path(__file__).resolve().parents[3] / "vendoo-extension"
CONTENT_SCRIPT = EXTENSION_DIR / "content-scripts" / "vendoo.js"


def _slice(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def _run(registry_options: dict, calls: list[dict]) -> list:
    """Run the real coercion helpers under node against a stubbed fill context."""
    text = CONTENT_SCRIPT.read_text(encoding="utf-8")

    helpers = "\n".join([
        _slice(text, "function normalizeOptionValue", "function normalizeComparableText"),
        _slice(text, "function optionMatchesValue", "function isDropdownLike"),
        _slice(text, "function uniqueStrings", "function brandFillCandidates"),
        _slice(text, "function normalizeFieldKey", "function selectorFor"),
    ])

    coercion = _slice(
        text,
        "// Live dropdown options learned by the schema probe",
        "function mapPatchValueStatic",
    )

    script = f"""
const FIELD_KEY_ALIASES = {{}};
const warnings = [];
function log() {{}}
function warn(message) {{ warnings.push(message); }}
function mappingMarketplace(marketplace) {{
  const mp = String(marketplace || '').toLowerCase();
  if (!mp || mp === 'general' || mp === 'unknown') return 'vendoo';
  return mp;
}}
// Stands in for the hardcoded value maps.
let staticResult;
function mapPatchValueStatic(marketplace, fieldName, value) {{
  return staticResult === undefined ? value : staticResult;
}}
{helpers}
{coercion}

currentRegistryOptions = {json.dumps(registry_options)};
const calls = {json.dumps(calls)};
const out = calls.map((call) => {{
  staticResult = Object.prototype.hasOwnProperty.call(call, 'static')
    ? call.static
    : undefined;
  return mapPatchValue(call.marketplace, call.field, call.value);
}});
console.log(JSON.stringify({{ values: out, warnings }}));
"""
    proc = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    return json.loads(proc.stdout)


def _values(registry_options: dict, calls: list[dict]) -> list:
    return _run(registry_options, calls)["values"]


class RegistryOptionCoercionTest(unittest.TestCase):
    def test_live_options_repair_formatting_drift(self):
        options = {"etsy": {"when made": ["2020 - 2026 (Recently)", "Before 2004 (Vintage)"]}}
        # Case, en-dash and spacing drift all snap back onto the real option.
        result = _values(options, [
            {
                "marketplace": "etsy",
                "field": "When Made",
                "value": "2020s",
                "static": "2020 - 2026 (recently)",
            },
            {
                "marketplace": "etsy",
                "field": "When Made",
                "value": "2020s",
                "static": "2020 – 2026 (Recently)",
            },
        ])
        self.assertEqual(result, ["2020 - 2026 (Recently)", "2020 - 2026 (Recently)"])

    def test_renamed_option_is_left_for_the_fill_log_to_flag(self):
        options = {"etsy": {"when made": ["2020 - 2027 (Recently)", "Before 2004 (Vintage)"]}}
        # A renamed bucket differs by one digit, which no fuzzy match should
        # bridge — guessing here would silently file the item under the wrong
        # era. The value passes through so fillDropdownField reports it invalid.
        result = _values(options, [{
            "marketplace": "etsy",
            "field": "When Made",
            "value": "2020s",
            "static": "2020 - 2026 (Recently)",
        }])
        self.assertEqual(result[0], "2020 - 2026 (Recently)")

    def test_renamed_option_warns_so_the_cause_is_visible(self):
        options = {"etsy": {"when made": ["2020 - 2027 (Recently)"]}}
        run = _run(options, [{
            "marketplace": "etsy",
            "field": "When Made",
            "value": "2020s",
            "static": "2020 - 2026 (Recently)",
        }])
        self.assertEqual(len(run["warnings"]), 1)
        self.assertIn("not a current etsy option", run["warnings"][0])

    def test_no_warning_when_the_value_is_valid(self):
        options = {"etsy": {"when made": ["2020 - 2026 (Recently)"]}}
        run = _run(options, [{
            "marketplace": "etsy",
            "field": "When Made",
            "value": "2020s",
            "static": "2020 - 2026 (Recently)",
        }])
        self.assertEqual(run["warnings"], [])

    def test_value_is_untouched_when_registry_is_cold(self):
        result = _values({}, [{
            "marketplace": "etsy",
            "field": "When Made",
            "value": "2020s",
            "static": "2020 - 2026 (Recently)",
        }])
        self.assertEqual(result[0], "2020 - 2026 (Recently)")

    def test_static_skip_decision_is_preserved(self):
        options = {"depop": {"parcel size": ["Small", "Medium", "Large"]}}
        # null from the static maps means "no option here"; the registry must not
        # resurrect the field.
        result = _values(options, [{
            "marketplace": "depop",
            "field": "Parcel Size",
            "value": "Chartreuse",
            "static": None,
        }])
        self.assertIsNone(result[0])

    def test_unknown_value_falls_through_to_static_result(self):
        options = {"depop": {"parcel size": ["Small", "Medium", "Large"]}}
        result = _values(options, [{
            "marketplace": "depop",
            "field": "Parcel Size",
            "value": "Enormous",
            "static": "Enormous",
        }])
        self.assertEqual(result[0], "Enormous")

    def test_raw_value_is_used_when_static_output_does_not_match(self):
        options = {"depop": {"parcel size": ["Small", "Medium", "Large"]}}
        result = _values(options, [{
            "marketplace": "depop",
            "field": "Parcel Size",
            "value": "Medium",
            "static": "Mid-size parcel",
        }])
        self.assertEqual(result[0], "Medium")

    def test_general_bucket_backs_up_the_marketplace_bucket(self):
        options = {"general": {"condition": ["Good", "Excellent", "Fair"]}}
        result = _values(options, [{
            "marketplace": "etsy",
            "field": "Condition",
            "value": "good",
            "static": "good",
        }])
        self.assertEqual(result[0], "Good")

    def test_options_do_not_leak_between_marketplaces(self):
        options = {"etsy": {"when made": ["2020 - 2027 (Recently)"]}}
        result = _values(options, [{
            "marketplace": "depop",
            "field": "When Made",
            "value": "2020 - 2026 (Recently)",
            "static": "2020 - 2026 (Recently)",
        }])
        self.assertEqual(result[0], "2020 - 2026 (Recently)")

    def test_empty_value_is_left_alone(self):
        options = {"etsy": {"when made": ["2020 - 2027 (Recently)"]}}
        result = _values(options, [{
            "marketplace": "etsy",
            "field": "When Made",
            "value": "",
            "static": "",
        }])
        self.assertEqual(result[0], "")


class SchemaProbeCapturesOptionsTest(unittest.TestCase):
    def test_discovery_awaits_option_capture(self):
        text = CONTENT_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("async function collectMarketplaceSchemaFields", text)
        self.assertIn("const fields = await collectMarketplaceSchemaFields(platform)", text)
        self.assertIn("readLiveFieldOptions", text)
        self.assertIn("MAX_OPTION_CAPTURES_PER_PLATFORM", text)

    def test_registry_options_reach_the_fill_handlers(self):
        text = CONTENT_SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(text.count("currentRegistryOptions = msg.registry_options || {}"), 2)
        background = (EXTENSION_DIR / "background.js").read_text(encoding="utf-8")
        self.assertIn("registry_options: job.registry_options || {}", background)
        self.assertIn("registry_options: payload.registry_options || {}", background)


if __name__ == "__main__":
    unittest.main()
