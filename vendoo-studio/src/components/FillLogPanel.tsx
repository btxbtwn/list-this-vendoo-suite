import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ConnectChromeButton } from "./ConnectChromeButton";

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
const MARKETPLACE_ORDER = ["general", "ebay", "poshmark", "mercari", "depop", "etsy", "facebook", "grailed", "whatnot", "shopify"];
const MARKETPLACE_LABELS: Record<string, string> = {
  general: "General",
  ebay: "eBay",
  poshmark: "Poshmark",
  mercari: "Mercari",
  depop: "Depop",
  etsy: "Etsy",
  facebook: "Facebook",
  grailed: "Grailed",
  whatnot: "Whatnot",
  shopify: "Shopify",
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
  "labels",
  "draftid",
  "lastsynced",
  "lastmodified",
]);

const UNFILLABLE_FIELDS = new Set(["photos", "images", "videos", "image"]);
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
  tags: "tags",
  notes: "notes",
  "internal notes": "notes",
};

function isUnfillableField(field: DraftField): boolean {
  return UNFILLABLE_FIELDS.has(field.label.toLowerCase()) || UNFILLABLE_FIELDS.has(field.key.toLowerCase());
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
  return String(raw).trim();
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

function leftoverCount(summary?: Record<string, number>): number {
  if (!summary) return 0;
  return [...FILLABLE_STATUSES].reduce((sum, status) => sum + (summary[status] || 0), 0);
}

function allowedMarketplaceIds(selected?: string[]): Set<string> {
  const chosen = selected ?? DEFAULT_SELECTED_MARKETPLACES;
  return new Set(["general", ...chosen]);
}

function leftoverEntries(report: FillLogReport): FillLogEntry[] {
  const rows: FillLogEntry[] = [];
  for (const group of Object.values(report.by_marketplace)) {
    for (const entry of group.entries) {
      if (FILLABLE_STATUSES.has(entry.status)) rows.push(entry);
    }
  }
  return rows.sort((left, right) => {
    const statusDelta = STATUS_ORDER.indexOf(left.status) - STATUS_ORDER.indexOf(right.status);
    if (statusDelta !== 0) return statusDelta;
    return `${left.marketplace} ${left.field}`.localeCompare(`${right.marketplace} ${right.field}`);
  });
}

function marketplaceLabel(id: string): string {
  return MARKETPLACE_LABELS[id] || id.charAt(0).toUpperCase() + id.slice(1);
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

function mergeDraftItem(draft: { item?: unknown; form?: unknown } | undefined): Record<string, unknown> | undefined {
  if (!draft) return undefined;
  const item = draft.item && typeof draft.item === "object" && !Array.isArray(draft.item)
    ? draft.item as Record<string, unknown>
    : {};
  const form = draft.form && typeof draft.form === "object" && !Array.isArray(draft.form)
    ? draft.form as Record<string, unknown>
    : {};
  if (!Object.keys(item).length && !Object.keys(form).length) return undefined;
  return {
    ...form,
    ...item,
    generalDetails: {
      ...((form.generalDetails as object) || {}),
      ...((item.generalDetails as object) || {}),
    },
    listings: {
      ...((form.listings as object) || {}),
      ...((item.listings as object) || {}),
    },
    images: item.images ?? form.images,
  };
}

function formsFromDraft(item: Record<string, unknown> | null | undefined, report?: FillLogReport): DraftForm[] {
  const leftovers = report ? leftoverEntries(report) : [];
  const leftoverByKey = new Map<string, FillLogEntry>();
  for (const entry of leftovers) {
    leftoverByKey.set(`${entry.marketplace.toLowerCase()}:${entry.field.toLowerCase()}`, entry);
  }

  const attach = (formId: string, fields: DraftField[]): DraftField[] =>
    fields.map((field) => ({
      ...field,
      leftover:
        leftoverByKey.get(`${formId}:${field.label.toLowerCase()}`) ||
        leftoverByKey.get(`${formId}:${field.key.toLowerCase()}`) ||
        leftoverByKey.get(`${formId}:${field.key.split(".").pop()!.toLowerCase()}`),
    }));

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
  if (general.length) {
    const fields = attach("general", general);
    forms.push({
      id: "general",
      label: "General",
      fields,
      filled: fields.filter((field) => !field.missing).length,
      missing: fields.filter((field) => field.missing).length,
    });
  }

  const listings = item?.listings && typeof item.listings === "object"
    ? item.listings as Record<string, unknown>
    : {};
  const leftoverMarkets = new Set(leftovers.map((entry) => entry.marketplace.toLowerCase()));
  const listingIds = [
    ...MARKETPLACE_ORDER.filter((id) => id !== "general" && listings[id] != null),
    ...Object.keys(listings).filter((id) => {
      if (MARKETPLACE_ORDER.includes(id) || id === "validate") return false;
      const listing = listings[id] as Record<string, unknown> | undefined;
      const status = listing?.status as Record<string, unknown> | undefined;
      return Boolean(status?.listed) || leftoverMarkets.has(id);
    }),
  ];
  for (const id of listingIds) {
    const fields = attach(id, flattenFields(listingSection(listings[id] as Record<string, unknown>)));
    if (!fields.length) continue;
    forms.push({
      id,
      label: marketplaceLabel(id),
      fields,
      filled: fields.filter((field) => !field.missing).length,
      missing: fields.filter((field) => field.missing).length,
    });
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
    const fields: DraftField[] = [...group.entries]
      .sort((left, right) => {
        const leftMissing = FILLABLE_STATUSES.has(left.status) ? 0 : 1;
        const rightMissing = FILLABLE_STATUSES.has(right.status) ? 0 : 1;
        if (leftMissing !== rightMissing) return leftMissing - rightMissing;
        return left.field.localeCompare(right.field);
      })
      .map((entry) => ({
        key: entry.id,
        label: entry.field,
        value: entry.value_preview || "",
        missing: FILLABLE_STATUSES.has(entry.status),
        leftover: FILLABLE_STATUSES.has(entry.status) ? entry : undefined,
      }));
    return {
      id,
      label: marketplaceLabel(id),
      fields,
      filled: group.summary.filled || 0,
      missing: leftoverCount(group.summary),
    };
  });
}

const LISTING_GENERAL_FIELDS: { key: string; label: string }[] = [
  { key: "title", label: "Title" },
  { key: "description", label: "Description" },
  { key: "price", label: "Price" },
  { key: "cost", label: "Cost" },
  { key: "quantity", label: "Quantity" },
  { key: "brand", label: "Brand" },
  { key: "condition", label: "Condition" },
  { key: "primaryColor", label: "Primary Color" },
  { key: "secondaryColor", label: "Secondary Color" },
  { key: "size", label: "Size" },
  { key: "sku", label: "SKU" },
  { key: "category_path", label: "Category" },
  { key: "tags", label: "Tags" },
  { key: "notes", label: "Notes" },
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
  const forms: DraftForm[] = [{
    id: "general",
    label: "General",
    fields: general,
    filled: general.filter((field) => !field.missing).length,
    missing: general.filter((field) => field.missing).length,
  }];
  for (const id of ["ebay", "poshmark", "mercari", "depop", "etsy"]) {
    const extras: DraftField[] = [];
    if (id === "poshmark") extras.push(listingField(listing, "poshmark_specifics.originalPrice", "Original Price"));
    if (id === "mercari") extras.push(listingField(listing, "mercari_specifics.shippingLabel", "Shipping Label"));
    const seen = new Set(extras.map((field) => field.key));
    const fields = [...extras, ...specificsListingFields(listing, id).filter((field) => !seen.has(field.key))];
    if (!fields.length) continue;
    forms.push({
      id,
      label: marketplaceLabel(id),
      fields,
      filled: fields.filter((field) => !field.missing).length,
      missing: fields.filter((field) => field.missing).length,
    });
  }
  return forms;
}

function filterForms(forms: DraftForm[], query: string, missingOnly: boolean): DraftForm[] {
  const needle = query.trim().toLowerCase();
  return forms
    .map((form) => {
      const fields = form.fields.filter((field) => {
        if (missingOnly && !field.missing) return false;
        if (!needle) return true;
        return (
          form.label.toLowerCase().includes(needle) ||
          field.label.toLowerCase().includes(needle) ||
          field.value.toLowerCase().includes(needle)
        );
      });
      if (needle && !fields.length && !form.label.toLowerCase().includes(needle)) return null;
      const visible = needle || missingOnly ? fields : form.fields;
      if (!visible.length && (needle || missingOnly)) return null;
      return { ...form, fields: visible };
    })
    .filter((form): form is DraftForm => Boolean(form));
}

export function FillLogSummary({ jobId, onOpenFillLog }: { jobId: string; onOpenFillLog?: () => void }) {
  const report = useFillLog(jobId);
  if (!report) return null;
  const total = Object.values(report.summary).reduce((sum, n) => sum + n, 0);
  if (total === 0) {
    return onOpenFillLog ? (
      <button type="button" className="fill-log-open" onClick={onOpenFillLog}>
        Review fields
      </button>
    ) : null;
  }
  const leftover = leftoverCount(report.summary);
  return (
    <div className="fill-log-chips" aria-label="Fill log summary">
      {STATUS_ORDER.map((status) => {
        const count = report.summary[status] || 0;
        if (!count) return null;
        return (
          <span key={status} className={`fill-log-chip fill-log-chip-${status}`}>
            {count} {STATUS_LABELS[status]}
          </span>
        );
      })}
      {leftover > 0 && onOpenFillLog && (
        <button type="button" className="fill-log-open" onClick={onOpenFillLog}>
          Fill {leftover} leftover {leftover === 1 ? "field" : "fields"}
        </button>
      )}
    </div>
  );
}

export function FillLogPanel({
  jobId,
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
  const [query, setQuery] = React.useState("");
  const [missingOnly, setMissingOnly] = React.useState(false);
  const [showJson, setShowJson] = React.useState(false);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const filling = jobStatus === "dispatched" && jobStep === "filling_fields";
  const hasDraft = Boolean(vendooItemId || vendooUrl);
  const chromeConnected = Boolean(extStatus?.connected);
  const didRead = React.useRef<string | null>(null);
  const awaitingFill = React.useRef(false);
  const sawFilling = React.useRef(false);
  const fillingRef = React.useRef(filling);
  fillingRef.current = filling;

  const { data: cachedDraft } = useQuery({
    queryKey: ["vendoo-item", jobId],
    queryFn: () => api.jobs.vendooItem(jobId),
    enabled: false,
    staleTime: Infinity,
  });
  const readMutation = useMutation({
    mutationFn: () => api.jobs.vendooItem(jobId),
    onSuccess: (payload) => {
      setShowJson(false);
      queryClient.setQueryData(["vendoo-item", jobId], payload);
    },
  });
  const draft = readMutation.data || cachedDraft;
  const item = mergeDraftItem(draft);
  const enabledMarketplaces = allowedMarketplaceIds(marketplaceSettings?.selected);
  const draftForms = item ? formsFromDraft(item, report) : [];
  const fillForms = report && Object.keys(report.by_marketplace).length ? formsFromFillLog(report) : [];
  const listingForms = formsFromListing(listing);
  const sourceForms = (draftForms.length ? draftForms : fillForms.length ? fillForms : listingForms)
    .filter((form) => enabledMarketplaces.has(form.id));
  const fromVendooDraft = draftForms.length > 0;
  const sourceKey = sourceForms.map((form) => form.id).join("|");
  const forms = filterForms(sourceForms, query, missingOnly);
  const leftovers = report
    ? leftoverEntries(report).filter((entry) => enabledMarketplaces.has(entry.marketplace.toLowerCase()))
    : [];
  const selectedForm = forms.find((form) => form.id === selected) || forms[0];

  React.useEffect(() => {
    if (!hasDraft || !chromeConnected || didRead.current === jobId) return;
    didRead.current = jobId;
    readMutation.mutate();
  }, [hasDraft, jobId, chromeConnected]);

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
      const firstMissing = sourceForms.find((form) => form.missing > 0) || sourceForms[0];
      return firstMissing?.id || null;
    });
  }, [sourceKey]);

  const rereadDraft = () => {
    awaitingFill.current = false;
    sawFilling.current = false;
    queryClient.invalidateQueries({ queryKey: ["fill-log", jobId] });
    queryClient.invalidateQueries({ queryKey: ["listing"] });
    if (hasDraft && chromeConnected) readMutation.mutate();
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

  React.useEffect(() => {
    if (!awaitingFill.current) return;
    if (filling) {
      sawFilling.current = true;
      return;
    }
    if (sawFilling.current) rereadDraft();
  }, [filling]);

  const emptyFields = sourceForms.flatMap((form) =>
    form.fields
      .filter((field) => field.missing && !isUnfillableField(field))
      .map((field) => ({ form, field })),
  );
  const fillableEmpty = emptyFields
    .map(({ form, field }) => {
      const leftover = field.leftover;
      const typed = leftover ? String(values[leftover.id] || "").trim() : "";
      const value = typed || listingValueForField(listing, form.id, field);
      if (!value) return null;
      return leftover
        ? { id: leftover.id, marketplace: form.id, field: field.label, value }
        : { marketplace: form.id, field: field.label, value };
    })
    .filter((item): item is { id?: string; marketplace: string; field: string; value: string } => Boolean(item));

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
          onClick={() => setMissingOnly((value) => !value)}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M2 3h12L9.5 8.5V13l-3 1.5V8.5L2 3z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
          </svg>
        </button>
        {hasDraft && (
          <button
            type="button"
            className="pr-icon-btn pr-read"
            disabled={readMutation.isPending}
            onClick={() => readMutation.mutate()}
          >
            {readMutation.isPending ? "Reading…" : draft ? "Refresh" : "Read draft"}
          </button>
        )}
        {draft?.ok && (
          <button type="button" className="pr-icon-btn pr-read" onClick={() => setShowJson((value) => !value)}>
            {showJson ? "Hide JSON" : "JSON"}
          </button>
        )}
      </div>

      {(onAskChat || hasDraft) && (
        <div className="pr-actions">
          {onAskChat && (
            <button
              type="button"
              className="btn btn-sm"
              disabled={fillMutation.isPending || filling || emptyFields.length === 0}
              onClick={() => onAskChat(emptyFieldsPrompt(sourceForms, fromVendooDraft))}
            >
              {emptyFields.length
                ? `Ask chat to fill ${emptyFields.length} empty ${emptyFields.length === 1 ? "field" : "fields"}`
                : "Ask chat to fill empty fields"}
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

      {hasDraft && !fromVendooDraft && !readMutation.isPending && (
        <p className="pr-notice">
          {chromeConnected
            ? "Showing blank listing fields. Read the Vendoo draft to send only the empty Vendoo form fields to chat."
            : "Showing blank listing fields. Connect Chrome, then read the draft so chat gets the actual empty Vendoo fields."}
        </p>
      )}

      {readMutation.error && (
        <div className="text-xs text-error">{(readMutation.error as Error).message || "Could not read the Vendoo draft"}</div>
      )}
      {draft?.api_error && <div className="pr-meta">API: {draft.api_error}</div>}

      {!forms.length ? (
        <div className="pr-empty">
          <p>
            {readMutation.isPending
              ? "Reading Vendoo draft…"
              : !chromeConnected && hasDraft
                ? "Connect Chrome to read empty Vendoo fields. Ask chat can still generate values, then Fill on Vendoo patches only those fields."
                : hasDraft
                  ? "Read the Vendoo draft to list each marketplace form. Missing fields show in red."
                  : "Send this listing to Vendoo to review each marketplace form."}
          </p>
          {!chromeConnected && hasDraft && <ConnectChromeButton />}
        </div>
      ) : (
        <div className="pr-split">
          <div className="pr-files">
            <div className="pr-files-head">
              <span>Marketplaces</span>
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
                {selectedForm.fields.map((field) => {
                  const leftover = field.leftover;
                  return (
                    <div key={field.key} className={`pr-diff-line ${field.missing ? "is-del" : "is-add"}`}>
                      <span className="pr-diff-gutter">{field.missing ? "-" : "+"}</span>
                      <span className="pr-diff-name">{field.label}</span>
                      <span className="pr-diff-value" title={field.value}>{field.value}</span>
                      {leftover && (
                        <input
                          className="pr-input"
                          value={values[leftover.id] || ""}
                          disabled={fillMutation.isPending || filling}
                          placeholder={STATUS_LABELS[leftover.status] || leftover.status}
                          onChange={(event) => setValues((prev) => ({ ...prev, [leftover.id]: event.target.value }))}
                        />
                      )}
                    </div>
                  );
                })}
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
