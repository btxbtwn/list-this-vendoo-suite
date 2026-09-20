import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { addLabel, removeLabel, splitLabels } from "./itemLabels";
import { historyRows } from "./vendooHistory";

interface Props {
  convId: string;
}

type Garment = "top" | "pants";

interface MeasurementField {
  key: string;
  label: string;
  placeholder: string;
}

// Keys and labels mirror GARMENT_MEASUREMENTS in server listing_generate.py.
const GARMENTS: { id: Garment; label: string; fields: MeasurementField[] }[] = [
  {
    id: "top",
    label: "Top",
    fields: [
      { key: "pitToPit", label: "Pit to Pit", placeholder: "22.5" },
      { key: "length", label: "Length", placeholder: "27" },
      { key: "sleeve", label: "Sleeve", placeholder: "9" },
    ],
  },
  // Pants cover shorts too: same waist, rise, inseam and leg opening.
  {
    id: "pants",
    label: "Pants",
    fields: [
      { key: "waist", label: "Waist", placeholder: "16" },
      { key: "rise", label: "Rise", placeholder: "11" },
      { key: "inseam", label: "Inseam", placeholder: "30" },
      { key: "legOpening", label: "Leg Opening", placeholder: "8" },
    ],
  },
];

type Measurements = Record<Garment, Record<string, string>>;

interface ItemDetailsData {
  sellerNotes: string;
  cog: string;
  packageDimensions: string;
  vendooLabels: string;
  poshmarkOriginalPrice: string;
  garment: Garment;
  measurements: Measurements;
}

type TextKey = Exclude<keyof ItemDetailsData, "garment" | "measurements">;

const RECENT_LABELS_KEY = "vendoo-studio.recent-labels";
const MAX_RECENT_LABELS = 12;

function readLegacyStoredLabels(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_LABELS_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string" && item.trim()) : [];
  } catch {
    return [];
  }
}

function clearLegacyStoredLabels() {
  try {
    localStorage.removeItem(RECENT_LABELS_KEY);
  } catch {
    /* ignore quota / private-mode failures */
  }
}

function rememberLabels(
  raw: string,
  restore: string[],
  queryClient?: ReturnType<typeof useQueryClient>,
) {
  void api.settings
    .setUi({ remember_labels: raw, ...(restore.length ? { restore_labels: restore } : {}) })
    .then(() => {
      queryClient?.invalidateQueries({ queryKey: ["settings-ui"] });
    })
    .catch(() => {
      /* disk prefs are best-effort; listing notes still save */
    });
}

function labelsFromNotes(notes: string | null | undefined): string[] {
  if (!notes) return [];
  try {
    const parsed = JSON.parse(notes);
    return splitLabels(String(parsed.vendooLabels || ""));
  } catch {
    return [];
  }
}

const DEFAULTS: ItemDetailsData = {
  sellerNotes: "",
  cog: "",
  packageDimensions: "13x10x3",
  vendooLabels: "",
  poshmarkOriginalPrice: "0",
  garment: "top",
  measurements: { top: {}, pants: {} },
};

function parseMeasurements(raw: unknown): Measurements {
  const source = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const out: Measurements = { top: {}, pants: {} };
  for (const garment of GARMENTS) {
    // Listings saved before shorts folded into pants kept a separate shorts set.
    const values = source[garment.id] ?? (garment.id === "pants" ? source.shorts : undefined);
    if (!values || typeof values !== "object") continue;
    for (const field of garment.fields) {
      const value = (values as Record<string, unknown>)[field.key];
      if (typeof value === "string" && value) out[garment.id][field.key] = value;
    }
  }
  return out;
}

function parseNotes(notes: string | null): ItemDetailsData {
  if (!notes) return { ...DEFAULTS, measurements: parseMeasurements(null) };
  try {
    const parsed = JSON.parse(notes);
    return {
      sellerNotes: parsed.sellerNotes || "",
      cog: parsed.cog || "",
      packageDimensions: parsed.packageDimensions || "13x10x3",
      vendooLabels: parsed.vendooLabels ?? DEFAULTS.vendooLabels,
      poshmarkOriginalPrice: parsed.poshmarkOriginalPrice ?? "0",
      garment: parsed.garment === "shorts"
        ? "pants"
        : GARMENTS.some((g) => g.id === parsed.garment) ? parsed.garment : DEFAULTS.garment,
      measurements: parseMeasurements(parsed.measurements),
    };
  } catch {
    return { ...DEFAULTS, measurements: parseMeasurements(null) };
  }
}

