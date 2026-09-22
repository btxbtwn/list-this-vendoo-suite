/** Pure form, field, and prompt logic behind the Fields panel. */
import type { FillLogEntry, FillLogReport } from "../api/types";
import { OPTIONS_RULE, optionsForField, type DropdownForms } from "../dropdownOptions";
import {
  DEPOP_CATEGORY_OPTIONALS,
  EBAY_CATEGORY_CORE,
  EBAY_CATEGORY_OPTIONALS,
  ETSY_CATEGORY_OPTIONALS,
} from "../marketplaceFields";

export interface DraftField {
  key: string;
  label: string;
  value: string;
  missing: boolean;
  /** Listing marked Does Not Apply / N/A — show yellow and never try to fill. */
  notApplicable?: boolean;
  leftover?: FillLogEntry;
  section?: string;
  /** Listing/chat overlay only — not confirmed empty on the live Vendoo draft. */
  listingOnly?: boolean;
}

interface DraftForm {
  id: string;
  label: string;
  fields: DraftField[];
  filled: number;
  missing: number;
  notApplicable: number;
  liveStatus?: string;
}

const STATUS_LABELS: Record<string, string> = {
  filled: "Filled",
  skipped: "Not filled",
  not_applicable: "Does not apply",
  not_found: "Missing",
  invalid: "Invalid option",
  failed: "Didn't work",
  uncertain: "Uncertain",
  new: "New fields",
};

const STATUS_ORDER = ["invalid", "failed", "not_found", "uncertain", "new", "skipped", "not_applicable", "filled"];
const FILLABLE_STATUSES = new Set(["invalid", "failed", "not_found", "uncertain", "new", "skipped"]);
const DISCOVERY_STATUSES = new Set(["new"]);
/** Real Apply/Send failures only — not skipped-empty or already-correct controls. */
export const FILL_FAILURE_STATUSES = new Set(["invalid", "failed", "not_found", "uncertain"]);

function isAlreadySetEntry(entry: { status?: string; reason?: string }): boolean {
  return /^already set$/i.test(String(entry.reason || "").trim());
}
export const EMPTY_CELL = "— empty —";
export const UNREAD_CELL = "— not read —";
/** Keep the option dump readable when a dropdown has hundreds of entries. */
const MAX_PROMPT_OPTIONS = 60;
const DOES_NOT_APPLY_RE = /^(d|n\/?a|n\.a\.?|does not apply|none|unknown|-+)$/i;

export interface FormSyncCounts {
  onVendoo: number;
  vendooEmpty: number;
  readyToApply: number;
  needsChat: number;
  notApplicable: number;
}

export function listingTextForField(
  listing: Record<string, unknown> | undefined,
  marketplace: string,
  field: DraftField,
): string {
  return listingValueForField(listing, marketplace, field);
}

export function listingFieldEmpty(
  listing: Record<string, unknown> | undefined,
  marketplace: string,
  field: DraftField,
): boolean {
  return !listingTextForField(listing, marketplace, field);
}

export function vendooTextForField(field: DraftField): string {
  if (field.notApplicable) return "Does not apply";
  return field.value || "";
}

