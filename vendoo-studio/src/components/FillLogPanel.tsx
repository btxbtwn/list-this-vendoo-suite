import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { addToast } from "../ui/toast";
import { ConnectChromeButton } from "./ConnectChromeButton";
import {
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
  leftover?: FillLogEntry;
  section?: string;
}

interface DraftForm {
  id: string;
  label: string;
  fields: DraftField[];
  filled: number;
  missing: number;
}

const STATUS_LABELS: Record<string, string> = {
  filled: "Filled",
  skipped: "Not filled",
  not_found: "Missing",
  failed: "Didn't work",
  uncertain: "Uncertain",
  new: "New fields",
};

const STATUS_ORDER = ["failed", "not_found", "uncertain", "new", "skipped", "filled"];
const FILLABLE_STATUSES = new Set(["failed", "not_found", "uncertain", "new", "skipped"]);
const DEFAULT_SELECTED_MARKETPLACES = ["ebay", "etsy", "poshmark", "mercari", "depop"];
const MARKETPLACE_ORDER = ["general", "ebay", "etsy", "poshmark", "mercari", "depop", "facebook", "shopify", "vinted", "whatnot", "grailed"];
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
  return ACCOUNT_SETTING_FIELDS.has(normalizeLookupKey(raw));
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

function valueFromRecord(record: Record<string, unknown> | undefined, key: string): unknown {
  if (!record || !key) return undefined;
  const jsonKey = lookupToJsonKey(key);
  const mapped = GENERAL_LISTING_KEYS[key];
  const colorKeys = new Set(["color", "primary color"]);
  for (const [candidate, value] of Object.entries(record)) {
    const candidateKey = normalizeLookupKey(candidate);
    if (candidateKey === key || (colorKeys.has(key) && colorKeys.has(candidateKey))) return value;
    if (candidate === jsonKey || (mapped && candidate === mapped)) return value;
  }
  if (jsonKey && jsonKey in record) return record[jsonKey];
  if (mapped && mapped in record) return record[mapped];
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
  if (
    marketplace === "ebay" &&
    key === "year manufactured" &&
    /^(d|n\/?a|n\.a\.?|does not apply|none|unknown|-+)$/i.test(text)
  ) {
    return "";
  }
  return text;
}

