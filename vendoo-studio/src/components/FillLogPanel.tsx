import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

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
  "type",
  "origin",
  "version",
  "validate",
  "hash",
  "labels",
  "draftid",
  "lastsynced",
  "lastmodified",
]);

function leftoverCount(summary?: Record<string, number>): number {
  if (!summary) return 0;
  return [...FILLABLE_STATUSES].reduce((sum, status) => sum + (summary[status] || 0), 0);
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
  if (total === 0) return <div className="fill-log-empty">Waiting for fill results…</div>;
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
  onFilled,
  onJobStarted,
}: {
  jobId: string;
  jobStatus?: string;
  jobStep?: string | null;
  vendooItemId?: string | null;
  vendooUrl?: string | null;
  onFilled?: () => void;
  onJobStarted?: () => void;
}) {
  const queryClient = useQueryClient();
  const report = useFillLog(jobId);
  const [query, setQuery] = React.useState("");
  const [missingOnly, setMissingOnly] = React.useState(false);
  const [showJson, setShowJson] = React.useState(false);
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({});
  const [selected, setSelected] = React.useState<string | null>(null);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const filling = jobStatus === "dispatched" && jobStep === "filling_fields";
  const hasDraft = Boolean(vendooItemId || vendooUrl);

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
  const draftForms = item ? formsFromDraft(item, report) : [];
  const fillForms = report && Object.keys(report.by_marketplace).length ? formsFromFillLog(report) : [];
  const forms = filterForms(draftForms.length ? draftForms : fillForms, query, missingOnly);
  const leftovers = report ? leftoverEntries(report) : [];

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
    const source = draftForms.length ? draftForms : fillForms;
    if (!source.length) return;
    setExpanded((prev) => {
      if (Object.keys(prev).length) return prev;
      const firstMissing = source.find((form) => form.missing > 0) || source[0];
      return { [firstMissing.id]: true };
    });
    setSelected((current) => current || (source.find((form) => form.missing > 0) || source[0]).id);
  }, [draftForms, fillForms]);

  const fillMutation = useMutation({
    mutationFn: (fields: { id: string; value: string }[]) => api.jobs.fillFields(jobId, fields),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["fill-log", jobId] });
      queryClient.invalidateQueries({ queryKey: ["listing"] });
      onFilled?.();
      onJobStarted?.();
    },
  });

  const pending = leftovers.filter((entry) => String(values[entry.id] || "").trim());
  const visiblePending = pending.filter((entry) => {
    if (selected && entry.marketplace.toLowerCase() !== selected) return false;
    const form = forms.find((item) => item.id === entry.marketplace.toLowerCase());
    return !form || form.fields.some((field) => field.leftover?.id === entry.id);
  });

  const toggleForm = (id: string) => {
    setSelected(id);
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
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
            placeholder="Search files..."
            aria-label="Search marketplace forms"
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
      </div>

      {readMutation.error && (
        <div className="text-xs text-error">{(readMutation.error as Error).message || "Could not read the Vendoo draft"}</div>
      )}
      {draft?.api_error && <div className="pr-meta">API: {draft.api_error}</div>}

      {!forms.length && (
        <p className="pr-empty">
          {hasDraft
            ? "Read the Vendoo draft to list each marketplace form. Missing fields show in red."
            : "Send this listing to Vendoo to review each marketplace form."}
        </p>
      )}

      <div className="pr-tree" role="tree">
        {forms.map((form) => {
          const open = Boolean(expanded[form.id]) || Boolean(query);
          return (
            <div key={form.id} className="pr-form">
              <button
                type="button"
                role="treeitem"
                aria-expanded={open}
                className={`pr-row pr-folder${selected === form.id ? " is-active" : ""}${form.missing ? " has-missing" : ""}`}
                onClick={() => toggleForm(form.id)}
              >
                <svg className={`pr-chevron${open ? " is-open" : ""}`} width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="M6 4l5 4-5 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="pr-name">{form.label}</span>
                <span className="pr-counts">
                  {form.filled > 0 && <span className="pr-add">+{form.filled}</span>}
                  {form.missing > 0 && <span className="pr-del">-{form.missing}</span>}
                </span>
              </button>
              {open && form.fields.map((field) => {
                const leftover = field.leftover;
                const fieldId = `${form.id}:${field.key}`;
                return (
                  <div
                    key={field.key}
                    role="treeitem"
                    className={`pr-row pr-file${field.missing ? " is-missing" : ""}${selected === fieldId ? " is-active" : ""}`}
                    onClick={() => setSelected(fieldId)}
                  >
                    <span className="pr-name" title={field.value || field.label}>{field.label}</span>
                    {field.missing
                      ? <span className="pr-value is-empty">{field.value || "Empty"}</span>
                      : field.value
                        ? <span className="pr-value" title={field.value}>{field.value}</span>
                        : null}
                    <span className="pr-counts">
                      {field.missing ? <span className="pr-del">-1</span> : <span className="pr-add">+1</span>}
                    </span>
                    {leftover && (
                      <input
                        className="pr-input"
                        value={values[leftover.id] || ""}
                        disabled={fillMutation.isPending || filling}
                        placeholder={STATUS_LABELS[leftover.status] || leftover.status}
                        onChange={(event) => setValues((prev) => ({ ...prev, [leftover.id]: event.target.value }))}
                        onClick={(event) => event.stopPropagation()}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      {visiblePending.length > 0 && (
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={fillMutation.isPending || filling}
          onClick={() => fillMutation.mutate(visiblePending.map((entry) => ({
            id: entry.id,
            value: String(values[entry.id] || "").trim(),
          })))}
        >
          {fillMutation.isPending || filling
            ? "Filling leftover fields..."
            : `Fill ${visiblePending.length} field${visiblePending.length === 1 ? "" : "s"}`}
        </button>
      )}
      {fillMutation.error && (
        <div className="text-xs text-error">{(fillMutation.error as Error).message || "Failed to fill leftover fields"}</div>
      )}

      {draft?.ok && (
        <button type="button" className="fill-log-open" onClick={() => setShowJson((value) => !value)}>
          {showJson ? "Hide JSON" : "Show JSON"}
        </button>
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