function normalizeComparableFieldText(text: string): string {
  return String(text || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
}

function normalizeLooseFieldText(text: string): string {
  return normalizeComparableFieldText(text)
    .replace(/[–—]/g, "-")
    .replace(/[*?]+/g, "")
    .replace(/[_/]+/g, " ")
    .replace(/-/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Listing/apply value already matches what Vendoo shows — no write needed. */
function applyValueMatchesVendoo(applyValue: string, field: DraftField): boolean {
  const got = normalizeComparableFieldText(vendooTextForField(field));
  const want = normalizeComparableFieldText(applyValue);
  if (!got || !want) return false;
  if (got === want) return true;
  return normalizeLooseFieldText(got) === normalizeLooseFieldText(want);
}

export function fieldNeedsVendooApply(field: DraftField, applyValue: string): boolean {
  if (!applyValue || field.notApplicable || isUnfillableField(field) || field.listingOnly) return false;
  if (field.missing) return true;
  return !applyValueMatchesVendoo(applyValue, field);
}

export function formSyncCounts(
  form: DraftForm,
  listing: Record<string, unknown> | undefined,
  fromVendooDraft: boolean,
): FormSyncCounts {
  const counts: FormSyncCounts = {
    onVendoo: 0,
    vendooEmpty: 0,
    readyToApply: 0,
    needsChat: 0,
    notApplicable: 0,
  };
  for (const field of form.fields) {
    if (field.notApplicable) {
      counts.notApplicable += 1;
      continue;
    }
    if (isUnfillableField(field)) continue;
    const listingValue = listingTextForField(listing, form.id, field);
    if (fromVendooDraft) {
      if (!field.missing) {
        if (listingValue && !applyValueMatchesVendoo(listingValue, field)) {
          counts.readyToApply += 1;
        } else {
          counts.onVendoo += 1;
        }
        continue;
      }
      counts.vendooEmpty += 1;
      if (listingValue) counts.readyToApply += 1;
      else counts.needsChat += 1;
      continue;
    }
    if (listingValue) counts.onVendoo += 1;
    else counts.vendooEmpty += 1;
  }
  return counts;
}

export function fieldsNeedingListingValues(
  forms: DraftForm[],
  listing: Record<string, unknown> | undefined,
): { form: DraftForm; field: DraftField }[] {
  return forms.flatMap((form) =>
    form.fields
      .filter((field) => !field.notApplicable && !isUnfillableField(field))
      .filter((field) => listingFieldEmpty(listing, form.id, field))
      .map((field) => ({ form, field })),
  );
}

/** Deduped empty listing values + Apply/Send failures for the Ask-chat button. */
export function askChatTargetCount(
  forms: DraftForm[],
  listing: Record<string, unknown> | undefined,
  failures: FillLogEntry[],
): number {
  const seen = new Set<string>();
  let count = 0;
  for (const entry of failures) {
    const key = `${String(entry.marketplace || "").toLowerCase()}:${normalizeFieldName(entry.field)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    count += 1;
  }
  for (const { form, field } of fieldsNeedingListingValues(forms, listing)) {
    const key = `${form.id}:${fieldMatchKey(field)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    count += 1;
  }
  return count;
}

export function issueLabel(entry: FillLogEntry): string {
  if (entry.status === "new") return "Discovered on form";
  if (isAlreadySetEntry(entry)) return "Already set";
  if (/^no evidence\b/i.test(String(entry.reason || "").trim())) return "No evidence";
  if (entry.status === "skipped") return "Not filled";
  return STATUS_LABELS[entry.status] || entry.status;
}

export function issueKind(entry: FillLogEntry): "discovery" | "failure" {
  return DISCOVERY_STATUSES.has(entry.status) ? "discovery" : "failure";
}
const DEFAULT_SELECTED_MARKETPLACES = ["ebay", "etsy", "poshmark", "mercari", "depop"];
const MARKETPLACE_ORDER = ["general", "ebay", "etsy", "poshmark", "mercari", "depop", "facebook", "shopify", "vinted", "whatnot", "sellwild", "grailed"];
const MARKETPLACE_LABELS: Record<string, string> = {
  general: "Vendoo",
  ebay: "eBay",
  etsy: "Etsy",
  poshmark: "Poshmark",
  mercari: "Mercari",
  depop: "Depop",
  facebook: "Facebook",
  shopify: "Shopify",
  vinted: "Vinted",
  whatnot: "Whatnot",
  sellwild: "Sellwild",
  grailed: "Grailed",
  vestiaire: "Vestiaire",
  kidizen: "Kidizen",
};
const SKIP_KEYS = new Set([
  "itemid",
  "userid",
  "datecreated",
  "datelastmodified",
  "datelisted",
  "lastdatelisted",
  "laststatusdate",
  "listings",
  "images",
  "videos",
  "id",
  "errors",
  "error",
  "extras",
  "siteid",
  "enabled",
  "listed",
  "listedid",
  "listingid",
  "listingurl",
  "listingattemptmessages",
  "marketplaceaccount",
  "marketplaceid",
  "sales",
  "status",
  "origin",
  "version",
  "validate",
  "hash",
  "draftid",
  "lastsynced",
  "lastmodified",
  "statuses",
]);

const UNFILLABLE_FIELDS = new Set(["photos", "images", "videos", "image"]);
const ACCOUNT_SETTING_FIELDS = new Set([
  "allow best offer",
  "auto-accept",
  "auto accept",
  "minimum offer",
  "minimum price",
  "exclude sku from listing",
  "no brand/not sure",
  "worldwide shipping",
  "custom property",
  "other info",
  "size grouping",
  "accept returns",
  "return within",
  "return refund method",
  "return paid by",
  "return payed by",
  "returns",
  "starting price",
  "payment method",
]);
const GENERAL_LISTING_KEYS: Record<string, string> = {
  title: "title",
  description: "description",
  price: "price",
  "listing price": "price",
  cost: "cost",
  "cost of goods": "cost",
  quantity: "quantity",
  brand: "brand",
  condition: "condition",
  "primary color": "primaryColor",
  color: "primaryColor",
  "secondary color": "secondaryColor",
  size: "size",
  "us size": "size",
  sku: "sku",
  category: "category_path",
  "zip code": "zipCode",
  "size type": "sizeType",
  pounds: "weight_lb",
  "package weight (lb)": "weight_lb",
  ounces: "weight_oz",
  "package weight (oz)": "weight_oz",
  tags: "tags",
  labels: "labels",
  "vendoo labels": "labels",
  notes: "notes",
  "internal notes": "notes",
  "vendoo internal notes": "notes",
};

function isAccountSettingField(field: DraftField | string): boolean {
  const raw = typeof field === "string" ? field : field.label || field.key;
  const key = normalizeLookupKey(raw);
  if (ACCOUNT_SETTING_FIELDS.has(key)) return true;
  // Scraped labels often concatenate the whole control path, e.g.
  // "Pricing Format Details Fixed Price Allow Best Offer".
  return (
    key.includes("best offer") ||
    key.includes("accept offer") ||
    key.includes("decline offer") ||
    key.includes("pricing format details") ||
    key.includes("auto-accept") ||
    key.includes("auto accept")
  );
}

function isUnfillableField(field: DraftField): boolean {
  return (
    UNFILLABLE_FIELDS.has(field.label.toLowerCase()) ||
    UNFILLABLE_FIELDS.has(field.key.toLowerCase()) ||
    isAccountSettingField(field)
  );
}

function normalizeLookupKey(value: string): string {
  const aliases: Record<string, string> = {
    "listing price": "price",
    "buy it now price": "price",
    "cost of goods": "cost",
    "us size": "size",
    "vendoo labels": "labels",
    "internal notes": "notes",
    "vendoo internal notes": "notes",
    "primary color": "color",
    "when was it made": "when made",
    "who made it": "who made",
    "starting price": "starting price",
    "return payed by": "return paid by",
  };
  const key = String(value || "")
    .replace(/^(ebay|etsy|poshmark|mercari|depop)\s+/i, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_*?-]+/g, " ")
    .replace(/[^\w\s]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return aliases[key] || key;
}

function lookupToJsonKey(key: string): string {
  const mapped: Record<string, string> = {
    "when made": "when_made",
    "who made": "who_made",
    "what is it": "what_is",
    "size type": "sizeType",
    "country of origin": "countryOfOrigin",
    "year manufactured": "yearManufactured",
  };
  if (mapped[key]) return mapped[key];
  const parts = key.split(" ").filter(Boolean);
  if (!parts.length) return "";
  return parts[0] + parts.slice(1).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join("");
}

function isBlankListingValue(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === "string") return value.trim() === "";
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value as object).length === 0;
  return false;
}

function valueFromRecord(record: Record<string, unknown> | undefined, key: string): unknown {
  if (!record || !key) return undefined;
  const jsonKey = lookupToJsonKey(key);
  const mapped = GENERAL_LISTING_KEYS[key];
  const colorKeys = new Set(["color", "primary color"]);
  for (const [candidate, value] of Object.entries(record)) {
    const candidateKey = normalizeLookupKey(candidate);
    const matched =
      candidateKey === key ||
      (colorKeys.has(key) && colorKeys.has(candidateKey)) ||
      candidate === jsonKey ||
      (mapped && candidate === mapped);
    if (!matched || isBlankListingValue(value)) continue;
    return value;
  }
  if (jsonKey && jsonKey in record && !isBlankListingValue(record[jsonKey])) return record[jsonKey];
  if (mapped && mapped in record && !isBlankListingValue(record[mapped])) return record[mapped];
  const nestedCategory = record.category_specifics;
  if (nestedCategory && typeof nestedCategory === "object" && !Array.isArray(nestedCategory) && nestedCategory !== record) {
    const found = valueFromRecord(nestedCategory as Record<string, unknown>, key);
    if (found != null) return found;
  }
  const nestedMarket = record.marketplaceSpecifics || record.marketplace_specifics;
  if (nestedMarket && typeof nestedMarket === "object" && !Array.isArray(nestedMarket) && nestedMarket !== record) {
    return valueFromRecord(nestedMarket as Record<string, unknown>, key);
  }
  return undefined;
}

export function listingValueForField(
  listing: Record<string, unknown> | undefined,
  marketplace: string,
  field: DraftField,
): string {
  if (!listing) return "";
  const key = normalizeLookupKey(field.label || field.key);
  let raw: unknown;
  if (marketplace === "general") {
    raw = valueFromRecord(listing, key);
  } else {
    const specifics = listing[`${marketplace}_specifics`];
    const record = specifics && typeof specifics === "object" && !Array.isArray(specifics)
      ? specifics as Record<string, unknown>
      : {};
    raw = valueFromRecord(record, key);
    if (raw == null && key === "when made") {
      const ebay = listing.ebay_specifics;
      raw = valueFromRecord(
        ebay && typeof ebay === "object" && !Array.isArray(ebay) ? ebay as Record<string, unknown> : {},
        "year manufactured",
      );
    }
    if (raw == null) raw = valueFromRecord(listing, key);
  }
  if (raw == null) return "";
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean).join(", ").trim();
  const text = String(raw).trim();
  if (isDoesNotApplyValue(text)) return "";
  return text;
}

function isDoesNotApplyValue(value: unknown): boolean {
  if (value == null) return false;
  if (Array.isArray(value)) {
    if (value.length === 0) return false;
    return value.every((item) => isDoesNotApplyValue(item));
  }
  return DOES_NOT_APPLY_RE.test(String(value).trim());
}

function notApplicableField(field: DraftField, value = "Does not apply"): DraftField {
  return {
    ...field,
    value,
    missing: false,
    notApplicable: true,
    leftover: undefined,
  };
}

export function leftoverGeneratedValue(
  listing: Record<string, unknown> | undefined,
  entry: FillLogEntry,
  field?: DraftField,
): string {
  return (
    listingValueForField(
      listing,
      entry.marketplace,
      field || { key: entry.field, label: entry.field, value: "", missing: true },
    ) || String(entry.value_preview || "").trim()
  );
}

function listingTitle(listing?: Record<string, unknown>): string {
  const title = String(listing?.title || "").trim();
  return title || "(untitled listing)";
}

function leftoverStatusLabel(entry: FillLogEntry): string {
  if (entry.status === "invalid") return "invalid-dropdown";
  const reason = String(entry.reason || "").toLowerCase();
  if (/invalid.*dropdown|not a valid option|no matching option|option not found|dropdown/.test(reason) && entry.status !== "filled") {
    return "invalid-dropdown";
  }
  if (/^no evidence\b/i.test(String(entry.reason || "").trim())) return "No evidence";
  return entry.status;
}

/** Vendoo's dropdown list for a field, so chat answers with a value the form takes. */
function optionsLine(
  dropdowns: DropdownForms | undefined,
  marketplace: string,
  field: string,
): string {
  const options = optionsForField(dropdowns, marketplace, field);
  if (!options?.length) return "";
  const shown = options.slice(0, MAX_PROMPT_OPTIONS);
  const rest = options.length - shown.length;
  return `\n  Options (use only these, verbatim): ${shown.join(" | ")}${rest > 0 ? ` (+${rest} more)` : ""}`;
}

export function leftoverFieldPrompt(
  listing: Record<string, unknown> | undefined,
  entry: FillLogEntry,
  currentValue: string,
  dropdowns?: DropdownForms,
): string {
  const title = listingTitle(listing);
  const current = String(currentValue || entry.value_preview || "").trim() || "(empty)";
  const reason = String(entry.reason || "").trim() || "(none)";
  return `Fix this Vendoo field for listing "${title}".

Listing: ${title}
Marketplace: ${entry.marketplace}
Field: ${entry.field}${optionsLine(dropdowns, entry.marketplace, entry.field)}
Current value: ${current}
Status: ${leftoverStatusLabel(entry)}
Failure reason: ${reason}

Generate a value for ONLY this field from the photos and current listing. Do not rewrite unrelated fields.

${OPTIONS_RULE}

Reply with JSON in this exact shape:

\`\`\`json
{"missing_fields":[{"marketplace":"${entry.marketplace}","field":"${entry.field}","value":"..."}]}
\`\`\`
`;
}

export function emptyFieldsPrompt(
  forms: DraftForm[],
  fromDraft: boolean,
  listing?: Record<string, unknown>,
  dropdowns?: DropdownForms,
): string {
  const title = listingTitle(listing);
  const rows: {
    marketplace: string;
    form: string;
    field: string;
    options: string;
    current: string;
    status: string;
    reason: string;
  }[] = [];
  for (const { form, field } of fieldsNeedingListingValues(forms, listing)) {
    const leftover = field.leftover;
    rows.push({
      marketplace: form.id,
      form: form.label,
      field: field.label,
      options: optionsLine(dropdowns, form.id, field.key) || optionsLine(dropdowns, form.id, field.label),
      current: listingTextForField(listing, form.id, field) || EMPTY_CELL,
      status: leftover ? leftoverStatusLabel(leftover) : "missing in listing",
      reason: leftover?.reason || (fromDraft
        ? "empty in listing JSON (field exists on the Vendoo form)"
        : "empty in listing JSON"),
    });
  }
  const limited = rows.slice(0, 50);
  const lines = limited.map((row) => `- Listing: ${title}
  Marketplace: ${row.marketplace}
  Field: ${row.field}${row.options}
  Current value: ${row.current}
  Status: ${row.status}
  Reason: ${row.reason}`);
  const intro = fromDraft
    ? `These fields are empty in the listing JSON for "${title}". Generate values for ONLY these fields from the photos and current listing. Do not rewrite the rest of the listing.`
    : `These listing fields are still empty on listing "${title}". Generate values for ONLY these fields from the photos and current listing. Do not rewrite the rest of the listing.`;
  return `${intro}

Reply with JSON in this exact shape:

\`\`\`json
{"missing_fields":[{"marketplace":"general","field":"SKU","value":"..."}]}
\`\`\`

Use the marketplace ids and field names exactly as listed. Studio updates the listing JSON and Forms/Fields UI when this reply finishes; filling the live Vendoo draft is a separate step.

${OPTIONS_RULE}

When the item's brand is not offered by a marketplace, answer "Other" for Depop and "No Brand/Not sure" for Mercari — never substitute a different brand.

Empty fields:
${lines.join("\n")}`;
}

/** One Ask-chat prompt for empty listing values and Apply/Send failures (deduped). */
export function askChatGapsPrompt(
  forms: DraftForm[],
  fromDraft: boolean,
  listing: Record<string, unknown> | undefined,
  failures: FillLogEntry[],
  dropdowns?: DropdownForms,
): string {
  const title = listingTitle(listing);
  const seen = new Set<string>();
  const lines: string[] = [];

  const pushLine = (line: string, key: string) => {
    if (seen.has(key) || lines.length >= 50) return;
    seen.add(key);
    lines.push(line);
  };

  for (const entry of failures) {
    const marketplace = String(entry.marketplace || "").toLowerCase();
    const field = entry.field || "";
    const key = `${marketplace}:${normalizeFieldName(field)}`;
    const current = leftoverGeneratedValue(listing, entry) || "(empty)";
    const reason = String(entry.reason || "").trim() || "(none)";
    pushLine(
      `- Listing: ${title}
  Marketplace: ${entry.marketplace}
  Field: ${field}${optionsLine(dropdowns, entry.marketplace, field)}
  Current value: ${current}
  Status: ${leftoverStatusLabel(entry)}
  Reason: ${reason}`,
      key,
    );
  }

  for (const { form, field } of fieldsNeedingListingValues(forms, listing)) {
    const leftover = field.leftover;
    const key = `${form.id}:${fieldMatchKey(field)}`;
    pushLine(
      `- Listing: ${title}
  Marketplace: ${form.id}
  Field: ${field.label}${optionsLine(dropdowns, form.id, field.key) || optionsLine(dropdowns, form.id, field.label)}
  Current value: ${listingTextForField(listing, form.id, field) || EMPTY_CELL}
  Status: ${leftover ? leftoverStatusLabel(leftover) : "missing in listing"}
  Reason: ${leftover?.reason || (fromDraft
    ? "empty in listing JSON (field exists on the Vendoo form)"
    : "empty in listing JSON")}`,
      key,
    );
  }

  const emptyCount = fieldsNeedingListingValues(forms, listing).length;
  const failCount = failures.length;
  const parts: string[] = [];
  if (emptyCount) parts.push(`${emptyCount} empty`);
  if (failCount) parts.push(`${failCount} failed`);
  const mix = parts.join(" + ") || "listed";

  return `Fill these listing fields for "${title}" (${mix}). Generate values for ONLY these fields from the photos and current listing. Do not rewrite unrelated fields.

Reply with JSON in this exact shape:

\`\`\`json
{"missing_fields":[{"marketplace":"ebay","field":"Brand","value":"..."}]}
\`\`\`

Use the marketplace ids and field names exactly as listed. Studio updates the listing JSON and Forms/Fields UI when this reply finishes; filling the live Vendoo draft is a separate step.

${OPTIONS_RULE}

When the item's brand is not offered by a marketplace, answer "Other" for Depop and "No Brand/Not sure" for Mercari — never substitute a different brand.

Fields:
${lines.join("\n") || "- (none)"}`;
}

function allowedMarketplaceIds(selected?: string[]): Set<string> {
  const chosen = selected ?? DEFAULT_SELECTED_MARKETPLACES;
  return new Set(["general", ...chosen]);
}

export function leftoverEntries(report: FillLogReport): FillLogEntry[] {
  const rows: FillLogEntry[] = [];
  for (const group of Object.values(report.by_marketplace)) {
    for (const entry of group.entries) {
      if (!FILLABLE_STATUSES.has(entry.status)) continue;
      // Already-correct controls are successes, not leftovers to retry.
      if (isAlreadySetEntry(entry)) continue;
      if (isAccountSettingField(entry.field)) continue;
      rows.push(entry);
    }
  }
  return rows.sort((left, right) => {
    const statusDelta = STATUS_ORDER.indexOf(left.status) - STATUS_ORDER.indexOf(right.status);
    if (statusDelta !== 0) return statusDelta;
    return `${left.marketplace} ${left.field}`.localeCompare(`${right.marketplace} ${right.field}`);
  });
}

export function fillFailureEntries(report: FillLogReport): FillLogEntry[] {
  return leftoverEntries(report).filter((entry) => FILL_FAILURE_STATUSES.has(entry.status));
}

export function patchableChangedFields(
  forms: DraftForm[],
  listing: Record<string, unknown> | undefined,
  values: Record<string, string> = {},
): { id?: string; marketplace: string; field: string; value: string }[] {
  return forms.flatMap((form) =>
    form.fields
      // Empty-on-Vendoo fields and mismatches only — never re-walk matching controls.
      .filter((field) => !field.listingOnly && !field.notApplicable && !isUnfillableField(field))
      .map((field) => {
        const leftover = field.leftover;
        const typed = leftover ? String(values[leftover.id] || "").trim() : "";
        const value = typed || listingValueForField(listing, form.id, field);
        if (!fieldNeedsVendooApply(field, value)) return null;
        return leftover
          ? { id: leftover.id, marketplace: form.id, field: leftover.field || field.label, value }
          : { marketplace: form.id, field: field.label, value };
      })
      .filter((item): item is { id?: string; marketplace: string; field: string; value: string } => Boolean(item)),
  );
}

function overlayListingForms(forms: DraftForm[], listingForms: DraftForm[]): DraftForm[] {
  if (!listingForms.length) return forms;
  const byId = new Map(listingForms.map((form) => [form.id, form]));
  const seenForms = new Set(forms.map((form) => form.id));
  const merged = forms.map((form) => {
    const listingForm = byId.get(form.id);
    if (!listingForm) return form;
    const listingByKey = new Map(
      listingForm.fields.map((field) => [fieldMatchKey(field), field]),
    );
    // Keep Vendoo draft emptiness authoritative. Listing/chat values are only
    // candidates for Fill — never paint them as already filled on Vendoo.
    // Does-not-apply listing values become yellow N/A rows instead of red missing.
    const fields = form.fields.map((field) => {
      const listingFieldRow = listingByKey.get(fieldMatchKey(field));
      if (listingFieldRow?.notApplicable || isDoesNotApplyValue(listingFieldRow?.value)) {
        return notApplicableField({ ...field, section: field.section || listingFieldRow?.section });
      }
      if (field.notApplicable || isDoesNotApplyValue(field.value)) {
        return notApplicableField(field);
      }
      return field;
    });
    const seen = new Set(fields.map((field) => fieldMatchKey(field)).filter(Boolean));
    const extrasSection = form.id === "ebay" || form.id === "etsy" ? "Category" : "Item specifics";
    const extras: DraftField[] = [];
    for (const field of listingForm.fields) {
      const key = fieldMatchKey(field);
      if (!key || seen.has(key)) continue;
      if (field.notApplicable || isDoesNotApplyValue(field.value)) {
        seen.add(key);
        extras.push(notApplicableField({
          ...field,
          section: extrasSection,
        }));
        continue;
      }
      if (fieldIsMissing(field.value, field.label)) continue;
      seen.add(key);
      extras.push({
        ...field,
        value: "",
        section: extrasSection,
        missing: true,
        listingOnly: true,
      });
    }
    if (!extras.length) return toForm(form.id, fields, form.liveStatus);
    const next = [...fields];
    let insertAt = next.length;
    for (let i = 0; i < next.length; i += 1) {
      if (next[i].section === extrasSection) insertAt = i + 1;
    }
    next.splice(insertAt, 0, ...extras);
    return toForm(form.id, next, form.liveStatus);
  });
  for (const listingForm of listingForms) {
    if (seenForms.has(listingForm.id) || !listingForm.fields.length) continue;
    merged.push(listingForm);
  }
  return merged;
}

export function sourceFormsForJob(
  item: Record<string, unknown> | undefined,
  report: FillLogReport | undefined,
  listing: Record<string, unknown> | undefined,
  selectedMarketplaces?: string[],
): { sourceForms: DraftForm[]; fromVendooDraft: boolean } {
  const enabled = allowedMarketplaceIds(selectedMarketplaces);
  const draftForms = item ? formsFromDraft(item, report) : [];
  const fillForms = report && Object.keys(report.by_marketplace).length ? formsFromFillLog(report) : [];
  const listingForms = formsFromListing(listing);
  const sourceForms = overlayListingForms(
    draftForms.length ? draftForms : fillForms.length ? fillForms : listingForms,
    listingForms,
  ).filter((form) => enabled.has(form.id) || Boolean(form.liveStatus));
  return { sourceForms, fromVendooDraft: draftForms.length > 0 };
}


export function marketplaceLabel(id: string): string {
  return MARKETPLACE_LABELS[id] || id.charAt(0).toUpperCase() + id.slice(1);
}

export function liveStatusClass(status?: string): string {
  const key = (status || "").toLowerCase().replace(/\s+/g, "-");
  if (key === "listed" || key === "complete" || key === "sold") return "is-listed";
  if (key === "not-listed" || key === "draft" || key === "incomplete") return "is-not-listed";
  if (key === "failed") return "is-failed";
  return "";
}

/** Map Vendoo's API ``listings.<mp>.status`` object onto the nav chip labels. */
export function statusFromListingStatus(status: unknown): string | undefined {
  if (!status || typeof status !== "object" || Array.isArray(status)) return undefined;
  const row = status as Record<string, unknown>;
  // Real drafts from get_item use { notListed: true }, not { listed: false }.
  if (row.sold === true) return "SOLD";
  if (row.listed === true) return "LISTED";
  if (row.notListed === true || row.listed === false) return "NOT LISTED";
  if (row.incomplete === true) return "INCOMPLETE";
  if (row.failed === true) return "FAILED";
  if (row.pending === true) return "PENDING";
  return undefined;
}

function normalizeLiveStatus(raw: unknown): string | undefined {
  if (typeof raw !== "string") return undefined;
  const cleaned = raw.replace(/\s+/g, " ").trim().toUpperCase();
  if (!cleaned || cleaned === "BETA" || cleaned === "NEW" || cleaned === "ALPHA") return undefined;
  return cleaned;
}

export function liveStatusForMarketplace(
  id: string,
  item: Record<string, unknown> | null | undefined,
): string | undefined {
  const statuses = item?.statuses;
  if (statuses && typeof statuses === "object" && !Array.isArray(statuses)) {
    const scraped = normalizeLiveStatus((statuses as Record<string, unknown>)[id]);
    if (scraped) return scraped;
  }
  if (id === "general") return undefined;
  const listings = item?.listings && typeof item.listings === "object"
    ? item.listings as Record<string, unknown>
    : undefined;
  const listing = listings?.[id] as Record<string, unknown> | undefined;
  return statusFromListingStatus(listing?.status);
}


type FieldSpec = { keys: string[]; label: string; always?: boolean };
type SectionSpec = { label: string; fields?: FieldSpec[]; extras?: boolean };

const FIELD_NAME_ALIASES: Record<string, string> = {
  "category v2": "category",
  categoryv2: "category",
  "category path": "category",
  categorypath: "category",
  "us size": "size",
  "size option": "size",
  "size option value": "size",
  "size type": "size type",
  "size scale": "size type",
  "size scale value": "size type",
  "listing price": "price",
  "buy it now price": "price",
  "cost of goods": "cost",
  "vendoo labels": "labels",
  "vendoo internal notes": "notes",
  "internal notes": "notes",
  "weight lbs": "pounds",
  "weight (lbs)": "pounds",
  "weight lb": "pounds",
  "weight pounds": "pounds",
  "package weight (lb)": "pounds",
  "package weight lb": "pounds",
  "weight ounces": "ounces",
  "weight (oz)": "ounces",
  "weight oz": "ounces",
  "package weight (oz)": "ounces",
  "package weight oz": "ounces",
  color: "primary color",
  zipcode: "zip code",
  zip: "zip code",
  "who made it": "who made",
  whomade: "who made",
  "what is": "what is it",
  whatisit: "what is it",
  "when was it made": "when made",
  whenmade: "when made",
  "style tags": "style tags",
  "style tag": "style tags",
  "shipping label": "shipping label",
  "accept return": "accept returns",
  "payment met": "payment method",
  "condition desc": "condition description",
  "size group": "size grouping",
  "body fit": "size grouping",
  "country region of manufacture": "country of origin",
  "fabric pattern": "pattern",
};

export function normalizeFieldName(value: string): string {
  const key = String(value || "")
    .replace(/^(ebay|etsy|poshmark|mercari|depop|vendoo)\s+/i, "")
    .replace(/[*?]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_.-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
  return FIELD_NAME_ALIASES[key] || key;
}

export function fieldMatchKey(field: DraftField): string {
  return normalizeFieldName(field.label) || normalizeFieldName(field.key.split(".").pop() || field.key);
}

/** Cascade fields that must stay visible so optionals can mount on Vendoo. */
const PROTECTED_EBAY_CORE_NAMES = new Set(
  EBAY_CATEGORY_CORE.filter((field) =>
    ["department", "size", "sizeType", "type"].includes(field.key),
  ).map((field) => normalizeFieldName(field.label)),
);

export function isProtectedEbayField(marketplace: string, field: DraftField | string): boolean {
  if (marketplace.toLowerCase() !== "ebay") return false;
  const name =
    typeof field === "string" ? normalizeFieldName(field) : fieldMatchKey(field) || normalizeFieldName(field.label);
  return PROTECTED_EBAY_CORE_NAMES.has(name);
}

const SHARED_ITEM_FIELDS: FieldSpec[] = [
  { keys: ["title"], label: "Title" },
  { keys: ["description"], label: "Description" },
  { keys: ["brand"], label: "Brand" },
  { keys: ["condition"], label: "Condition" },
  { keys: ["primary color"], label: "Primary Color" },
  { keys: ["secondary color"], label: "Secondary Color" },
  { keys: ["quantity"], label: "Quantity" },
  { keys: ["sku"], label: "SKU" },
  { keys: ["price"], label: "Price" },
];

const PACKAGE_FIELDS: FieldSpec[] = [
  { keys: ["pounds"], label: "Package Weight (lb)" },
  { keys: ["ounces"], label: "Package Weight (oz)" },
  { keys: ["length"], label: "Length" },
  { keys: ["width"], label: "Width" },
  { keys: ["height"], label: "Height" },
];

/** Empty optional category fields Vendoo keeps off the API until filled. */
const EBAY_OPTIONAL_FIELDS: FieldSpec[] = EBAY_CATEGORY_OPTIONALS.map((field) => ({
  keys: [normalizeFieldName(field.label), normalizeFieldName(field.key)],
  label: field.label,
  always: true,
}));

const EBAY_CATEGORY_CORE_FIELDS: FieldSpec[] = [
  { keys: ["category"], label: "Category", always: true },
  ...EBAY_CATEGORY_CORE.map((field) => ({
    keys: [normalizeFieldName(field.label), normalizeFieldName(field.key)],
    label: field.label,
    always: true,
  })),
];

const ETSY_OPTIONAL_FIELDS: FieldSpec[] = ETSY_CATEGORY_OPTIONALS.map((field) => ({
  keys: [normalizeFieldName(field.label), normalizeFieldName(field.key), ...(field.key === "pattern" ? ["fabric pattern"] : [])],
  label: field.label,
  always: true,
}));

const DEPOP_OPTIONAL_FIELDS: FieldSpec[] = DEPOP_CATEGORY_OPTIONALS.map((field) => ({
  keys: [normalizeFieldName(field.label), normalizeFieldName(field.key)],
  label: field.label,
  always: true,
}));

const FORM_LAYOUTS: Record<string, SectionSpec[]> = {
  general: [
    { label: "Photos", fields: [{ keys: ["photos", "images"], label: "Photos", always: false }] },
    {
      label: "Item Details",
      fields: [
        { keys: ["title"], label: "Title", always: true },
        { keys: ["description"], label: "Description", always: true },
        { keys: ["brand"], label: "Brand", always: true },
        { keys: ["condition"], label: "Condition", always: true },
        { keys: ["primary color"], label: "Primary Color", always: true },
        { keys: ["secondary color"], label: "Secondary Color", always: true },
        { keys: ["sku"], label: "SKU", always: true },
        { keys: ["zip code"], label: "Zip Code", always: true },
        { keys: ["quantity"], label: "Quantity" },
      ],
    },
    {
      label: "Category",
      fields: [
        { keys: ["category"], label: "Category", always: true },
        { keys: ["size"], label: "US Size", always: true },
        { keys: ["size type"], label: "Size Type", always: true },
      ],
    },
    { label: "Package Details", fields: PACKAGE_FIELDS.map((field) => ({ ...field, always: true })) },
    {
      label: "Price",
      fields: [
        { keys: ["price"], label: "Listing Price", always: true },
        { keys: ["cost"], label: "Cost of Goods", always: true },
      ],
    },
    {
      label: "Additional Details",
      fields: [
        { keys: ["tags"], label: "Tags" },
        { keys: ["labels"], label: "Vendoo Labels", always: true },
        { keys: ["notes"], label: "Vendoo Internal Notes", always: true },
      ],
    },
    { label: "More fields", extras: true },
  ],
  ebay: [
    {
      label: "Item Details",
      fields: [
        { keys: ["title"], label: "Title" },
        { keys: ["description"], label: "Description" },
        { keys: ["brand"], label: "Brand" },
        { keys: ["primary color"], label: "Primary Color" },
        { keys: ["secondary color"], label: "Secondary Color" },
        { keys: ["quantity"], label: "Quantity" },
        { keys: ["sku"], label: "SKU" },
        { keys: ["price"], label: "Price" },
      ],
    },
    {
      label: "Category",
      fields: [
        ...EBAY_CATEGORY_CORE_FIELDS,
        ...EBAY_OPTIONAL_FIELDS,
      ],
      extras: true,
    },
    { label: "Package Details", fields: PACKAGE_FIELDS },
    {
      label: "Shipping & returns",
      fields: [
        { keys: ["shipping"], label: "Shipping" },
        { keys: ["returns"], label: "Returns" },
      ],
    },
  ],
  etsy: [
    { label: "Item Details", fields: SHARED_ITEM_FIELDS },
    {
      label: "Listing info",
      fields: [
        { keys: ["who made"], label: "Who made it" },
        { keys: ["what is it"], label: "What is it" },
        { keys: ["when made"], label: "When was it made" },
      ],
    },
    {
      label: "Category",
      fields: [
        { keys: ["category"], label: "Category", always: true },
        { keys: ["size"], label: "Size", always: true },
        ...ETSY_OPTIONAL_FIELDS,
      ],
      extras: true,
    },
    {
      label: "Tags & materials",
      fields: [
        { keys: ["tags"], label: "Tags" },
        { keys: ["materials"], label: "Materials" },
      ],
    },
  ],
  poshmark: [
    { label: "Item Details", fields: SHARED_ITEM_FIELDS },
    { label: "Category", fields: [{ keys: ["category"], label: "Category" }, { keys: ["size"], label: "Size" }] },
    {
      label: "Additional Details",
      fields: [
        { keys: ["style tags"], label: "Style Tags" },
        { keys: ["original price"], label: "Original Price" },
      ],
    },
    { label: "Item specifics", extras: true },
  ],
  mercari: [
    { label: "Item Details", fields: SHARED_ITEM_FIELDS },
    { label: "Category", fields: [{ keys: ["category"], label: "Category" }, { keys: ["size"], label: "Size" }] },
    { label: "Shipping", fields: [{ keys: ["shipping label"], label: "Shipping Label" }] },
    { label: "Item specifics", extras: true },
  ],
  depop: [
    { label: "Item Details", fields: SHARED_ITEM_FIELDS },
    { label: "Category", fields: [{ keys: ["category"], label: "Category" }, { keys: ["size"], label: "Size" }] },
    {
      label: "Optional fields",
      fields: DEPOP_OPTIONAL_FIELDS,
    },
    { label: "Item specifics", extras: true },
  ],
};

const DEFAULT_FORM_LAYOUT: SectionSpec[] = [
  { label: "Item Details", fields: SHARED_ITEM_FIELDS },
  { label: "Category", fields: [{ keys: ["category"], label: "Category" }, { keys: ["size"], label: "Size" }] },
  { label: "Package Details", fields: PACKAGE_FIELDS },
  { label: "Item specifics", extras: true },
];

function organizeFields(marketplace: string, fields: DraftField[], leftovers: FillLogEntry[] = []): DraftField[] {
  const layout = FORM_LAYOUTS[marketplace] || DEFAULT_FORM_LAYOUT;
  const unused = new Map<string, DraftField[]>();
  for (const field of fields) {
    const key = fieldMatchKey(field);
    if (!key) continue;
    const bucket = unused.get(key) || [];
    bucket.push(field);
    unused.set(key, bucket);
  }
  const leftoverPool = leftovers.slice();
  const takeField = (keys: string[]): DraftField | undefined => {
    for (const key of keys) {
      const bucket = unused.get(key);
      if (bucket?.length) return bucket.shift();
    }
    return undefined;
  };
  const takeLeftover = (keys: string[]): FillLogEntry | undefined => {
    const wants = new Set(keys);
    const index = leftoverPool.findIndex((entry) => wants.has(normalizeFieldName(entry.field)));
    if (index < 0) return undefined;
    return leftoverPool.splice(index, 1)[0];
  };
  const attachLeftover = (field: DraftField | undefined): FillLogEntry | undefined => {
    if (field?.leftover && leftoverPool.includes(field.leftover)) {
      leftoverPool.splice(leftoverPool.indexOf(field.leftover), 1);
      return field.leftover;
    }
    return takeLeftover(field ? [fieldMatchKey(field)] : []);
  };
  const placed = new Map<string, DraftField[]>();
  let extrasSection = "Item specifics";

  for (const section of layout) {
    const rows: DraftField[] = placed.get(section.label) || [];
    if (section.extras) extrasSection = section.label;
    for (const spec of section.fields || []) {
      const found = takeField(spec.keys);
      const leftover = found
        ? attachLeftover(found) || takeLeftover([...spec.keys, normalizeFieldName(spec.label)])
        : takeLeftover([...spec.keys, normalizeFieldName(spec.label)]);
      if (found) {
        // Only the live Vendoo value counts as filled. Leftover previews are
        // proposed fill values and must stay in the red/missing column.
        if (found.notApplicable || isDoesNotApplyValue(found.value) || leftover?.status === "not_applicable") {
          rows.push(notApplicableField({
            ...found,
            label: spec.label,
            section: section.label,
            value: "",
            missing: false,
          }));
          continue;
        }
        const value = fieldDisplayValue(found.value, spec.label);
        const pendingLeftover =
          value
            ? undefined
            : leftover && FILLABLE_STATUSES.has(leftover.status)
              ? leftover
              : found.leftover;
        rows.push({
          ...found,
          label: spec.label,
          section: section.label,
          leftover: pendingLeftover && FILLABLE_STATUSES.has(pendingLeftover.status) ? pendingLeftover : undefined,
          missing: !value,
          notApplicable: false,
          value,
        });
        continue;
      }
      if (leftover?.status === "not_applicable") {
        rows.push(notApplicableField({
          key: leftover.id || `${marketplace}.${spec.keys[0]}`,
          label: spec.label,
          value: "",
          missing: false,
          section: section.label,
        }));
        continue;
      }
      if (spec.always || leftover) {
        const pendingLeftover = leftover && FILLABLE_STATUSES.has(leftover.status) ? leftover : undefined;
        rows.push({
          key: leftover?.id || `${marketplace}.${spec.keys[0]}`,
          label: spec.label,
          value: "",
          missing: true,
          leftover: pendingLeftover,
          section: section.label,
        });
      }
    }
    placed.set(section.label, rows);
  }

  const namedExtras = placed.get(extrasSection) || [];
  const extraRows: DraftField[] = [...unused.values()].flat().map((field) => {
    const leftover = attachLeftover(field);
    if (field.notApplicable || isDoesNotApplyValue(field.value) || leftover?.status === "not_applicable") {
      return notApplicableField({
        ...field,
        section: extrasSection,
        value: "",
        missing: false,
      });
    }
    const value = fieldDisplayValue(field.value, field.label);
    const pendingLeftover =
      value
        ? undefined
        : leftover && FILLABLE_STATUSES.has(leftover.status)
          ? leftover
          : field.leftover;
    return {
      ...field,
      leftover: pendingLeftover && FILLABLE_STATUSES.has(pendingLeftover.status) ? pendingLeftover : undefined,
      missing: !value,
      notApplicable: false,
      value,
      section: extrasSection,
    };
  });
  const seenExtras = new Set([...namedExtras, ...extraRows].map((field) => fieldMatchKey(field)));
  extraRows.push(...leftoverPool.flatMap((entry) => {
    const key = normalizeFieldName(entry.field);
    if (key && seenExtras.has(key)) return [];
    if (key) seenExtras.add(key);
    const label = entry.field.replace(/^(ebay|etsy|poshmark|mercari|depop|vendoo)\s+/i, "").trim() || entry.field;
    if (entry.status === "not_applicable") {
      return [notApplicableField({
        key: entry.id,
        label,
        value: "",
        missing: false,
        section: extrasSection,
      })];
    }
    const pending = FILLABLE_STATUSES.has(entry.status);
    return [{
      key: entry.id,
      label,
      value: "",
      missing: pending || !fieldDisplayValue(entry.value_preview || "", label),
      leftover: pending ? entry : undefined,
      section: extrasSection,
    }];
  }));
  extraRows.sort((left, right) => left.label.localeCompare(right.label));
  placed.set(extrasSection, [...namedExtras, ...extraRows]);

  const seenKeys = new Set<string>();
  return layout.flatMap((section) => placed.get(section.label) || []).filter((field) => {
    const key = `${field.section}|${fieldMatchKey(field)}|${field.key}`;
    if (seenKeys.has(key)) return false;
    seenKeys.add(key);
    return true;
  });
}

export function groupFields(fields: DraftField[]): { label: string; fields: DraftField[] }[] {
  const groups: { label: string; fields: DraftField[] }[] = [];
  for (const field of fields) {
    const label = field.section || "";
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.fields.push(field);
    else groups.push({ label, fields: [field] });
  }
  return groups;
}

function fieldLabel(key: string): string {
  return key
    .replace(/^[0-9a-f]{8,}_/i, "")
    .replace(/^\d+_/, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_.-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();
}

function isEmptyValue(value: unknown): boolean {
  if (value == null) return true;
  if (typeof value === "boolean") return false;
  if (typeof value === "number") return false;
  if (typeof value === "string") return value.trim() === "";
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.displayName === "string") return record.displayName.trim() === "";
    if (Array.isArray(record.displayPath)) return record.displayPath.length === 0;
    if ("value" in record) return isEmptyValue(record.value);
    if (record.option) return isEmptyValue(record.option);
    return Object.values(record).every(isEmptyValue);
  }
  return true;
}

/** MUI empty selects often render the field label itself as the visible text. */
function isPlaceholderFieldValue(value: unknown, label?: string): boolean {
  if (isEmptyValue(value)) return true;
  if (typeof value !== "string") return false;
  const shown = value
    .trim()
    .replace(/[*?]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!shown) return true;
  const lower = shown.toLowerCase();
  if (/^(select|choose|pick|----)\b/.test(lower)) return true;
  if (label) {
    const labelNorm = label
      .trim()
      .replace(/[*?]+$/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
    if (labelNorm && lower === labelNorm) return true;
  }
  return /^(department|type|size|size type|condition|brand|primary color|secondary color|shipping label|category)$/i.test(
    lower,
  );
}

function fieldDisplayValue(value: unknown, label?: string): string {
  if (isPlaceholderFieldValue(value, label)) return "";
  return displayValue(value);
}

function fieldIsMissing(value: unknown, label?: string): boolean {
  return isPlaceholderFieldValue(value, label);
}

function displayValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    if (value.length === 0) return "";
    if (value.every((item) => typeof item === "string" || typeof item === "number")) return value.join(", ");
    if (value.some((item) => item && typeof item === "object" && "url" in (item as object))) {
      return `${value.length} photo${value.length === 1 ? "" : "s"}`;
    }
    return `${value.length} items`;
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.displayName === "string" && record.displayName.trim()) return record.displayName.trim();
    if (Array.isArray(record.displayPath) && record.displayPath.length) return record.displayPath.map(String).join(" > ");
    if (record.option && !isEmptyValue(record.option)) return displayValue(record.option);
    if (record.scale && record.option) {
      const size = displayValue(record.option);
      const scale = displayValue(record.scale);
      return [size, scale].filter(Boolean).join(" · ");
    }
    if ("value" in record) return displayValue(record.value);
    const pounds = record.pounds ?? record.lb;
    const ounces = record.ounces ?? record.oz;
    if (pounds != null || ounces != null) {
      return [pounds != null ? `${pounds} lb` : "", ounces != null ? `${ounces} oz` : ""].filter(Boolean).join(" ");
    }
    const length = record.length;
    const width = record.width;
    const height = record.height;
    if (length != null || width != null || height != null) {
      return [length, width, height].filter((part) => part != null && String(part) !== "").join(" × ");
    }
    const nested = Object.entries(record)
      .filter(([key]) => !SKIP_KEYS.has(key.toLowerCase()))
      .map(([key, nestedValue]) => {
        const shown = displayValue(nestedValue);
        return shown ? `${fieldLabel(key)} ${shown}` : "";
      })
      .filter(Boolean);
    return nested.join(" · ");
  }
  return String(value);
}

