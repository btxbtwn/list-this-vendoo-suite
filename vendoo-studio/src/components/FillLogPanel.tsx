import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import {
  fetchVendooItemLive,
  VENDOO_ITEM_STALE_MS,
  vendooItemQueryKey,
} from "../api/vendooItemQuery";
import { addToast } from "../ui/toast";
import { ConnectChromeButton } from "./ConnectChromeButton";
import {
  DEPOP_CATEGORY_OPTIONALS,
  EBAY_CATEGORY_CORE,
  EBAY_CATEGORY_OPTIONALS,
  ETSY_CATEGORY_OPTIONALS,
} from "../marketplaceFields";

interface FillLogEntry {
  id: string;
  step: string;
  marketplace: string;
  field: string;
  status: string;
  reason: string;
  selector: string;
  value_preview: string;
}

interface FillLogReport {
  job_id: string;
  summary: Record<string, number>;
  by_marketplace: Record<string, { summary: Record<string, number>; entries: FillLogEntry[] }>;
  log_path: string | null;
}

interface DraftField {
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
const FILL_FAILURE_STATUSES = new Set(["invalid", "failed", "not_found", "uncertain"]);

function isAlreadySetEntry(entry: { status?: string; reason?: string }): boolean {
  return /^already set$/i.test(String(entry.reason || "").trim());
}
const EMPTY_CELL = "— empty —";
const UNREAD_CELL = "— not read —";
const DOES_NOT_APPLY_RE = /^(d|n\/?a|n\.a\.?|does not apply|none|unknown|-+)$/i;

interface FormSyncCounts {
  onVendoo: number;
  vendooEmpty: number;
  readyToApply: number;
  needsChat: number;
  notApplicable: number;
}

function listingTextForField(
  listing: Record<string, unknown> | undefined,
  marketplace: string,
  field: DraftField,
): string {
  return listingValueForField(listing, marketplace, field);
}

function listingFieldEmpty(
  listing: Record<string, unknown> | undefined,
  marketplace: string,
  field: DraftField,
): boolean {
  return !listingTextForField(listing, marketplace, field);
}

function vendooTextForField(field: DraftField): string {
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

function fieldNeedsVendooApply(field: DraftField, applyValue: string): boolean {
  if (!applyValue || field.notApplicable || isUnfillableField(field) || field.listingOnly) return false;
  if (field.missing) return true;
  return !applyValueMatchesVendoo(applyValue, field);
}

function formSyncCounts(
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

function fieldsNeedingListingValues(
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

function issueLabel(entry: FillLogEntry): string {
  if (entry.status === "new") return "Discovered on form";
  if (isAlreadySetEntry(entry)) return "Already set";
  if (/^no evidence\b/i.test(String(entry.reason || "").trim())) return "No evidence";
  if (entry.status === "skipped") return "Not filled";
  return STATUS_LABELS[entry.status] || entry.status;
}

function issueKind(entry: FillLogEntry): "discovery" | "failure" {
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

function listingValueForField(
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

function leftoverGeneratedValue(
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

function leftoverFieldPrompt(
  listing: Record<string, unknown> | undefined,
  entry: FillLogEntry,
  currentValue: string,
): string {
  const title = listingTitle(listing);
  const current = String(currentValue || entry.value_preview || "").trim() || "(empty)";
  const reason = String(entry.reason || "").trim() || "(none)";
  return `Fix this Vendoo field for listing "${title}".

Listing: ${title}
Marketplace: ${entry.marketplace}
Field: ${entry.field}
Current value: ${current}
Status: ${leftoverStatusLabel(entry)}
Failure reason: ${reason}

Generate a value for ONLY this field from the photos and current listing. Do not rewrite unrelated fields.

Reply with JSON in this exact shape:

\`\`\`json
{"missing_fields":[{"marketplace":"${entry.marketplace}","field":"${entry.field}","value":"..."}]}
\`\`\`
`;
}

function emptyFieldsPrompt(
  forms: DraftForm[],
  fromDraft: boolean,
  listing?: Record<string, unknown>,
): string {
  const title = listingTitle(listing);
  const rows: { marketplace: string; form: string; field: string; current: string; status: string; reason: string }[] = [];
  for (const { form, field } of fieldsNeedingListingValues(forms, listing)) {
    const leftover = field.leftover;
    rows.push({
      marketplace: form.id,
      form: form.label,
      field: field.label,
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
  Field: ${row.field}
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

When the item's brand is not offered by a marketplace, answer "Other" for Depop and "No Brand/Not sure" for Mercari — never substitute a different brand.

Empty fields:
${lines.join("\n")}`;
}

/** One Ask-chat prompt for empty listing values and Apply/Send failures (deduped). */
function askChatGapsPrompt(
  forms: DraftForm[],
  fromDraft: boolean,
  listing: Record<string, unknown> | undefined,
  failures: FillLogEntry[],
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
  Field: ${field}
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
  Field: ${field.label}
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

When the item's brand is not offered by a marketplace, answer "Other" for Depop and "No Brand/Not sure" for Mercari — never substitute a different brand.

Fields:
${lines.join("\n") || "- (none)"}`;
}

function allowedMarketplaceIds(selected?: string[]): Set<string> {
  const chosen = selected ?? DEFAULT_SELECTED_MARKETPLACES;
  return new Set(["general", ...chosen]);
}

function leftoverEntries(report: FillLogReport): FillLogEntry[] {
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

function fillFailureEntries(report: FillLogReport): FillLogEntry[] {
  return leftoverEntries(report).filter((entry) => FILL_FAILURE_STATUSES.has(entry.status));
}

function patchableChangedFields(
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

function sourceFormsForJob(
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

function useVendooDraft(jobId: string, enabled: boolean, liveRefresh = true) {
  return useQuery({
    queryKey: vendooItemQueryKey(jobId),
    // Live hydrate: cache-only reads can overwrite a just-finished Chrome scrape.
    // While Send/verify owns the Vendoo tab, stay on cache so Discovering… cannot race it.
    queryFn: () => api.jobs.vendooItem(jobId, liveRefresh ? { refresh: true } : { cacheOnly: true }),
    enabled,
    staleTime: VENDOO_ITEM_STALE_MS,
    retry: 1,
  });
}

function marketplaceLabel(id: string): string {
  return MARKETPLACE_LABELS[id] || id.charAt(0).toUpperCase() + id.slice(1);
}

function liveStatusClass(status?: string): string {
  const key = (status || "").toLowerCase().replace(/\s+/g, "-");
  if (key === "listed" || key === "complete" || key === "sold") return "is-listed";
  if (key === "not-listed" || key === "draft" || key === "incomplete") return "is-not-listed";
  if (key === "failed") return "is-failed";
  return "";
}

function LiveStatusChip({ status }: { status?: string }) {
  if (!status) return null;
  return (
    <span className={`pr-live-status ${liveStatusClass(status)}`} title={`Vendoo status: ${status}`}>
      {status}
    </span>
  );
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

function normalizeFieldName(value: string): string {
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

function fieldMatchKey(field: DraftField): string {
  return normalizeFieldName(field.label) || normalizeFieldName(field.key.split(".").pop() || field.key);
}

/** Cascade fields that must stay visible so optionals can mount on Vendoo. */
const PROTECTED_EBAY_CORE_NAMES = new Set(
  EBAY_CATEGORY_CORE.filter((field) =>
    ["department", "size", "sizeType", "type"].includes(field.key),
  ).map((field) => normalizeFieldName(field.label)),
);

function isProtectedEbayField(marketplace: string, field: DraftField | string): boolean {
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

function groupFields(fields: DraftField[]): { label: string; fields: DraftField[] }[] {
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
  const out: Record<string, unknown> = { ...(base || {}) };
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

function mergeDraftItem(draft: {
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

function normalizeLiveStatus(raw: unknown): string | undefined {
  if (typeof raw !== "string") return undefined;
  const cleaned = raw.replace(/\s+/g, " ").trim().toUpperCase();
  if (!cleaned || cleaned === "BETA" || cleaned === "NEW" || cleaned === "ALPHA") return undefined;
  return cleaned;
}

function liveStatusForMarketplace(
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
  const status = listing?.status as Record<string, unknown> | undefined;
  if (!status || typeof status !== "object") return undefined;
  if (status.listed === true) return "LISTED";
  if (status.listed === false) return "NOT LISTED";
  return undefined;
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
    const images = (item?.generalDetails as Record<string, unknown>).images;
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
type OpenMenu = { kind: "hidden" } | { kind: "field"; key: string } | null;

function emptyHiddenFields(): HiddenFieldsState {
  return { always: [], listing: [] };
}

function hiddenFieldKey(marketplace: string, field: string): string {
  return `${marketplace}:${field}`;
}

function hiddenKeySet(hidden: HiddenFieldsState): Set<string> {
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

function withoutHiddenFields(forms: DraftForm[], hidden: HiddenFieldsState): DraftForm[] {
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

function filterForms(
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

function FormSyncCountsView({
  counts,
  fromVendooDraft,
}: {
  counts: FormSyncCounts;
  fromVendooDraft: boolean;
}) {
  return (
    <span className="pr-counts">
      {counts.onVendoo > 0 && (
        <span className="pr-add" title={fromVendooDraft ? "Filled on Vendoo" : "Filled in listing JSON"}>
          +{counts.onVendoo}
        </span>
      )}
      {fromVendooDraft && counts.readyToApply > 0 && (
        <span className="pr-ready" title="Listing has a value; Vendoo is still empty">
          ●{counts.readyToApply}
        </span>
      )}
      {counts.notApplicable > 0 && <span className="pr-na">~{counts.notApplicable}</span>}
      {counts.vendooEmpty > 0 && (
        <span className="pr-del" title={fromVendooDraft ? "Empty on Vendoo" : "Empty in listing JSON"}>
          -{counts.vendooEmpty}
        </span>
      )}
    </span>
  );
}

export function FillLogPanel({
  jobId,
  conversationId,
  jobStatus,
  jobStep,
  vendooItemId,
  vendooUrl,
  listing,
  onAskChat,
  onFilled,
  onJobStarted,
}: {
  jobId: string;
  conversationId?: string;
  jobStatus?: string;
  jobStep?: string | null;
  vendooItemId?: string | null;
  vendooUrl?: string | null;
  listing?: Record<string, unknown>;
  onAskChat?: (text: string) => void;
  onFilled?: () => void;
  onJobStarted?: () => void;
}) {
  const queryClient = useQueryClient();
  const report = useFillLog(jobId);
  const { data: extStatus } = useQuery({
    queryKey: ["extension-status"],
    queryFn: api.extension.status,
    refetchInterval: 5000,
  });
  const { data: marketplaceSettings } = useQuery({
    queryKey: ["settings-marketplaces"],
    queryFn: api.settings.marketplaces,
  });
  const hiddenQueryKey = ["settings-hidden-fields", conversationId] as const;
  const { data: hiddenData } = useQuery({
    queryKey: hiddenQueryKey,
    queryFn: () => api.settings.hiddenFields(conversationId),
  });
  const [query, setQuery] = React.useState("");
  const [missingOnly, setMissingOnly] = React.useState(false);
  const [showJson, setShowJson] = React.useState(false);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [openMenu, setOpenMenu] = React.useState<OpenMenu>(null);
  const resolving =
    jobStatus === "dispatched"
    && (jobStep === "resolving_fields" || jobStep === "verifying_draft");
  const filling = jobStatus === "dispatched" && !resolving;
  const hasDraft = Boolean(vendooItemId || vendooUrl);
  const chromeConnected = Boolean(extStatus?.connected);
  const awaitingFill = React.useRef(false);
  const sawFilling = React.useRef(false);
  const fillingRef = React.useRef(filling);
  fillingRef.current = filling;

  const draftQuery = useVendooDraft(jobId, hasDraft, !(resolving || filling));
  const draft = draftQuery.data;
  const [refreshingDraft, setRefreshingDraft] = React.useState(false);
  const { sourceForms, fromVendooDraft } = sourceFormsForJob(
    mergeDraftItem(draft),
    report,
    listing,
    marketplaceSettings?.selected,
  );
  const hidden = hiddenData || emptyHiddenFields();
  const visibleSourceForms = withoutHiddenFields(sourceForms, hidden);
  const hiddenCount = hidden.always.length + hidden.listing.length;
  const sourceKey = visibleSourceForms.map((form) => form.id).join("|");
  const forms = filterForms(visibleSourceForms, query, missingOnly, listing, fromVendooDraft);
  const selectedForm = forms.find((form) => form.id === selected) || forms[0];
  const selectedCounts = selectedForm ? formSyncCounts(selectedForm, listing, fromVendooDraft) : null;

  React.useEffect(() => {
    if (!report) return;
    setValues((prev) => {
      let changed = false;
      const next = { ...prev };
      leftoverEntries(report).forEach((entry) => {
        const generated = leftoverGeneratedValue(listing, entry);
        if (!generated) {
          if (next[entry.id] == null) {
            next[entry.id] = "";
            changed = true;
          }
          return;
        }
        if (!String(next[entry.id] || "").trim()) {
          next[entry.id] = generated;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [report, listing]);

  React.useEffect(() => {
    if (!sourceKey) return;
    const source = sourceKey.split("|");
    setSelected((current) => {
      if (current && source.includes(current)) return current;
      const firstMissing = visibleSourceForms.find((form) => form.missing > 0) || visibleSourceForms[0];
      return firstMissing?.id || null;
    });
  }, [sourceKey]);

  React.useEffect(() => {
    if (!openMenu) return;
    const onPointer = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest(".pr-menu-wrap, .pr-hide-choices, .pr-hide-btn")) return;
      setOpenMenu(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpenMenu(null);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [openMenu]);

  const refreshDraftLive = async () => {
    if (!hasDraft) return;
    if (resolving || filling) {
      return;
    }
    setShowJson(false);
    setRefreshingDraft(true);
    try {
      // Always hit Chrome with refresh=true via the shared query so remounts
      // don't replace the live scrape with a server-cache response.
      const fresh = await fetchVendooItemLive(queryClient, jobId, { force: true });
      if (fresh?.error || fresh?.api_error) {
        addToast({
          type: "error",
          title: "Could not fully refresh Vendoo draft",
          description: String(fresh.error || fresh.api_error),
        });
      }
    } catch (error) {
      addToast({ type: "error", title: (error as Error).message || "Could not refresh Vendoo draft" });
    } finally {
      setRefreshingDraft(false);
    }
  };

  const rereadDraft = () => {
    awaitingFill.current = false;
    sawFilling.current = false;
    queryClient.invalidateQueries({ queryKey: ["fill-log", jobId] });
    queryClient.invalidateQueries({ queryKey: ["listing"] });
    if (hasDraft) void refreshDraftLive();
    onFilled?.();
  };

  const fillMutation = useMutation({
    mutationFn: (fields: { id?: string; marketplace?: string; field?: string; value?: string }[]) =>
      api.jobs.fillFields(jobId, fields),
    onSuccess: () => {
      awaitingFill.current = true;
      sawFilling.current = fillingRef.current;
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["fill-log", jobId] });
      queryClient.invalidateQueries({ queryKey: ["listing"] });
      onFilled?.();
      onJobStarted?.();
      window.setTimeout(() => {
        if (awaitingFill.current && !sawFilling.current && !fillingRef.current) rereadDraft();
      }, 8000);
    },
  });
  const busy = fillMutation.isPending || filling || resolving;

  const hideMutation = useMutation({
    mutationFn: (body: {
      marketplace: string;
      field: string;
      label?: string;
      scope: "always" | "listing";
      conversation_id?: string;
    }) => api.settings.hideField(body),
    onSuccess: (payload, body) => {
      queryClient.setQueryData(hiddenQueryKey, { always: payload.always, listing: payload.listing });
      setOpenMenu(null);
      addToast({
        type: "success",
        title: body.scope === "always" ? "Hidden on every listing" : "Hidden on this listing",
      });
    },
    onError: (error) => {
      addToast({ type: "error", title: (error as Error).message || "Could not hide field" });
    },
  });

  const showMutation = useMutation({
    mutationFn: (body: {
      marketplace: string;
      field: string;
      scope: "always" | "listing";
      conversation_id?: string;
    }) => api.settings.showField(body),
    onSuccess: (payload) => {
      queryClient.setQueryData(hiddenQueryKey, { always: payload.always, listing: payload.listing });
      if (payload.always.length + payload.listing.length === 0) setOpenMenu(null);
    },
    onError: (error) => {
      addToast({ type: "error", title: (error as Error).message || "Could not show field" });
    },
  });

  const restoreAllMutation = useMutation({
    mutationFn: () => api.settings.restoreAllHiddenFields(conversationId),
    onSuccess: (payload) => {
      queryClient.setQueryData(hiddenQueryKey, { always: payload.always, listing: payload.listing });
      setOpenMenu(null);
      addToast({ type: "success", title: "Restored all hidden fields" });
    },
    onError: (error) => {
      addToast({ type: "error", title: (error as Error).message || "Could not restore fields" });
    },
  });

  const resolveCategory = useMutation({
    mutationFn: () => api.jobs.resolveCategory(jobId, String(listing?.category_path || "")),
    onSuccess: (result) => {
      addToast({
        type: "success",
        title: "Matched Vendoo category",
        description: result.path || "Saved the picker category onto this listing.",
      });
      queryClient.invalidateQueries({ queryKey: ["listing"] });
      queryClient.invalidateQueries({ queryKey: ["conversation"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: vendooItemQueryKey(jobId) });
      onFilled?.();
    },
    onError: (err: Error) => {
      addToast({ type: "error", title: "Could not match category", description: err.message });
    },
  });

  React.useEffect(() => {
    if (!awaitingFill.current) return;
    if (filling) {
      sawFilling.current = true;
      return;
    }
    if (sawFilling.current) rereadDraft();
  }, [filling]);

  const prevJobStatus = React.useRef(jobStatus);
  React.useEffect(() => {
    const prev = prevJobStatus.current;
    prevJobStatus.current = jobStatus;
    if (!hasDraft || !chromeConnected) return;
    if (jobStatus !== "completed" || prev === "completed" || prev == null) return;
    // Leftover-fill completion already triggers rereadDraft above.
    if (awaitingFill.current) return;
    rereadDraft();
  }, [jobStatus, hasDraft, chromeConnected, onAskChat]);

  const hiddenKeys = hiddenKeySet(hidden);
  const askChatFields = fieldsNeedingListingValues(visibleSourceForms, listing).filter(
    ({ form, field }) => !hiddenKeys.has(hiddenFieldKey(form.id, fieldMatchKey(field))),
  );
  const fillFailures = (report ? fillFailureEntries(report) : []).filter(
    (entry) => !hiddenKeys.has(hiddenFieldKey(entry.marketplace.toLowerCase(), normalizeFieldName(entry.field))),
  );
  const askChatTargets = (() => {
    const seen = new Set<string>();
    let count = 0;
    for (const entry of fillFailures) {
      const key = `${entry.marketplace.toLowerCase()}:${normalizeFieldName(entry.field)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      count += 1;
    }
    for (const { form, field } of askChatFields) {
      const key = `${form.id}:${fieldMatchKey(field)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      count += 1;
    }
    return count;
  })();
  // With a live draft read, Apply is only empty or mismatched fields. Matching
  // controls stay untouched so retries do not re-walk every marketplace form.
  const fillPayload = fromVendooDraft
    ? patchableChangedFields(visibleSourceForms, listing, values)
    : (() => {
        const payload: { id?: string; marketplace: string; field: string; value: string }[] = [];
        const seen = new Set<string>();
        for (const entry of report ? leftoverEntries(report) : []) {
          const key = `${entry.marketplace.toLowerCase()}:${entry.field.toLowerCase()}`;
          if (seen.has(key)) continue;
          const typed = String(values[entry.id] || "").trim();
          const value = typed || listingValueForField(listing, entry.marketplace, {
            key: entry.field,
            label: entry.field,
            value: "",
            missing: true,
          });
          if (!value) continue;
          seen.add(key);
          payload.push({ id: entry.id, marketplace: entry.marketplace, field: entry.field, value });
        }
        return payload;
      })();

  const hideField = (formId: string, field: DraftField, scope: "always" | "listing") => {
    if (scope === "listing" && !conversationId) return;
    if (isProtectedEbayField(formId, field)) {
      addToast({
        type: "error",
        title: "Keep this field visible",
        description: `${field.label} is required for eBay category specifics to load on Vendoo.`,
      });
      setOpenMenu(null);
      return;
    }
    hideMutation.mutate({
      marketplace: formId,
      field: fieldMatchKey(field),
      label: field.label,
      scope,
      conversation_id: conversationId,
    });
  };

  return (
    <div className="fill-log-pr">
      <div className="pr-toolbar">
        <label className="pr-search">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search fields..."
            aria-label="Search marketplace fields"
          />
        </label>
        <button
          type="button"
          className={`pr-icon-btn${missingOnly ? " is-on" : ""}`}
          title={missingOnly
            ? "Show all fields"
            : fromVendooDraft
              ? "Show empty-on-Vendoo fields only"
              : "Show empty-in-listing fields only"}
          aria-pressed={missingOnly}
          aria-label={missingOnly
            ? (fromVendooDraft ? "Showing empty-on-Vendoo fields only" : "Showing empty-in-listing fields only")
            : "Showing all fields"}
          onClick={() => setMissingOnly((value) => !value)}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M2 3h12L9.5 8.5V13l-3 1.5V8.5L2 3z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
          </svg>
        </button>
        {hiddenCount > 0 && (
          <div className="pr-menu-wrap">
            <button
              type="button"
              className={`pr-icon-btn pr-read${openMenu?.kind === "hidden" ? " is-on" : ""}`}
              title="Show hidden fields"
              aria-haspopup="menu"
              aria-expanded={openMenu?.kind === "hidden"}
              onClick={() => setOpenMenu((current) => (current?.kind === "hidden" ? null : { kind: "hidden" }))}
            >
              {hiddenCount} hidden
            </button>
            {openMenu?.kind === "hidden" && (
              <div className="pr-menu pr-menu-wide" role="menu">
                <button
                  type="button"
                  className="pr-menu-item-action"
                  style={{ width: "100%", marginBottom: 8 }}
                  disabled={restoreAllMutation.isPending}
                  onClick={() => restoreAllMutation.mutate()}
                >
                  {restoreAllMutation.isPending ? "Restoring…" : "Show all"}
                </button>
                {[
                  ...hidden.always.map((item) => ({ ...item, scope: "always" as const })),
                  ...hidden.listing.map((item) => ({ ...item, scope: "listing" as const })),
                ].map((item) => (
                  <div key={`${item.scope}:${item.marketplace}:${item.field}`} className="pr-hidden-row">
                    <div className="pr-hidden-copy">
                      <span className="pr-hidden-name">{item.label || item.field}</span>
                      <span className="pr-hidden-meta">
                        {marketplaceLabel(item.marketplace)} · {item.scope === "always" ? "Always" : "This listing"}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="pr-menu-item-action"
                      disabled={showMutation.isPending || (item.scope === "listing" && !conversationId)}
                      onClick={() =>
                        showMutation.mutate({
                          marketplace: item.marketplace,
                          field: item.field,
                          scope: item.scope,
                          conversation_id: conversationId,
                        })
                      }
                    >
                      Show
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {hasDraft && (
          <button
            type="button"
            className="pr-icon-btn pr-read"
            disabled={draftQuery.isFetching || refreshingDraft}
            onClick={() => {
              void refreshDraftLive();
            }}
            title={chromeConnected ? "Re-read the live Vendoo form" : "Connect Chrome to refresh from Vendoo"}
          >
            {draftQuery.isFetching || refreshingDraft ? "Discovering…" : draft ? "Refresh" : "Read draft"}
          </button>
        )}
        {draft?.ok && (
          <button type="button" className="pr-icon-btn pr-read" onClick={() => setShowJson((value) => !value)}>
            {showJson ? "Hide JSON" : "JSON"}
          </button>
        )}
      </div>

      {draftQuery.isFetching && (
        <p className="pr-notice">
          Opening each marketplace form and expanding optional fields so Studio can list every empty field…
        </p>
      )}

      {hasDraft && !fromVendooDraft && !draftQuery.isFetching && (
        <p className="pr-notice">
          {chromeConnected
            ? "Read the Vendoo draft to compare listing JSON against the live form."
            : "Connect Chrome, then read the Vendoo draft to compare listing JSON against the live form."}
        </p>
      )}

      {draftQuery.error && (
        <div className="text-xs text-error">{(draftQuery.error as Error).message || "Could not read the Vendoo draft"}</div>
      )}
      {draft?.api_error && <div className="pr-meta">API: {draft.api_error}</div>}

      {!sourceForms.length ? (
        <div className="pr-empty">
          <p>
            {draftQuery.isFetching
              ? "Discovering every marketplace form and optional field…"
              : !chromeConnected && hasDraft
                ? "Connect Chrome to read Vendoo fields. Ask chat can still write values, then Apply types only empty or changed fields."
                : hasDraft
                  ? "Read the Vendoo draft to compare listing JSON against each marketplace form."
                  : "Send this listing to Vendoo to review each marketplace form. After generate, Studio also discovers live Vendoo fields once the category is known."}
          </p>
          {!chromeConnected && hasDraft && <ConnectChromeButton />}
        </div>
      ) : !forms.length ? (
        <div className="pr-empty">
          <p>
            {!visibleSourceForms.length
              ? "Every field is hidden. Restore hidden fields to see them here."
              : missingOnly
                ? "No missing fields match this filter."
                : "No fields match this search."}
          </p>
        </div>
      ) : (
        <div className="pr-split">
          <div className="pr-files">
            <div className="pr-files-head">
              <span>Forms</span>
              <span className="pr-files-count">{forms.length}</span>
            </div>
            <div className="pr-tree" role="list">
              {forms.map((form) => {
                const counts = formSyncCounts(form, listing, fromVendooDraft);
                return (
                <button
                  key={form.id}
                  type="button"
                  className={`pr-row${selectedForm?.id === form.id ? " is-active" : ""}`}
                  onClick={() => setSelected(form.id)}
                >
                  <span className="pr-name">{form.label}</span>
                  <LiveStatusChip status={form.liveStatus} />
                  <FormSyncCountsView counts={counts} fromVendooDraft={fromVendooDraft} />
                </button>
                );
              })}
            </div>
          </div>
          {selectedForm && (
            <div className="pr-diff">
              <div className="pr-diff-head">
                <span className="pr-diff-path">{selectedForm.label}</span>
                <LiveStatusChip status={selectedForm.liveStatus} />
                {selectedCounts && (
                  <FormSyncCountsView counts={selectedCounts} fromVendooDraft={fromVendooDraft} />
                )}
              </div>
              <div className="pr-diff-body">
                {!selectedForm.fields.length ? (
                  <div className="pr-empty">
                    <p>
                      {selectedForm.liveStatus
                        ? `Vendoo status: ${selectedForm.liveStatus}. Studio doesn’t fill this marketplace yet.`
                        : "No fields to show for this marketplace."}
                    </p>
                  </div>
                ) : (
                  groupFields(selectedForm.fields).map((group) => (
                  <div key={group.label || "fields"} className="pr-section-block">
                    {group.label ? <div className="pr-section">{group.label}</div> : null}
                    <div className="pr-field-table-head" aria-hidden="true">
                      <span className="pr-field-table-gap" />
                      <span>Field</span>
                      <span>Listing</span>
                      <span>Vendoo</span>
                      <span />
                    </div>
                    {group.fields.map((field) => {
                      const leftover = field.leftover;
                      const menuKey = `${selectedForm.id}:${field.key}`;
                      const menuOpen = openMenu?.kind === "field" && openMenu.key === menuKey;
                      const canHide = !isProtectedEbayField(selectedForm.id, field);
                      const listingText = listingTextForField(listing, selectedForm.id, field);
                      const listingEmpty = listingFieldEmpty(listing, selectedForm.id, field);
                      const vendooText = vendooTextForField(field);
                      const applyValue = listingText || (leftover
                        ? (String(values[leftover.id] ?? "").trim() || leftoverGeneratedValue(listing, leftover, field))
                        : "");
                      const rowClass = field.notApplicable
                        ? "is-na"
                        : !fromVendooDraft
                          ? "is-unknown"
                          : field.missing
                            ? "is-del"
                            : "is-add";
                      const gutter = field.notApplicable ? "~" : !fromVendooDraft ? "?" : field.missing ? "-" : "+";
                      const listingCell = field.notApplicable
                        ? "Does not apply"
                        : (listingText || EMPTY_CELL);
                      const vendooCell = !fromVendooDraft
                        ? UNREAD_CELL
                        : (vendooText || EMPTY_CELL);
                      return (
                        <div key={field.key} className={`pr-field-row ${rowClass}`}>
                          <span className="pr-field-gutter">{gutter}</span>
                          <span className="pr-field-name">{field.label}</span>
                          <span className={`pr-field-cell${listingEmpty && !field.notApplicable ? " is-empty" : " is-filled"}`}>
                            {listingCell}
                          </span>
                          <span className={`pr-field-cell${
                            !fromVendooDraft
                              ? " is-unknown"
                              : field.missing && !field.notApplicable
                                ? " is-empty"
                                : " is-filled"
                          }`}>
                            {vendooCell}
                          </span>
                          <div className="pr-field-row-actions">
                            {leftover && !field.notApplicable && (
                              <span className={`pr-issue-badge is-${issueKind(leftover)}`} title={leftover.reason || issueLabel(leftover)}>
                                {issueLabel(leftover)}
                              </span>
                            )}
                            {onAskChat && !field.notApplicable && (
                              listingEmpty
                              || (leftover && FILL_FAILURE_STATUSES.has(leftover.status))
                            ) && (
                              <button
                                type="button"
                                className="pr-read"
                                disabled={busy}
                                onClick={() => onAskChat(leftover && FILL_FAILURE_STATUSES.has(leftover.status)
                                  ? leftoverFieldPrompt(listing, leftover, applyValue || vendooText)
                                  : emptyFieldsPrompt([{ ...selectedForm, fields: [field] }], fromVendooDraft, listing))}
                              >
                                Ask chat
                              </button>
                            )}
                            {!field.notApplicable && applyValue && fromVendooDraft && fieldNeedsVendooApply(field, applyValue) && chromeConnected && (
                              <button
                                type="button"
                                className="pr-read"
                                disabled={busy}
                                onClick={() => fillMutation.mutate([{
                                  id: leftover?.id,
                                  marketplace: selectedForm.id,
                                  field: leftover?.field || field.label,
                                  value: applyValue,
                                }])}
                              >
                                Apply
                              </button>
                            )}
                            {menuOpen && canHide && (
                              <div className="pr-hide-choices">
                                <button
                                  type="button"
                                  disabled={!conversationId || hideMutation.isPending}
                                  onClick={() => hideField(selectedForm.id, field, "listing")}
                                >
                                  This listing
                                </button>
                                <button
                                  type="button"
                                  disabled={hideMutation.isPending}
                                  onClick={() => hideField(selectedForm.id, field, "always")}
                                >
                                  Always
                                </button>
                              </div>
                            )}
                            {canHide && (
                              <button
                                type="button"
                                className="pr-hide-btn"
                                aria-label={menuOpen ? `Cancel hiding ${field.label}` : `Hide ${field.label}`}
                                aria-expanded={menuOpen}
                                title="Hide this field"
                                onClick={() => setOpenMenu(menuOpen ? null : { kind: "field", key: menuKey })}
                              >
                                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                                  <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                                </svg>
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ))
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {(onAskChat || hasDraft) && (
        <div className="pr-actions">
          <p className="pr-notice">
            Ask chat only for fields generation could not resolve. After generate, Studio fills discovered listing values and applies them on Vendoo when Chrome is connected. Nothing is published.
          </p>
          {hasDraft && (
            <div className="pr-action">
              <button
                type="button"
                className="btn btn-sm"
                disabled={resolveCategory.isPending || busy || !chromeConnected}
                title={!chromeConnected ? "Connect Chrome to search the Vendoo category picker" : "Search the live Vendoo category picker and save the match"}
                onClick={() => resolveCategory.mutate()}
              >
                {resolveCategory.isPending ? "Setting category…" : "Set Vendoo category"}
              </button>
              <p className="pr-action-hint">Picks the matching category in Vendoo. Start here if the category is wrong.</p>
            </div>
          )}
          {onAskChat && (
            <div className="pr-action">
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy || askChatTargets === 0}
                title="Send empty listing fields and Apply/Send failures to chat. Does not change Vendoo yet."
                onClick={() => onAskChat(askChatGapsPrompt(
                  visibleSourceForms,
                  fromVendooDraft,
                  listing,
                  fillFailures,
                ))}
              >
                {askChatTargets
                  ? `Ask chat for ${askChatTargets} field${askChatTargets === 1 ? "" : "s"}`
                  : "Ask chat for fields"}
              </button>
              <p className="pr-action-hint">
                Empty listing values and failed Apply/Send fields — writes listing JSON only, not Vendoo.
              </p>
            </div>
          )}
          <div className="pr-action">
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={busy || fillPayload.length === 0 || !chromeConnected}
              title={
                !chromeConnected
                  ? "Connect Chrome to type these values into the Vendoo draft"
                  : resolving
                    ? "Wait for field repair to finish before applying"
                  : fillPayload.length
                    ? "Type listing values into empty Vendoo draft fields"
                    : "Ask chat to write listing values first"
              }
              onClick={() => fillMutation.mutate(fillPayload)}
            >
              {fillMutation.isPending || filling
                ? "Applying on Vendoo…"
                : resolving
                  ? (jobStep === "verifying_draft" ? "Checking draft…" : "Resolving fields…")
                : fillPayload.length
                  ? `Apply ${fillPayload.length} value${fillPayload.length === 1 ? "" : "s"} on Vendoo`
                  : "Apply values on Vendoo"}
            </button>
            <p className="pr-action-hint">
              {!chromeConnected
                ? "Connect Chrome to type listing values into the Vendoo draft."
                : resolving
                  ? "Waiting on the listing assistant to resolve saved-draft gaps. Does not publish."
                : fillPayload.length
                  ? "Listing has these values; Vendoo draft fields are still empty."
                  : "Ask chat to write listing values first, then apply them here."}
            </p>
          </div>
        </div>
      )}

      {fillPayload.length > 0 && !busy && (
        <p className="pr-notice">
          {fillPayload.length} listing value{fillPayload.length === 1 ? "" : "s"} ready for Vendoo.
          Review the Listing and Vendoo columns above, then click Apply on Vendoo.
        </p>
      )}

      {fillMutation.error && (
        <div className="text-xs text-error">{(fillMutation.error as Error).message || "Failed to apply values on Vendoo"}</div>
      )}

      {showJson && draft?.ok && (
        <pre className="fill-log-vendoo-json">
          {JSON.stringify({ source: draft.source, item_id: draft.item_id, url: draft.url, item: draft.item, form: draft.form }, null, 2)}
        </pre>
      )}
    </div>
  );
}

function useFillLog(jobId: string): FillLogReport | undefined {
  const { data } = useQuery({
    queryKey: ["fill-log", jobId],
    queryFn: () => api.jobs.fillLog(jobId),
    enabled: Boolean(jobId),
    refetchInterval: 2000,
  });
  return data;
}
