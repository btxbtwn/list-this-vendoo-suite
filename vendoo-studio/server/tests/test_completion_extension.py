import json
from pathlib import Path
import subprocess
import unittest

EXTENSION = Path(__file__).resolve().parents[3] / "vendoo-extension"


class CompletionExtensionTest(unittest.TestCase):
    def test_verified_category_walk_uses_exact_labels_without_aliases(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        function = source[source.index("  async function fillCategoryPath"):source.index("  function normalizeCategoryDisplay")]
        script = """
let opened = false, depth = 0;
const path = 'Women > Tops > T-shirts', clicked = [];
const segments = path.split(' > ');
const catBtn = {scrollIntoView() {}, click() {opened = true;}};
const document = {querySelector: () => opened ? {} : null, contains: () => opened};
const normalizeText = text => text.toLowerCase(), normalizeCategoryDisplay = text => text;
const normalizeVendooCategoryPath = data => data.category_path;
const categoryOptionLeaf = option => option.lower;
const findExactCategoryOption = segment => {
  const needle = normalizeText(segment);
  return listCategoryOptions().find(option => option.lower === needle) || null;
};
const waitForCategoryOptions = async () => listCategoryOptions();
const filterCategoryPicker = async () => false;
const readCategoryDisplay = () => depth === 3 ? path : '';
const waitForGeneralCategoryControl = async () => catBtn, findGeneralCategoryControl = () => catBtn;
const findMarketplaceCategoryControl = () => catBtn;
const clearExistingCategorySelection = async () => {}, closeOpenMenus = async () => {};
const waitForCategorySearch = async () => ({}), resetCategoryPickerToRoot = async () => {};
const sleep = async () => {}, log = () => {}, warn = () => {};
const CONFIG = {SLEEP_SHORT: 0, SLEEP_MEDIUM: 0, SLEEP_LONG: 0};
const listCategoryOptions = () => ['Blouses', segments[depth]].map(text => ({text, lower: text.toLowerCase()}));
const findStrongCategoryOption = segment => listCategoryOptions().find(o => o.lower === segment.toLowerCase()) || null;
const clickCategoryOption = async option => {clicked.push(option.text); depth++; if (depth === 3) opened = false;};
""" + function + """
(async () => console.log(JSON.stringify({result: await fillCategoryPath({category_path: path,
  marketplace_categories: {depop: path}, type: 'Blouse'}), clicked})))();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertTrue(result["result"]["ok"])
        self.assertEqual(result["clicked"], ["Women", "Tops", "T-shirts"])

    def test_verified_category_walk_filters_when_exact_option_missing(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        function = source[source.index("  async function fillCategoryPath"):source.index("  function normalizeCategoryDisplay")]
        script = """
let opened = false, depth = 0, filtered = [];
const path = 'Women > Tops > T-shirts', clicked = [];
const segments = path.split(' > ');
const catBtn = {scrollIntoView() {}, click() {opened = true;}};
const document = {querySelector: () => opened ? {} : null, contains: () => opened};
const normalizeText = text => text.toLowerCase(), normalizeCategoryDisplay = text => text;
const normalizeVendooCategoryPath = data => data.category_path;
const categoryOptionLeaf = option => option.lower;
let reveal = false;
const listCategoryOptions = () => {
  if (!reveal && depth === 0) return [{text: 'Men', lower: 'men'}];
  return [segments[depth]].map(text => ({text, lower: text.toLowerCase()}));
};
const findExactCategoryOption = segment => {
  const needle = normalizeText(segment);
  return listCategoryOptions().find(option => option.lower === needle) || null;
};
const waitForCategoryOptions = async () => listCategoryOptions();
const filterCategoryPicker = async (query) => {filtered.push(query); reveal = true; return true;};
const readCategoryDisplay = () => depth === 3 ? path : '';
const waitForGeneralCategoryControl = async () => catBtn, findGeneralCategoryControl = () => catBtn;
const findMarketplaceCategoryControl = () => catBtn;
const clearExistingCategorySelection = async () => {}, closeOpenMenus = async () => {};
const waitForCategorySearch = async () => ({}), resetCategoryPickerToRoot = async () => {};
const sleep = async () => {}, log = () => {}, warn = () => {};
const CONFIG = {SLEEP_SHORT: 0, SLEEP_MEDIUM: 0, SLEEP_LONG: 0};
const findStrongCategoryOption = () => null;
const clickCategoryOption = async option => {clicked.push(option.text); depth++; if (depth === 3) opened = false;};
""" + function + """
(async () => console.log(JSON.stringify({result: await fillCategoryPath({category_path: path,
  marketplace_categories: {poshmark: path}}), clicked, filtered})))();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertTrue(result["result"]["ok"])
        self.assertEqual(result["filtered"], ["Women"])
        self.assertEqual(result["clicked"], ["Women", "Tops", "T-shirts"])

    def test_schema_collection_includes_disabled_cascade_fields(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        function = source[source.index("  async function collectMarketplaceSchemaFields"):source.index("  function compareSchemaValues")]
        script = """
const enabled = {tagName: 'INPUT', id: 'listings.ebay.overrides.brand', value: '',
  getAttribute: () => null};
const disabled = {tagName: 'INPUT', id: 'listings.ebay.marketplaceSpecifics.department', value: '',
  disabled: true, getAttribute: (name) => name === 'aria-disabled' ? 'true' : null};
const document = {querySelectorAll: () => [enabled, disabled], getElementById: () => null};
const isVisibleElement = () => true;
const isEnabledField = (el) => !el.disabled && el.getAttribute('aria-disabled') !== 'true';
const marketplaceFieldNode = (el) => el;
const fieldLabelForControl = el => el.id.includes('brand') ? 'Brand' : 'Department';
const scrapedFieldLabel = fieldLabelForControl;
const normalizeFieldKey = value => value.toLowerCase(), isAccountSettingField = () => false;
const readPersistedControlValue = () => '', isMultiChipField = () => false;
const selectorFor = el => '#' + el.id, isDropdownLike = () => false;
const displayedFieldValue = () => '';
const readLiveFieldOptions = async () => ({options: [], source: 'none'});
const closeOpenMenus = async () => {}, log = () => {}, warn = () => {};
const MAX_OPTION_CAPTURES_PER_PLATFORM = 12;
const fieldLooksFilled = () => false;
""" + function + """
(async () => console.log(JSON.stringify(await collectMarketplaceSchemaFields('ebay'))))();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        labels = [field["label"] for field in result]
        self.assertEqual(labels, ["Brand", "Department"])
        self.assertFalse(result[0]["disabled"])
        self.assertTrue(result[1]["disabled"])

    def test_ensure_marketplace_form_ready_reactivates_after_category_remount(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        start = source.index("  async function ensureMarketplaceFormReady")
        end = source.index("  function marketplaceSectionLooksActive")
        function = source[start:end]
        script = """
let activates = 0, expands = 0, tick = 0;
const document = {querySelector: (sel) => {
  if (tick < 2) return null;
  if (String(sel).includes('listings.ebay.')) return {id: 'listings.ebay.overrides.price'};
  return null;
}};
const closeOpenMenus = async () => {};
const marketplaceSectionLooksActive = () => tick >= 2;
const marketplaceFormMounted = () => tick >= 2;
const activateMarketplaceSection = async () => {activates++; tick++; return true;};
const expandOptionalFields = async () => {expands++;};
const sleep = async () => {tick++;};
const CONFIG = {SLEEP_LONG: 0};
""" + function + """
(async () => console.log(JSON.stringify({
  ready: await ensureMarketplaceFormReady('ebay', {requireListingFields: true}),
  activates, expands,
})))();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertTrue(result["ready"])
        self.assertGreaterEqual(result["activates"], 1)
        self.assertGreaterEqual(result["expands"], 1)

    def test_category_readback_reconstructs_css_breadcrumb_separators(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        function = source[source.index("  function readCategoryDisplay"):source.index("  function categoryDisplayMatches")]
        script = "const normalizeCategoryDisplay = text => text.trim();\n" + function + """
const parts = ["Clothing", "Women's Clothing", "Tops & Tees", "T-shirts"];
const button = {children: parts.map(textContent => ({tagName: 'SPAN', textContent})),
  textContent: parts.join('')};
console.log(JSON.stringify([readCategoryDisplay(button), readCategoryDisplay({textContent: 'Category'})]));
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(result, ["Clothing > Women's Clothing > Tops & Tees > T-shirts", ""])

    def test_failed_probe_releases_job_before_reporting_failure(self):
        source = (EXTENSION / "background.js").read_text()
        function = source[source.index("async function runJob"):source.index("function buildJobSteps")]
        script = """
let activeJob = {job_id: 'probe', tabId: 3, options: {mode: 'schema_probe'}};
const events = [];
const selectJobSteps = (job, steps) => steps;
const buildJobSteps = () => [{step: 'discovering_schema', fn: async () => ({ok: false,
  error: 'etsy: category missing', schema: {etsy: {fields: [], error: 'category missing'}}})}];
const persistActiveJob = async value => events.push({persist: value});
const collectDiagnostics = () => {}, log = () => {};
const send = message => events.push({message, busy: !!activeJob});
const stopJobPreview = async () => {}, closeListingTab = async id => events.push({closed: id});
""" + function + """
(async () => {await runJob('probe'); console.log(JSON.stringify({activeJob, events}));})();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertIsNone(result["activeJob"])
        failure = next(event for event in result["events"] if event.get("message", {}).get("type") == "job.step_failed")
        self.assertFalse(failure["busy"])
        self.assertEqual(failure["message"]["payload"]["schema"]["etsy"]["error"], "category missing")
        self.assertIn({"persist": None}, result["events"])
        self.assertIn({"closed": 3}, result["events"])

    def test_schema_collection_preserves_native_options_and_awaits_live_capture(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        function = source[source.index("  async function collectMarketplaceSchemaFields"):source.index("  function compareSchemaValues")]
        script = """
const native = {tagName: 'SELECT', id: 'material', value: 'cotton',
  options: [{textContent: 'Choose', value: ''}, {textContent: 'Cotton', value: 'cotton'}],
  selectedOptions: [{textContent: 'Cotton'}], getAttribute: () => null};
const live = {tagName: 'INPUT', id: 'occasion', value: '', getAttribute: () => null};
const document = {querySelectorAll: () => [native, live], getElementById: () => null};
const isVisibleElement = () => true, isEnabledField = () => true;
const marketplaceFieldNode = () => true, fieldLabelForControl = el => el.id;
const scrapedFieldLabel = fieldLabelForControl;
const normalizeFieldKey = value => value, isAccountSettingField = () => false;
const readPersistedControlValue = el => el.value, isMultiChipField = () => false;
const selectorFor = el => '#' + el.id, isDropdownLike = () => true;
const displayedFieldValue = el => el.value;
let captures = 0;
const readLiveFieldOptions = async () => {captures++; return {options: ['Casual'], source: 'live-dropdown'};};
const closeOpenMenus = async () => {}, log = () => {}, warn = () => {};
const MAX_OPTION_CAPTURES_PER_PLATFORM = 12;
""" + function + """
(async () => console.log(JSON.stringify({fields: await collectMarketplaceSchemaFields('etsy'), captures})))();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(result["captures"], 1)
        native, live = result["fields"]
        self.assertEqual(native["options"], [{"label": "Cotton", "value": "cotton"}])
        self.assertTrue(native["options_complete"])
        self.assertEqual(native["value"], "Cotton")
        self.assertEqual(live["options"], ["Casual"])
        self.assertFalse(live["options_complete"])

    def test_boolean_repair_clicks_only_when_value_changes(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        function = source[source.index("  async function fillBooleanField"):source.index("  function reverifyPatchedFields")]
        script = """
const entries = [];
const recordFill = (entry) => entries.push(entry);
const readPersistedControlValue = (el) => el.checked;
const selectorFor = () => '#handmade';
const sleep = async () => {};
const CONFIG = {SLEEP_SHORT: 1};
""" + function + """
(async () => {
  const control = {checked: false, clicks: 0, click() {this.clicks++; this.checked = !this.checked;}};
  await fillBooleanField(control, true, 'Handmade');
  await fillBooleanField(control, true, 'Handmade');
  await fillBooleanField(control, false, 'Handmade');
  await fillBooleanField(control, 'maybe', 'Handmade');
  console.log(JSON.stringify({clicks: control.clicks, checked: control.checked, entries}));
})();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(result["clicks"], 2)
        self.assertFalse(result["checked"])
        self.assertEqual([entry["status"] for entry in result["entries"]], ["filled", "filled", "filled", "invalid"])

    def test_refill_reads_saved_draft_even_when_save_rejects_values(self):
        source = (EXTENSION / "background.js").read_text()
        functions = source[source.index("async function runFillFields"):source.index("function compactVendooValue")]
        script = """
let activePatch = null;
let activeJob = null;
let calls = [];
const log = () => {};
const warn = () => {};
const send = (message) => calls.push(message);
const stopJobPreview = async () => {};
const sleep = async () => {};
const closeListingTab = async () => calls.push('closed');
const openListingForPatch = async () => ({ok: true, tabId: 123});
const waitForContentScript = async () => ({ok: true});
const durableItemId = (id) => id;
const sendToVendoo = async (job, command) => {
  calls.push(command.type);
  if (command.type === 'SAVE_MARKETPLACE') return {ok: false, error: 'Material required'};
  return {ok: true, fill_log: {entries: [{field: 'Material', status: 'failed'}]}};
};
const verifySavedDraft = async (job) => {
  calls.push({verify: job});
  return {readback: true, verified: false, schema: {ebay: {fields: [{label: 'Material', value: ''}]}}};
};
""" + functions + """
(async () => {
  await runFillFields('job', {vendoo_item_id: 'draft', listing: {title: 'Tee'}, platforms: ['ebay'],
    fields: [{marketplace: 'ebay', field: 'Material', value: 'Cotton'}]});
  const repaired = calls;
  calls = [];
  await runFillFields('job', {vendoo_item_id: 'draft', listing: {title: 'Tee'}, platforms: ['ebay'], fields: []});
  console.log(JSON.stringify({repaired, readOnly: calls, activePatch}));
})();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        calls = result["repaired"]
        verified = next(item for item in calls if isinstance(item, dict) and "verify" in item)
        self.assertEqual(verified["verify"]["options"]["platforms"], ["ebay"])
        self.assertEqual(calls[-2], "closed")
        self.assertEqual(calls[-1]["type"], "job.step_completed")
        self.assertTrue(calls[-1]["payload"]["verification"]["readback"])
        self.assertFalse(calls[-1]["payload"]["verification"]["verified"])
        self.assertNotIn("FILL_FIELDS", result["readOnly"])
        self.assertNotIn("SAVE_GENERAL", result["readOnly"])
        self.assertIsNone(result["activePatch"])

    def test_manual_apply_skips_full_draft_verification(self):
        source = (EXTENSION / "background.js").read_text()
        functions = source[source.index("async function runFillFields"):source.index("function compactVendooValue")]
        script = """
let activePatch = null;
let activeJob = null;
let calls = [];
const log = () => {};
const warn = () => {};
const send = (message) => calls.push(message);
const stopJobPreview = async () => {};
const sleep = async () => {};
const closeListingTab = async () => calls.push('closed');
const openListingForPatch = async () => ({ok: true, tabId: 123});
const waitForContentScript = async () => ({ok: true});
const durableItemId = (id) => id;
const sendToVendoo = async (job, command) => {
  calls.push(command.type);
  return {ok: true, fill_log: {entries: [{field: 'Material', status: 'filled'}]}, vendoo_item_id: 'draft'};
};
const verifySavedDraft = async () => {
  calls.push('verified');
  return {readback: true, verified: true, schema: {}};
};
""" + functions + """
(async () => {
  await runFillFields('job', {vendoo_item_id: 'draft', listing: {title: 'Tee'}, platforms: ['ebay'],
    verify: false, fields: [{marketplace: 'ebay', field: 'Material', value: 'Cotton'}]});
  console.log(JSON.stringify({calls, activePatch}));
})();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertIn("FILL_FIELDS", result["calls"])
        self.assertNotIn("verified", result["calls"])
        completed = next(item for item in result["calls"] if isinstance(item, dict) and item.get("type") == "job.step_completed")
        self.assertNotIn("verification", completed["payload"])
        self.assertIsNone(result["activePatch"])

    def test_verification_reloads_before_reading_and_checks_readiness(self):
        source = (EXTENSION / "background.js").read_text()
        function = source[source.index("async function verifySavedDraft"):source.index("async function auditGeneral")]
        script = """
const calls = [];
const durableItemId = (id) => id;
const extractItemIdFromUrl = () => 'draft';
const chrome = {tabs: {update: async () => calls.push('navigate')}};
const reloadTabAndWait = async () => {calls.push('reload'); return {status: 'complete'};};
const isTabReady = (tab) => tab.status === 'complete';
const waitForContentScript = async () => {calls.push('ready'); return {ok: true};};
const sendToVendoo = async (job, message) => {calls.push(message.type); return {ok: true, readback: true};};
""" + function + """
(async () => {
  await verifySavedDraft({tabId: 123, job_id: 'job', vendoo_item_id: 'draft', vendoo_url: 'https://web.vendoo.co/app/item/draft', listing: {}, options: {platforms: ['ebay']}});
  console.log(JSON.stringify(calls));
})();
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(result, ["navigate", "reload", "ready", "VERIFY_SAVED_DRAFT"])

    def test_patch_fill_skips_matching_values_but_replaces_mismatches(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        start = source.index("  /** True when a FILL_FIELDS patch would leave the control unchanged. */")
        end = source.index("  function chipsMatchValues")
        helper = source[start:end]
        equals_start = source.index("  function normalizeComparableText")
        equals_end = source.index("  /** True when a FILL_FIELDS patch would leave the control unchanged. */")
        equals = source[equals_start:equals_end]
        script = equals + """
function normalizeOptionValue(text) {
  return String(text || '').replace(/[–—]/g, '-').replace(/[*?]+/g, '')
    .replace(/[_/]+/g, ' ').replace(/-/g, ' ').replace(/\\s+/g, ' ').trim().toLowerCase();
}
function displayedFieldValue(el) { return el.value || ''; }
function readPersistedControlValue(el) { return el.checked; }
function isMultiChipField() { return false; }
function shouldFillAsDropdown() { return false; }
function splitChipValues() { return []; }
function chipsMatchValues() { return false; }
function optionMatchesValue(got, want) {
  return normalizeOptionValue(got) === normalizeOptionValue(want);
}
""" + helper + """
const empty = { value: '' };
const matching = { value: 'Spring' };
const wrong = { value: 'Fall' };
console.log(JSON.stringify({
  empty: patchValueAlreadySet(empty, 'Spring', 'Season'),
  match: patchValueAlreadySet(matching, 'Spring', 'Season'),
  replace: patchValueAlreadySet(wrong, 'Spring', 'Season'),
  loose: patchValueAlreadySet({ value: 'spring' }, 'Spring', 'Season'),
}));
"""
        result = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertFalse(result["empty"])
        self.assertTrue(result["match"])
        self.assertFalse(result["replace"])
        self.assertTrue(result["loose"])

    def test_fill_fields_path_no_longer_skips_all_filled_controls(self):
        source = (EXTENSION / "content-scripts" / "vendoo.js").read_text()
        self.assertIn("patchValueAlreadySet", source)
        self.assertNotIn("Already filled on Vendoo", source)
        self.assertIn("replacements (wrong value → listing value) still write", source)