/** Scraped on-page labels win over the key, which for Etsy is a bare taxonomy id. */
type FieldLabels = Record<string, string> | undefined;

/**
 * The Vendoo API keeps the category prefix (554_148789511893) while the DOM
 * scrape strips it (148789511893), and both can survive the merge, so try the
 * stripped form too.
 */
function strippedFieldKey(key: string): string {
  return key.replace(/^[0-9a-f]{8,}_/i, "").replace(/^\d+_/, "");
}

function labelFor(key: string, path: string, labels: FieldLabels): string {
  const scraped = labels && (labels[path] || labels[key] || labels[strippedFieldKey(key)]);
  return (typeof scraped === "string" && scraped.trim()) || fieldLabel(key);
}

function flattenFields(value: unknown, prefix = "", labels: FieldLabels = undefined): DraftField[] {
  if (value == null || typeof value !== "object" || Array.isArray(value)) {
    if (!prefix) return [];
    const label = labelFor(prefix.split(".").pop() || prefix, prefix, labels);
    const shown = fieldDisplayValue(value, label);
    return [{ key: prefix, label, value: shown, missing: fieldIsMissing(value, label) }];
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.displayName === "string" ||
    Array.isArray(record.displayPath) ||
    record.option ||
    (record.value != null && Object.keys(record).length <= 3)
  ) {
    const label = labelFor(prefix.split(".").pop() || prefix || "Value", prefix, labels);
    const shown = fieldDisplayValue(record, label);
    return [{
      key: prefix || "value",
      label,
      value: shown,
      missing: fieldIsMissing(record, label),
    }];
  }
  const rows: DraftField[] = [];
  for (const [key, nested] of Object.entries(record)) {
    if (SKIP_KEYS.has(key.toLowerCase())) continue;
    if (key === "category" && record.categoryV2) continue;
    const path = prefix ? `${prefix}.${key}` : key;
    if (nested && typeof nested === "object" && !Array.isArray(nested)) {
      const nestedRecord = nested as Record<string, unknown>;
      if (nestedRecord.option && nestedRecord.scale) {
        rows.push({
          key: `${path}.option`,
          label: "US Size",
          value: fieldDisplayValue(nestedRecord.option, "US Size"),
          missing: fieldIsMissing(nestedRecord.option, "US Size"),
        });
        rows.push({
          key: `${path}.scale`,
          label: "Size Type",
          value: fieldDisplayValue(nestedRecord.scale, "Size Type"),
          missing: fieldIsMissing(nestedRecord.scale, "Size Type"),
        });
        continue;
      }
      const leaf =
        typeof nestedRecord.displayName === "string" ||
        Array.isArray(nestedRecord.displayPath) ||
        nestedRecord.option ||
        ("value" in nestedRecord && Object.keys(nestedRecord).length <= 3);
      if (!leaf && !isEmptyValue(nested) && Object.keys(nestedRecord).length > 1) {
        rows.push(...flattenFields(nested, path, labels));
        continue;
      }
    }
    const label = labelFor(key, path, labels);
    const shown = fieldDisplayValue(nested, label);
    rows.push({
      key: path,
      label,
      value: shown,
      missing: fieldIsMissing(nested, label),
    });
  }
  return rows;
}