export function ItemDetails({ convId }: Props) {
  const queryClient = useQueryClient();
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveChainRef = useRef<Promise<void>>(Promise.resolve());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const saveGenRef = useRef(0);
  const [labelMenuOpen, setLabelMenuOpen] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState(0);
  const [labelDraft, setLabelDraft] = useState("");
  const labelDraftRef = useRef("");
  const labelInputRef = useRef<HTMLInputElement | null>(null);
  const migratedLabelsRef = useRef(false);

  const { data: conv } = useQuery({
    queryKey: ["conversation", convId],
    queryFn: () => api.conversations.get(convId),
  });

  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.conversations.list,
  });

  const { data: uiPrefs } = useQuery({
    queryKey: ["settings-ui"],
    queryFn: api.settings.ui,
  });

  useEffect(() => {
    if (!uiPrefs || migratedLabelsRef.current) return;
    migratedLabelsRef.current = true;
    const legacy = readLegacyStoredLabels();
    if (!legacy.length) return;
    if ((uiPrefs.recent_vendoo_labels || []).length) {
      clearLegacyStoredLabels();
      return;
    }
    void api.settings
      .setUi({ recent_vendoo_labels: legacy })
      .then(() => {
        clearLegacyStoredLabels();
        queryClient.invalidateQueries({ queryKey: ["settings-ui"] });
      })
      .catch(() => {
        migratedLabelsRef.current = false;
      });
  }, [uiPrefs, queryClient]);

  const hiddenLabelKeys = useMemo(
    () => new Set((uiPrefs?.hidden_vendoo_labels || []).map((label) => label.toLowerCase())),
    [uiPrefs?.hidden_vendoo_labels],
  );

  const recentLabels = useMemo(() => {
    const seen = new Set<string>(hiddenLabelKeys);
    const ordered: string[] = [];
    for (const label of [
      ...(uiPrefs?.recent_vendoo_labels || []),
      ...readLegacyStoredLabels(),
      ...(conversations || []).flatMap((item: { notes?: string | null }) => labelsFromNotes(item.notes)),
    ]) {
      const key = label.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      ordered.push(label);
    }
    return ordered.slice(0, MAX_RECENT_LABELS);
  }, [conversations, uiPrefs?.recent_vendoo_labels, hiddenLabelKeys]);

  const [details, setDetails] = useState<ItemDetailsData>({ ...DEFAULTS });
  const detailsRef = useRef(details);

  useEffect(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    saveGenRef.current += 1;
    if (conv) {
      const parsed = parseNotes(conv.notes);
      detailsRef.current = parsed;
      setDetails(parsed);
    } else {
      detailsRef.current = { ...DEFAULTS };
      setDetails({ ...DEFAULTS });
    }
  }, [convId, conv?.notes, conv?.updated_at]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveGenRef.current += 1;
    };
  }, []);

  useEffect(() => {
    setLabelMenuOpen(false);
    setActiveSuggestion(0);
    labelDraftRef.current = "";
    setLabelDraft("");
  }, [convId]);

  const save = useCallback(async (updated: ItemDetailsData) => {
    const gen = ++saveGenRef.current;
    setSaving(true);
    setSaveError(null);
    detailsRef.current = updated;
    setDetails(updated);
    // Labels newly typed into this listing come back even if removed from the history.
    const savedKeys = new Set(splitLabels(parseNotes(conv?.notes ?? null).vendooLabels).map((l) => l.toLowerCase()));
    const added = splitLabels(updated.vendooLabels).filter((label) => !savedKeys.has(label.toLowerCase()));
    rememberLabels(updated.vendooLabels, added, queryClient);
    const persist = async () => {
      try {
        if (gen !== saveGenRef.current) return;
        await api.conversations.update(convId, { notes: JSON.stringify({
          // Clear obsolete seller-entered condition; categoryOverride stays agent-managed.
          condition: "",
          sellerNotes: updated.sellerNotes,
          cog: updated.cog,
          packageDimensions: updated.packageDimensions,
          vendooLabels: updated.vendooLabels,
          poshmarkOriginalPrice: updated.poshmarkOriginalPrice,
          garment: updated.garment,
          measurements: updated.measurements,
        })});
        if (gen !== saveGenRef.current) return;
        queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
      } catch (err) {
        if (gen !== saveGenRef.current) return;
        setSaveError(err instanceof Error ? err.message : "Could not save seller details");
      } finally {
        if (gen === saveGenRef.current) setSaving(false);
      }
    };
    const queued = saveChainRef.current.catch(() => undefined).then(persist);
    saveChainRef.current = queued;
    await queued;
  }, [convId, conv?.notes, queryClient]);

  const scheduleSave = useCallback((updated: ItemDetailsData) => {
    detailsRef.current = updated;
    setDetails(updated);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => save(updated), 500);
  }, [save]);

  const f = (key: TextKey, type = "text") => ({
    className: "input",
    type,
    value: details[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => scheduleSave({ ...details, [key]: e.target.value }),
  });

  const garment = GARMENTS.find((g) => g.id === details.garment) || GARMENTS[0];
  const setMeasurement = (key: string, value: string) => scheduleSave({
    ...details,
    measurements: {
      ...details.measurements,
      [garment.id]: { ...details.measurements[garment.id], [key]: value },
    },
  });

  // Vendoo's own dates for the item: when it went live, sold, and was touched.
  const history = useMemo(() => historyRows(conv || {}), [conv]);
  const currentLabels = splitLabels(details.vendooLabels);
  const selectedKeys = new Set(currentLabels.map((label) => label.toLowerCase()));
  const token = labelDraft.trim().toLowerCase();
  const labelSuggestions = recentLabels.filter((label) => {
    const key = label.toLowerCase();
    if (selectedKeys.has(key)) return false;
    return !token || key.includes(token);
  });

  const commitLabels = (vendooLabels: string, draft = "") => {
    const next = { ...detailsRef.current, vendooLabels };
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    labelDraftRef.current = draft;
    setLabelDraft(draft);
    setActiveSuggestion(0);
    void save(next);
  };

  const chooseLabel = (suggestion: string) => {
    commitLabels(addLabel(detailsRef.current.vendooLabels, suggestion));
    setLabelMenuOpen(true);
    labelInputRef.current?.focus();
  };

  const commitDraft = (rawDraft = labelDraftRef.current) => {
    const draft = rawDraft.trim();
    if (!draft) return;
    commitLabels(addLabel(detailsRef.current.vendooLabels, draft));
    setLabelMenuOpen(true);
  };

  const removeCommittedLabel = (label: string) => {
    commitLabels(removeLabel(detailsRef.current.vendooLabels, label), labelDraftRef.current);
    labelInputRef.current?.focus();
  };

  const forgetLabel = (label: string) => {
    const key = label.toLowerCase();
    queryClient.setQueryData(["settings-ui"], (prev: typeof uiPrefs) => prev && {
      ...prev,
      recent_vendoo_labels: prev.recent_vendoo_labels.filter((item) => item.toLowerCase() !== key),
      hidden_vendoo_labels: [label, ...(prev.hidden_vendoo_labels || [])],
    });
    setActiveSuggestion((i) => Math.max(0, Math.min(i, labelSuggestions.length - 2)));
    void api.settings
      .setUi({ forget_label: label })
      .catch(() => { /* best-effort; refetch below restores truth */ })
      .finally(() => queryClient.invalidateQueries({ queryKey: ["settings-ui"] }));
  };

  return (
    <div className="item-details">
      <section className="item-section" aria-labelledby="item-section-listing">
        <h3 className="item-section-title" id="item-section-listing">Notes &amp; Labels</h3>
        <div className="item-field item-field-notes">
          <label className="label">Notes</label>
          <textarea
            className="input"
            value={details.sellerNotes}
            placeholder="Flaws, provenance, sizing quirks, or other seller notes"
            rows={3}
            onChange={(e) => scheduleSave({ ...details, sellerNotes: e.target.value })}
          />
        </div>
        <div className="item-field">
          <label className="label">Labels</label>
          <div
            className="label-input"
            onClick={() => labelInputRef.current?.focus()}
          >
            {currentLabels.map((label) => (
              <span key={label} className="label-chip">
                <span className="label-chip-text">{label}</span>
                <button
                  type="button"
                  aria-label={`Remove ${label}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    removeCommittedLabel(label);
                  }}
                >
                  ×
                </button>
              </span>
            ))}
            <input
              ref={labelInputRef}
              className="input label-input-field"
              type="text"
              value={labelDraft}
              placeholder={currentLabels.length ? "Add another" : "Add labels"}
              autoComplete="off"
              role="combobox"
              aria-expanded={labelMenuOpen && labelSuggestions.length > 0}
              aria-controls="label-history"
              aria-autocomplete="list"
              onChange={(e) => {
                labelDraftRef.current = e.target.value;
                setLabelDraft(e.target.value);
                setLabelMenuOpen(true);
                setActiveSuggestion(0);
              }}
              onFocus={() => { setLabelMenuOpen(true); setActiveSuggestion(0); }}
              onClick={() => { setLabelMenuOpen(true); setActiveSuggestion(0); }}
              onBlur={() => {
                setTimeout(() => {
                  setLabelMenuOpen(false);
                  commitDraft();
                }, 120);
              }}
              onKeyDown={(e) => {
                if (e.key === "Backspace" && !labelDraft && currentLabels.length) {
                  e.preventDefault();
                  removeCommittedLabel(currentLabels[currentLabels.length - 1]);
                  return;
                }
                if (e.key === "," || e.key === "Enter") {
                  if (labelDraft.trim()) {
                    e.preventDefault();
                    if (e.key === "Enter" && labelMenuOpen && labelSuggestions.length) {
                      chooseLabel(labelSuggestions[activeSuggestion] || labelSuggestions[0]);
                    } else {
                      commitDraft();
                    }
                    return;
                  }
                  if (e.key === "Enter" && labelMenuOpen && labelSuggestions.length) {
                    e.preventDefault();
                    chooseLabel(labelSuggestions[activeSuggestion] || labelSuggestions[0]);
                  }
                  return;
                }
                if (!labelMenuOpen && e.key === "ArrowDown") {
                  setLabelMenuOpen(true);
                  return;
                }
                if (!labelSuggestions.length) return;
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setLabelMenuOpen(true);
                  setActiveSuggestion((i) => (i + 1) % labelSuggestions.length);
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActiveSuggestion((i) => (i - 1 + labelSuggestions.length) % labelSuggestions.length);
                } else if (e.key === "Escape") {
                  setLabelMenuOpen(false);
                }
              }}
            />
          </div>
          {labelMenuOpen && labelSuggestions.length > 0 && (
            <div className="label-history" id="label-history" role="listbox">
              {labelSuggestions.map((label, i) => (
                <div
                  key={label}
                  className={`label-history-row${i === activeSuggestion ? " active" : ""}`}
                  onMouseEnter={() => setActiveSuggestion(i)}
                >
                  <button
                    type="button"
                    role="option"
                    aria-selected={i === activeSuggestion}
                    className="label-history-item"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => chooseLabel(label)}
                  >
                    {label}
                  </button>
                  <button
                    type="button"
                    className="label-history-remove"
                    aria-label={`Remove "${label}" from label history`}
                    title="Remove from history"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => forgetLabel(label)}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="item-section" aria-labelledby="item-section-pricing">
        <h3 className="item-section-title" id="item-section-pricing">Pricing &amp; Shipping</h3>
        <div className="item-row item-row-3">
          <div className="item-field">
            <label className="label">COG ($)</label>
            <input {...f("cog", "number")} step="0.01" placeholder="0.00" />
          </div>
          <div className="item-field">
            <label className="label">Posh Orig ($)</label>
            <input {...f("poshmarkOriginalPrice", "number")} step="1" placeholder="0" />
          </div>
          <div className="item-field">
            <label className="label">Package L×W×H</label>
            <input {...f("packageDimensions")} placeholder="13x10x3" />
          </div>
        </div>
      </section>

      <section className="item-section" aria-labelledby="item-section-measurements">
        <div className="item-section-header">
          <h3 className="item-section-title" id="item-section-measurements">Measurements (in)</h3>
          <div className="pr-pills item-garment-pills" role="radiogroup" aria-label="Garment type">
            {GARMENTS.map((g) => (
              <button
                key={g.id}
                type="button"
                role="radio"
                aria-checked={g.id === garment.id}
                className={`pr-pill${g.id === garment.id ? " is-active" : ""}`}
                onClick={() => {
                  if (g.id === garment.id) return;
                  if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
                  void save({ ...details, garment: g.id });
                }}
              >
                {g.label}
              </button>
            ))}
          </div>
        </div>
        <div className={`item-row item-row-${garment.fields.length}`}>
          {garment.fields.map((field) => (
            <div className="item-field" key={`${garment.id}-${field.key}`}>
              <label className="label">{field.label}</label>
              <input
                className="input"
                type="number"
                step="0.25"
                placeholder={field.placeholder}
                value={details.measurements[garment.id][field.key] || ""}
                onChange={(e) => setMeasurement(field.key, e.target.value)}
              />
            </div>
          ))}
        </div>
      </section>

      {history.length > 0 && (
        <section className="item-section" aria-labelledby="item-section-history">
          <h3 className="item-section-title" id="item-section-history">Vendoo History</h3>
          <dl className="item-history">
            {history.map((row) => (
              <div className={`item-history-row${row.nested ? " is-nested" : ""}`} key={row.key}>
                <dt>{row.label}</dt>
                <dd title={row.iso}>
                  <span className="item-history-age">{row.age}</span>
                  <span className="item-history-date">{row.when}</span>
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}
      {saving && <span className="item-saving">SAVING…</span>}
      {saveError && (
        <span className="item-saving text-error">
          {saveError}{" "}
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => void save(details)}>
            Retry
          </button>
        </span>
      )}
    </div>
  );
}