function emptyFieldsPrompt(forms: DraftForm[], fromDraft: boolean): string {
  const rows: { marketplace: string; form: string; field: string }[] = [];
  for (const form of forms) {
    for (const field of form.fields) {
      if (!field.missing || isUnfillableField(field)) continue;
      rows.push({ marketplace: form.id, form: form.label, field: field.label });
    }
  }
  const limited = rows.slice(0, 50);
  const lines = limited.map((row) => `- ${row.form} / ${row.field} (marketplace: ${row.marketplace})`);
  const intro = fromDraft
    ? "These Vendoo form fields are empty. Generate values for ONLY these fields from the photos and current listing. Do not rewrite the rest of the listing."
    : "These listing fields are still empty. Generate values for ONLY these fields from the photos and current listing. Do not rewrite the rest of the listing.";
  return `${intro}

Reply with JSON in this exact shape:

\`\`\`json
{"missing_fields":[{"marketplace":"general","field":"SKU","value":"..."}]}
\`\`\`

Use the marketplace ids and field names exactly as listed. After the values are saved, they can be filled on Vendoo without resending the whole listing.

Empty fields:
${lines.join("\n")}`;
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

function patchableEmptyFields(
  forms: DraftForm[],
  listing: Record<string, unknown> | undefined,
  values: Record<string, string> = {},
): { id?: string; marketplace: string; field: string; value: string }[] {
  return forms.flatMap((form) =>
    form.fields
      .filter((field) => field.missing && !isUnfillableField(field))
      .map((field) => {
        const leftover = field.leftover;
        const typed = leftover ? String(values[leftover.id] || "").trim() : "";
        const value = typed || listingValueForField(listing, form.id, field);
        if (!value) return null;
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
    const listingFields = new Map(listingForm.fields.map((field) => [fieldMatchKey(field), field]));
    const seen = new Set<string>();
    const fields = form.fields.map((field) => {
      const key = fieldMatchKey(field);
      if (key) seen.add(key);
      const match = listingFields.get(key);
      if (!match || isEmptyValue(match.value)) return field;
      return { ...field, value: match.value, missing: false };
    });
    // Listing-only values (chat-filled optionals) are missing from the Vendoo API
    // draft until written — still show them under the marketplace extras section.
    const extrasSection = form.id === "ebay" || form.id === "etsy" ? "Category" : "Item specifics";
    const extras: DraftField[] = [];
    for (const field of listingForm.fields) {
      const key = fieldMatchKey(field);
      if (!key || seen.has(key) || isEmptyValue(field.value)) continue;
      seen.add(key);
      extras.push({
        ...field,
        section: extrasSection,
        missing: false,
      });
    }
    if (extras.length) {
      let insertAt = fields.length;
      for (let i = 0; i < fields.length; i += 1) {
        if (fields[i].section === extrasSection) insertAt = i + 1;
      }
      fields.splice(insertAt, 0, ...extras);
    }
    return toForm(form.id, fields);
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
  ).filter((form) => enabled.has(form.id));
  return { sourceForms, fromVendooDraft: draftForms.length > 0 };
}

function useVendooDraft(jobId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["vendoo-item", jobId],
    queryFn: () => api.jobs.vendooItem(jobId),
    enabled,
    staleTime: Infinity,
    retry: 1,
  });
}

function marketplaceLabel(id: string): string {
  return MARKETPLACE_LABELS[id] || id.charAt(0).toUpperCase() + id.slice(1);
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
      fields: [
        { keys: ["source"], label: "Source", always: true },
        { keys: ["age"], label: "Age", always: true },
        { keys: ["style"], label: "Style", always: true },
        { keys: ["occasion"], label: "Occasion", always: true },
        { keys: ["size grouping"], label: "Size Grouping", always: true },
        { keys: ["material"], label: "Material", always: true },
        { keys: ["tags"], label: "Tags", always: true },
      ],
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
        rows.push({
          ...found,
          label: spec.label,
          section: section.label,
          leftover: leftover && FILLABLE_STATUSES.has(leftover.status) ? leftover : found.leftover,
          missing: found.value ? found.missing : leftover ? FILLABLE_STATUSES.has(leftover.status) : found.missing,
          value: found.value || leftover?.value_preview || "",
        });
        continue;
      }
      if (spec.always || leftover) {
        rows.push({
          key: leftover?.id || `${marketplace}.${spec.keys[0]}`,
          label: spec.label,
          value: leftover?.value_preview || "",
          missing: leftover ? FILLABLE_STATUSES.has(leftover.status) : true,
          leftover: leftover && FILLABLE_STATUSES.has(leftover.status) ? leftover : undefined,
          section: section.label,
        });
      }
    }
    placed.set(section.label, rows);
  }

  const namedExtras = placed.get(extrasSection) || [];
  const extraRows: DraftField[] = [...unused.values()].flat().map((field) => {
    const leftover = attachLeftover(field);
    return {
      ...field,
      leftover: leftover && FILLABLE_STATUSES.has(leftover.status) ? leftover : field.leftover,
      missing: field.value ? field.missing : leftover ? FILLABLE_STATUSES.has(leftover.status) : field.missing,
      value: field.value || leftover?.value_preview || "",
      section: extrasSection,
    };
  });
  const seenExtras = new Set([...namedExtras, ...extraRows].map((field) => fieldMatchKey(field)));
  extraRows.push(...leftoverPool.flatMap((entry) => {
    const key = normalizeFieldName(entry.field);
    if (key && seenExtras.has(key)) return [];
    if (key) seenExtras.add(key);
    return [{
      key: entry.id,
      label: entry.field.replace(/^(ebay|etsy|poshmark|mercari|depop|vendoo)\s+/i, "").trim() || entry.field,
      value: entry.value_preview || "",
      missing: FILLABLE_STATUSES.has(entry.status),
      leftover: FILLABLE_STATUSES.has(entry.status) ? entry : undefined,
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

function flattenFields(value: unknown, prefix = ""): DraftField[] {
  if (value == null || typeof value !== "object" || Array.isArray(value)) {
    if (!prefix) return [];
    const shown = displayValue(value);
    return [{ key: prefix, label: fieldLabel(prefix.split(".").pop() || prefix), value: shown, missing: isEmptyValue(value) }];
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.displayName === "string" ||
    Array.isArray(record.displayPath) ||
    record.option ||
    (record.value != null && Object.keys(record).length <= 3)
  ) {
    const shown = displayValue(record);
    return [{
      key: prefix || "value",
      label: fieldLabel((prefix.split(".").pop() || prefix || "Value")),
      value: shown,
      missing: isEmptyValue(record),
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
          value: displayValue(nestedRecord.option),
          missing: isEmptyValue(nestedRecord.option),
        });
        rows.push({
          key: `${path}.scale`,
          label: "Size Type",
          value: displayValue(nestedRecord.scale),
          missing: isEmptyValue(nestedRecord.scale),
        });
        continue;
      }
      const leaf =
        typeof nestedRecord.displayName === "string" ||
        Array.isArray(nestedRecord.displayPath) ||
        nestedRecord.option ||
        ("value" in nestedRecord && Object.keys(nestedRecord).length <= 3);
      if (!leaf && !isEmptyValue(nested) && Object.keys(nestedRecord).length > 1) {
        rows.push(...flattenFields(nested, path));
        continue;
      }
    }
    const shown = displayValue(nested);
    rows.push({
      key: path,
      label: fieldLabel(key),
      value: shown,
      missing: isEmptyValue(nested),
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
  delete rest.type;
  return {
    ...rest,
    ...(overrides && typeof overrides === "object" && !Array.isArray(overrides) ? overrides as object : {}),
    ...(specifics && typeof specifics === "object" && !Array.isArray(specifics) ? specifics as object : {}),
    ...(category && typeof category === "object" && !Array.isArray(category) ? category as object : {}),
  };
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
    } else {
      out[key] = value;
    }
  }
  return out;
}

function mergeDraftItem(draft: { item?: unknown; form?: unknown } | undefined): Record<string, unknown> | undefined {
  if (!draft) return undefined;
  const item = draft.item && typeof draft.item === "object" && !Array.isArray(draft.item)
    ? draft.item as Record<string, unknown>
    : {};
  const form = draft.form && typeof draft.form === "object" && !Array.isArray(draft.form)
    ? draft.form as Record<string, unknown>
    : {};
  if (!Object.keys(item).length && !Object.keys(form).length) return undefined;
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
  };
}

function fillLogEntriesForMarket(report: FillLogReport | undefined, marketplace: string): FillLogEntry[] {
  return report?.by_marketplace[marketplace]?.entries || [];
}

function toForm(id: string, fields: DraftField[]): DraftForm {
  return {
    id,
    label: marketplaceLabel(id),
    fields,
    filled: fields.filter((field) => !field.missing).length,
    missing: fields.filter((field) => field.missing).length,
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
  forms.push(toForm("general", organizeFields("general", general, fillLogEntriesForMarket(report, "general"))));

  const listings = item?.listings && typeof item.listings === "object"
    ? item.listings as Record<string, unknown>
    : {};
  const leftoverMarkets = new Set(leftovers.map((entry) => entry.marketplace.toLowerCase()));
  // Always include the standard marketplaces so empty Category optionals still
  // appear even when the Vendoo API omits an empty listings.ebay object.
  const listingIds = [
    ...MARKETPLACE_ORDER.filter((id) => id !== "general"),
    ...Object.keys(listings).filter((id) => {
      if (MARKETPLACE_ORDER.includes(id) || id === "validate") return false;
      const listing = listings[id] as Record<string, unknown> | undefined;
      const status = listing?.status as Record<string, unknown> | undefined;
      return Boolean(status?.listed) || leftoverMarkets.has(id);
    }),
  ];
  for (const id of listingIds) {
    const raw = listings[id] ? flattenFields(listingSection(listings[id] as Record<string, unknown>)) : [];
    const fields = organizeFields(id, raw, fillLogEntriesForMarket(report, id));
    if (!fields.length) continue;
    forms.push(toForm(id, fields));
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
    const fields: DraftField[] = group.entries.map((entry) => ({
      key: entry.id,
      label: entry.field,
      value: entry.value_preview || "",
      missing: FILLABLE_STATUSES.has(entry.status),
      leftover: FILLABLE_STATUSES.has(entry.status) ? entry : undefined,
    }));
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
  return { key, label, value: displayValue(raw), missing: isEmptyValue(raw) };
}

function specificsListingFields(listing: Record<string, unknown>, marketplace: string): DraftField[] {
  const specs = listing[`${marketplace}_specifics`];
  if (!specs || typeof specs !== "object" || Array.isArray(specs)) return [];
  const fields: DraftField[] = [];
  for (const [key, value] of Object.entries(specs as Record<string, unknown>)) {
    if (key === "category_specifics" && value && typeof value === "object" && !Array.isArray(value)) {
      for (const [nested, nestedValue] of Object.entries(value as Record<string, unknown>)) {
        fields.push({
          key: `${marketplace}_specifics.category_specifics.${nested}`,
          label: nested,
          value: displayValue(nestedValue),
          missing: isEmptyValue(nestedValue),
        });
      }
      continue;
    }
    fields.push({
      key: `${marketplace}_specifics.${key}`,
      label: fieldLabel(key),
      value: displayValue(value),
      missing: isEmptyValue(value),
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
    const fields = [...extras, ...specificsListingFields(listing, id).filter((field) => !seen.has(field.key))];
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
  return hidden.has(hiddenFieldKey(marketplace, fieldMatchKey(field)));
}

function withoutHiddenFields(forms: DraftForm[], hidden: HiddenFieldsState): DraftForm[] {
  const keys = hiddenKeySet(hidden);
  return forms
    .map((form) => {
      const fields = form.fields.filter(
        (field) => !isFieldHidden(keys, form.id, field) && !isAccountSettingField(field),
      );
      return toForm(form.id, fields);
    })
    .filter((form) => form.fields.length > 0);
}

function filterForms(forms: DraftForm[], query: string, missingOnly: boolean): DraftForm[] {
  const needle = query.trim().toLowerCase();
  const filtered = missingOnly || Boolean(needle);
  return forms
    .map((form) => {
      const fields = form.fields.filter((field) => {
        if (missingOnly && !field.missing) return false;
        if (!needle) return true;
        return (
          form.label.toLowerCase().includes(needle) ||
          (field.section || "").toLowerCase().includes(needle) ||
          field.label.toLowerCase().includes(needle) ||
          field.value.toLowerCase().includes(needle)
        );
      });
      if (needle && !fields.length && !form.label.toLowerCase().includes(needle)) return null;
      const visible = filtered ? fields : form.fields;
      if (!visible.length && filtered) return null;
      return toForm(form.id, visible);
    })
    .filter((form): form is DraftForm => Boolean(form));
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
  const filling = jobStatus === "dispatched" && jobStep === "filling_fields";
  const hasDraft = Boolean(vendooItemId || vendooUrl);
  const chromeConnected = Boolean(extStatus?.connected);
  const awaitingFill = React.useRef(false);
  const sawFilling = React.useRef(false);
  const fillingRef = React.useRef(filling);
  fillingRef.current = filling;

  const draftQuery = useVendooDraft(jobId, hasDraft && chromeConnected);
  const draft = draftQuery.data;
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
  const forms = filterForms(visibleSourceForms, query, missingOnly);
  const selectedForm = forms.find((form) => form.id === selected) || forms[0];

  React.useEffect(() => {
    if (!report) return;
    setValues((prev) => {
      const next = { ...prev };
      leftoverEntries(report).forEach((entry) => {
        if (next[entry.id] == null) next[entry.id] = entry.value_preview || "";
      });
      return next;
    });
  }, [report]);

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

  const rereadDraft = () => {
    awaitingFill.current = false;
    sawFilling.current = false;
    queryClient.invalidateQueries({ queryKey: ["fill-log", jobId] });
    queryClient.invalidateQueries({ queryKey: ["listing"] });
    if (hasDraft && chromeConnected) {
      setShowJson(false);
      draftQuery.refetch();
    }
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
      queryClient.invalidateQueries({ queryKey: ["vendoo-item", jobId] });
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
  }, [jobStatus, hasDraft, chromeConnected]);

  const emptyFields = visibleSourceForms.flatMap((form) =>
    form.fields
      .filter((field) => field.missing && !isUnfillableField(field))
      .map((field) => ({ form, field })),
  );
  const hiddenKeys = hiddenKeySet(hidden);
  const leftovers = (report ? leftoverEntries(report) : []).filter(
    (entry) => !hiddenKeys.has(hiddenFieldKey(entry.marketplace.toLowerCase(), normalizeFieldName(entry.field))),
  );
  const fillableEmpty = fromVendooDraft ? patchableEmptyFields(visibleSourceForms, listing, values) : [];
  const fillPayload = (() => {
    const payload = [...fillableEmpty];
    const seen = new Set(
      payload.map((item) => `${(item.marketplace || "").toLowerCase()}:${(item.field || "").toLowerCase()}`),
    );
    for (const entry of leftovers) {
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
          title={missingOnly ? "Show all fields" : "Show missing fields only"}
          aria-pressed={missingOnly}
          aria-label={missingOnly ? "Showing missing fields only" : "Showing all fields"}
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
            disabled={draftQuery.isFetching}
            onClick={() => {
              setShowJson(false);
              draftQuery.refetch();
            }}
          >
            {draftQuery.isFetching ? "Discovering…" : draft ? "Refresh" : "Read draft"}
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

      {(onAskChat || hasDraft) && (
        <div className="pr-actions">
          {onAskChat && (
            <button
              type="button"
              className="btn btn-sm"
              disabled={fillMutation.isPending || filling || emptyFields.length === 0}
              onClick={() => onAskChat(emptyFieldsPrompt(visibleSourceForms, fromVendooDraft))}
            >
              {emptyFields.length
                ? `Ask chat to fill ${emptyFields.length} empty ${emptyFields.length === 1 ? "field" : "fields"}`
                : "Ask chat to fill empty fields"}
            </button>
          )}
          {hasDraft && (
            <button
              type="button"
              className="btn btn-sm"
              disabled={resolveCategory.isPending || filling || !chromeConnected}
              title={!chromeConnected ? "Connect Chrome to search the Vendoo category picker" : "Search the live Vendoo category picker and save the match"}
              onClick={() => resolveCategory.mutate()}
            >
              {resolveCategory.isPending ? "Matching category…" : "Match Vendoo category"}
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={fillMutation.isPending || filling || fillPayload.length === 0 || !chromeConnected}
            title={
              !chromeConnected
                ? "Connect Chrome to fill only these fields on Vendoo"
                : fillPayload.length
                  ? "Fill only these missing fields on the Vendoo draft"
                  : "Ask chat to generate values first"
            }
            onClick={() => fillMutation.mutate(fillPayload)}
          >
            {fillMutation.isPending || filling
              ? "Filling empty fields..."
              : fillPayload.length
                ? `Fill ${fillPayload.length} empty field${fillPayload.length === 1 ? "" : "s"} on Vendoo`
                : "Fill empty fields on Vendoo"}
          </button>
        </div>
      )}

      {hasDraft && !fromVendooDraft && !draftQuery.isFetching && (
        <p className="pr-notice">
          {chromeConnected
            ? "Showing blank listing fields. Read the Vendoo draft to send only the empty Vendoo form fields to chat."
            : "Showing blank listing fields. Connect Chrome, then read the draft so chat gets the actual empty Vendoo fields."}
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
                ? "Connect Chrome to read empty Vendoo fields. Ask chat can still generate values, then Fill on Vendoo patches only those fields."
                : hasDraft
                  ? "Read the Vendoo draft to list each marketplace form. Missing fields show in red."
                  : "Send this listing to Vendoo to review each marketplace form."}
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
              {forms.map((form) => (
                <button
                  key={form.id}
                  type="button"
                  role="listitem"
                  className={`pr-row${selectedForm?.id === form.id ? " is-active" : ""}`}
                  onClick={() => setSelected(form.id)}
                >
                  <span className="pr-name">{form.label}</span>
                  <span className="pr-counts">
                    {form.filled > 0 && <span className="pr-add">+{form.filled}</span>}
                    {form.missing > 0 && <span className="pr-del">-{form.missing}</span>}
                  </span>
                </button>
              ))}
            </div>
          </div>
          {selectedForm && (
            <div className="pr-diff">
              <div className="pr-diff-head">
                <span className="pr-diff-path">{selectedForm.label}</span>
                <span className="pr-files-count">
                  {selectedForm.filled > 0 && <span className="pr-add">+{selectedForm.filled}</span>}
                  {selectedForm.missing > 0 && <span className="pr-del">-{selectedForm.missing}</span>}
                </span>
              </div>
              <div className="pr-diff-body">
                {groupFields(selectedForm.fields).map((group) => (
                  <div key={group.label || "fields"} className="pr-section-block">
                    {group.label ? <div className="pr-section">{group.label}</div> : null}
                    {group.fields.map((field) => {
                      const leftover = field.leftover;
                      const menuKey = `${selectedForm.id}:${field.key}`;
                      const menuOpen = openMenu?.kind === "field" && openMenu.key === menuKey;
                      return (
                        <div key={field.key} className={`pr-diff-line ${field.missing ? "is-del" : "is-add"}`}>
                          <span className="pr-diff-gutter">{field.missing ? "-" : "+"}</span>
                          <div className="pr-diff-main">
                            <span className="pr-diff-name">{field.label}</span>
                            {field.value ? <span className="pr-diff-value">{field.value}</span> : null}
                            {leftover && (
                              <input
                                className="pr-input"
                                value={values[leftover.id] || ""}
                                disabled={fillMutation.isPending || filling}
                                placeholder={STATUS_LABELS[leftover.status] || leftover.status}
                                onChange={(event) => setValues((prev) => ({ ...prev, [leftover.id]: event.target.value }))}
                              />
                            )}
                            {menuOpen && (
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
                          </div>
                          <div className="pr-field-actions">
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
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {fillMutation.error && (
        <div className="text-xs text-error">{(fillMutation.error as Error).message || "Failed to fill leftover fields"}</div>
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