function listingSection(listing: Record<string, unknown> | undefined): unknown {
  if (!listing || typeof listing !== "object") return listing;
  const rest = { ...listing };
  const overrides = rest.overrides;
  const specifics = rest.marketplaceSpecifics;
  const category = rest.categorySpecifics;
  delete rest.overrides;
  delete rest.marketplaceSpecifics;
  delete rest.categorySpecifics;
  delete rest.fieldLabels;
  delete rest.type;
  return {
    ...rest,
    ...(overrides && typeof overrides === "object" && !Array.isArray(overrides) ? overrides as object : {}),
    ...(specifics && typeof specifics === "object" && !Array.isArray(specifics) ? specifics as object : {}),
    ...(category && typeof category === "object" && !Array.isArray(category) ? category as object : {}),
  };
}

/**
 * The extension records on-page labels for keys the id can't name, under
 * `fieldLabels` as "<bucket>.<key>". listingSection flattens the buckets away,
 * so re-key them to the bare field key that flattenFields will see.
 *
 * Always attach scraped labels — even when a camelCase twin exists. Duplicate
 * taxonomy-id rows are dropped later by withoutTaxonomyIdNoise; keeping the raw
 * id visible was what made Etsy Fields look like random numbers.
 */
function listingFieldLabels(listing: Record<string, unknown> | undefined, _section?: unknown): FieldLabels {
  const raw = listing?.fieldLabels;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const out: Record<string, string> = {};
  for (const [path, label] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof label !== "string" || !label.trim()) continue;
    const text = label.trim();
    out[path] = text;
    const bare = path.split(".").slice(1).join(".");
    if (bare) out[bare] = text;
  }
  return Object.keys(out).length ? out : undefined;
}

