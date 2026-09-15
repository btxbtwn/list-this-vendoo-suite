import json
from pathlib import Path
import subprocess
import unittest

EXTENSION = Path(__file__).resolve().parents[3] / "vendoo-extension"


class CompletionExtensionTest(unittest.TestCase):
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