/** Etsy category specifics use bare taxonomy ids (148789511893) as DOM keys. */
function isLetterlessFieldKey(key: string): boolean {
  const leaf = key.split(".").pop() || key;
  return Boolean(leaf) && !/[A-Za-z]/.test(leaf);
}

/**
 * Hide taxonomy-id noise: unlabeled digit keys, and labeled digit keys that
 * duplicate a real named sibling (closure + 325502673988 both meaning Closure).
 */
function withoutTaxonomyIdNoise(fields: DraftField[]): DraftField[] {
  const namedLabels = new Set(
    fields
      .filter((field) => !isLetterlessFieldKey(field.key))
      .map((field) => normalizeFieldName(field.label))
      .filter(Boolean),
  );
  return fields.filter((field) => {
    if (!isLetterlessFieldKey(field.key)) return true;
    const labelName = normalizeFieldName(field.label);
    if (!labelName || !/[a-z]/.test(labelName)) return false;
    if (namedLabels.has(labelName)) return false;
    return true;
  });
}

function deepMergeRecords(
  base: Record<string, unknown> | undefined,
  overlay: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(overlay || {})) {
    const prev = out[key];
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      prev &&
      typeof prev === "object" &&
      !Array.isArray(prev)
    ) {
      out[key] = deepMergeRecords(prev as Record<string, unknown>, value as Record<string, unknown>);
      continue;
    }
    // Prefer a real value over an empty scrape/API placeholder so Refresh does
    // not wipe fields that are already present on either side.
    if (isEmptyValue(value) && !isEmptyValue(prev)) continue;
    out[key] = value;
  }
  return out;
}

export function mergeDraftItem(draft: {
  item?: unknown;
  form?: unknown;
  statuses?: unknown;
} | undefined): Record<string, unknown> | undefined {
  if (!draft) return undefined;
  const item = draft.item && typeof draft.item === "object" && !Array.isArray(draft.item)
    ? draft.item as Record<string, unknown>
    : {};
  const form = draft.form && typeof draft.form === "object" && !Array.isArray(draft.form)
    ? draft.form as Record<string, unknown>
    : {};
  if (!Object.keys(item).length && !Object.keys(form).length) return undefined;
  const formStatuses = form.statuses && typeof form.statuses === "object" && !Array.isArray(form.statuses)
    ? form.statuses as Record<string, unknown>
    : undefined;
  const draftStatuses = draft.statuses && typeof draft.statuses === "object" && !Array.isArray(draft.statuses)
    ? draft.statuses as Record<string, unknown>
    : undefined;
  // Deep-merge so empty optional categorySpecifics scraped from the page are
  // kept when the API omits those keys.
  return {
    ...form,
    ...item,
    generalDetails: deepMergeRecords(
      (form.generalDetails as Record<string, unknown> | undefined),
      (item.generalDetails as Record<string, unknown> | undefined),
    ),
    listings: deepMergeRecords(
      (form.listings as Record<string, unknown> | undefined),
      (item.listings as Record<string, unknown> | undefined),
    ),
    images: item.images ?? form.images,
    statuses: draftStatuses || formStatuses,
  };
}

function fillLogEntriesForMarket(report: FillLogReport | undefined, marketplace: string): FillLogEntry[] {
  return report?.by_marketplace[marketplace]?.entries || [];
}

function toForm(id: string, fields: DraftField[], liveStatus?: string): DraftForm {
  return {
    id,
    label: marketplaceLabel(id),
    fields,
    filled: fields.filter((field) => !field.missing && !field.notApplicable).length,
    missing: fields.filter((field) => field.missing && !field.notApplicable).length,
    notApplicable: fields.filter((field) => field.notApplicable).length,
    liveStatus,
  };
}

function formsFromDraft(item: Record<string, unknown> | null | undefined, report?: FillLogReport): DraftForm[] {
  const leftovers = report ? leftoverEntries(report) : [];
  const forms: DraftForm[] = [];
  const general = item?.generalDetails && typeof item.generalDetails === "object"
    ? flattenFields(item.generalDetails)
    : [];
  if (item?.images && Array.isArray(item.images) && !general.some((field) => field.key === "images")) {
    general.unshift({
      key: "images",
      label: "Photos",
      value: displayValue(item.images),
      missing: item.images.length === 0,
    });
  } else if ((item?.generalDetails as Record<string, unknown> | undefined)?.images) {
    const images = (item?.generalDetails as Record<string, unknown> | undefined)?.images;
    if (!general.some((field) => field.key === "images" || field.label === "Photos")) {
      general.unshift({
        key: "images",
        label: "Photos",
        value: displayValue(images),
        missing: isEmptyValue(images),
      });
    }
  }
  forms.push(toForm(
    "general",
    organizeFields("general", general, fillLogEntriesForMarket(report, "general")),
    liveStatusForMarketplace("general", item),
  ));

  const listings = item?.listings && typeof item.listings === "object"
    ? item.listings as Record<string, unknown>
    : {};
  const leftoverMarkets = new Set(leftovers.map((entry) => entry.marketplace.toLowerCase()));
  const scrapedStatuses = item?.statuses && typeof item.statuses === "object" && !Array.isArray(item.statuses)
    ? item.statuses as Record<string, unknown>
    : {};
  // Always include the standard marketplaces so empty Category optionals still
  // appear even when the Vendoo API omits an empty listings.ebay object.
  // Also keep any marketplace that has a live Vendoo status (Facebook, etc.).
  const listingIds = [
    ...MARKETPLACE_ORDER.filter((id) => id !== "general"),
    ...Object.keys(scrapedStatuses).filter((id) => id !== "general" && !MARKETPLACE_ORDER.includes(id)),
    ...Object.keys(listings).filter((id) => {
      if (MARKETPLACE_ORDER.includes(id) || id === "validate" || id in scrapedStatuses) return false;
      const listing = listings[id] as Record<string, unknown> | undefined;
      const status = listing?.status as Record<string, unknown> | undefined;
      return Boolean(status?.listed) || leftoverMarkets.has(id);
    }),
  ];
  for (const id of listingIds) {
    const listing = listings[id] as Record<string, unknown> | undefined;
    const section = listing ? listingSection(listing) : undefined;
    const raw = listing
      ? withoutTaxonomyIdNoise(flattenFields(section, "", listingFieldLabels(listing, section)))
      : [];
    const fields = organizeFields(id, raw, fillLogEntriesForMarket(report, id));
    const liveStatus = liveStatusForMarketplace(id, item);
    if (!fields.length && !liveStatus) continue;
    forms.push(toForm(id, fields, liveStatus));
  }
  return forms;
}

function formsFromFillLog(report: FillLogReport): DraftForm[] {
  const ids = [
    ...MARKETPLACE_ORDER.filter((id) => report.by_marketplace[id]),
    ...Object.keys(report.by_marketplace).filter((id) => !MARKETPLACE_ORDER.includes(id)),
  ];
  return ids.map((id) => {
    const group = report.by_marketplace[id];
    const fields: DraftField[] = group.entries.map((entry) => {
      if (entry.status === "not_applicable") {
        return notApplicableField({
          key: entry.id,
          label: entry.field,
          value: "",
          missing: false,
        });
      }
      const pending = FILLABLE_STATUSES.has(entry.status);
      return {
        key: entry.id,
        label: entry.field,
        // Pending leftovers keep their proposed value only in the leftover input.
        value: pending ? "" : entry.value_preview || "",
        missing: pending,
        leftover: pending ? entry : undefined,
      };
    });
    return toForm(id, organizeFields(id, fields, group.entries));
  });
}

const LISTING_GENERAL_FIELDS: { key: string; label: string }[] = [
  { key: "title", label: "Title" },
  { key: "description", label: "Description" },
  { key: "brand", label: "Brand" },
  { key: "condition", label: "Condition" },
  { key: "primaryColor", label: "Primary Color" },
  { key: "secondaryColor", label: "Secondary Color" },
  { key: "sku", label: "SKU" },
  { key: "zipCode", label: "Zip Code" },
  { key: "quantity", label: "Quantity" },
  { key: "category_path", label: "Category" },
  { key: "size", label: "US Size" },
  { key: "sizeType", label: "Size Type" },
  { key: "weight_lb", label: "Package Weight (lb)" },
  { key: "weight_oz", label: "Package Weight (oz)" },
  { key: "price", label: "Listing Price" },
  { key: "cost", label: "Cost of Goods" },
  { key: "tags", label: "Tags" },
  { key: "labels", label: "Vendoo Labels" },
  { key: "notes", label: "Vendoo Internal Notes" },
];

function nestedListingValue(listing: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((current, key) => {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    return (current as Record<string, unknown>)[key];
  }, listing);
}

function listingField(listing: Record<string, unknown>, key: string, label: string): DraftField {
  const raw = nestedListingValue(listing, key);
  if (isDoesNotApplyValue(raw)) {
    return notApplicableField({ key, label, value: "", missing: false });
  }
  return { key, label, value: fieldDisplayValue(raw, label), missing: fieldIsMissing(raw, label) };
}

function specificsListingFields(listing: Record<string, unknown>, marketplace: string): DraftField[] {
  const specs = listing[`${marketplace}_specifics`];
  if (!specs || typeof specs !== "object" || Array.isArray(specs)) return [];
  const fields: DraftField[] = [];
  for (const [key, value] of Object.entries(specs as Record<string, unknown>)) {
    if (key === "category_specifics" && value && typeof value === "object" && !Array.isArray(value)) {
      for (const [nested, nestedValue] of Object.entries(value as Record<string, unknown>)) {
        const label = fieldLabel(nested);
        if (isDoesNotApplyValue(nestedValue)) {
          fields.push(notApplicableField({
            key: `${marketplace}_specifics.category_specifics.${nested}`,
            label,
            value: "",
            missing: false,
          }));
          continue;
        }
        fields.push({
          key: `${marketplace}_specifics.category_specifics.${nested}`,
          label,
          value: fieldDisplayValue(nestedValue, label),
          missing: fieldIsMissing(nestedValue, label),
        });
      }
      continue;
    }
    const label = fieldLabel(key);
    if (isDoesNotApplyValue(value)) {
      fields.push(notApplicableField({
        key: `${marketplace}_specifics.${key}`,
        label,
        value: "",
        missing: false,
      }));
      continue;
    }
    fields.push({
      key: `${marketplace}_specifics.${key}`,
      label,
      value: fieldDisplayValue(value, label),
      missing: fieldIsMissing(value, label),
    });
  }
  return fields;
}

function formsFromListing(listing?: Record<string, unknown>): DraftForm[] {
  if (!listing || typeof listing !== "object") return [];
  const general = LISTING_GENERAL_FIELDS.map((field) => listingField(listing, field.key, field.label));
  const forms: DraftForm[] = [toForm("general", organizeFields("general", general))];
  for (const id of ["ebay", "etsy", "poshmark", "mercari", "depop"]) {
    const extras: DraftField[] = [];
    if (id === "poshmark") extras.push(listingField(listing, "poshmark_specifics.originalPrice", "Original Price"));
    if (id === "mercari") extras.push(listingField(listing, "mercari_specifics.shippingLabel", "Shipping Label"));
    const seen = new Set(extras.map((field) => field.key));
    const fields = withoutTaxonomyIdNoise([
      ...extras,
      ...specificsListingFields(listing, id).filter((field) => !seen.has(field.key)),
    ]);
    const organized = organizeFields(id, fields);
    if (!organized.length) continue;
    forms.push(toForm(id, organized));
  }
  return forms;
}

type HiddenField = { marketplace: string; field: string; label: string };
type HiddenFieldsState = { always: HiddenField[]; listing: HiddenField[] };
export type OpenMenu = { kind: "hidden" } | { kind: "field"; key: string } | null;

export function emptyHiddenFields(): HiddenFieldsState {
  return { always: [], listing: [] };
}

export function hiddenFieldKey(marketplace: string, field: string): string {
  return `${marketplace}:${field}`;
}

export function hiddenKeySet(hidden: HiddenFieldsState): Set<string> {
  return new Set(
    [...hidden.always, ...hidden.listing].map((item) => hiddenFieldKey(item.marketplace, item.field)),
  );
}

function isFieldHidden(hidden: Set<string>, marketplace: string, field: DraftField): boolean {
  if (hidden.has(hiddenFieldKey(marketplace, fieldMatchKey(field)))) return true;
  // Hidden entries are stored by label, so a field hidden back when it showed a
  // raw id would reappear once a scraped label names it. Only letterless keys
  // get this fallback -- matching real key names here would hide sibling fields
  // that happen to share a normalized name (layout key "size" vs label "Size").
  const rawKey = normalizeFieldName(field.key.split(".").pop() || field.key);
  if (!rawKey || /[a-z]/.test(rawKey)) return false;
  return hidden.has(hiddenFieldKey(marketplace, rawKey));
}

export function withoutHiddenFields(forms: DraftForm[], hidden: HiddenFieldsState): DraftForm[] {
  const keys = hiddenKeySet(hidden);
  return forms
    .map((form) => {
      const fields = form.fields.filter(
        (field) => !isFieldHidden(keys, form.id, field) && !isAccountSettingField(field),
      );
      return toForm(form.id, fields, form.liveStatus);
    })
    .filter((form) => form.fields.length > 0 || Boolean(form.liveStatus));
}

function fieldNeedsAttention(
  form: DraftForm,
  field: DraftField,
  listing: Record<string, unknown> | undefined,
  fromVendooDraft: boolean,
): boolean {
  if (field.notApplicable || isUnfillableField(field)) return false;
  if (fromVendooDraft) return field.missing;
  return listingFieldEmpty(listing, form.id, field);
}

export function filterForms(
  forms: DraftForm[],
  query: string,
  missingOnly: boolean,
  listing?: Record<string, unknown>,
  fromVendooDraft = false,
): DraftForm[] {
  const needle = query.trim().toLowerCase();
  const filtered = missingOnly || Boolean(needle);
  return forms
    .map((form) => {
      const fields = form.fields.filter((field) => {
        if (missingOnly && !fieldNeedsAttention(form, field, listing, fromVendooDraft)) return false;
        if (!needle) return true;
        const listingValue = listingTextForField(listing, form.id, field);
        return (
          form.label.toLowerCase().includes(needle) ||
          (form.liveStatus || "").toLowerCase().includes(needle) ||
          (field.section || "").toLowerCase().includes(needle) ||
          field.label.toLowerCase().includes(needle) ||
          field.value.toLowerCase().includes(needle) ||
          listingValue.toLowerCase().includes(needle)
        );
      });
      if (needle && !fields.length && !form.label.toLowerCase().includes(needle)
        && !(form.liveStatus || "").toLowerCase().includes(needle)) return null;
      const visible = filtered ? fields : form.fields;
      if (!visible.length && filtered) return null;
      return toForm(form.id, visible, form.liveStatus);
    })
    .filter((form): form is DraftForm => Boolean(form));
}
