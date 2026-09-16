import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  convId: string;
}

interface ItemDetailsData {
  condition: string;
  cog: string;
  packageDimensions: string;
  pitToPit: string;
  length: string;
  sleeve: string;
  vendooLabels: string;
  categoryOverride: string;
  poshmarkOriginalPrice: string;
}

const RECENT_LABELS_KEY = "vendoo-studio.recent-labels";
const MAX_RECENT_LABELS = 12;

function splitLabels(raw: string): string[] {
  return raw.split(",").map((part) => part.trim()).filter(Boolean);
}

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

function rememberLabels(raw: string, queryClient?: ReturnType<typeof useQueryClient>) {
  void api.settings
    .setUi({ remember_labels: raw })
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

function applyLabelSuggestion(raw: string, suggestion: string, known: string[]): string {
  const parts = splitLabels(raw);
  const trailing = /,\s*$/.test(raw);
  const lastToken = trailing ? "" : (raw.includes(",") ? raw.slice(raw.lastIndexOf(",") + 1) : raw).trim();
  const lastIsKnown = known.some((label) => label.toLowerCase() === lastToken.toLowerCase());
  const completed = trailing || lastIsKnown || !raw.trim()
    ? parts
    : (raw.includes(",") ? parts.slice(0, -1) : []);
  if (completed.some((label) => label.toLowerCase() === suggestion.toLowerCase())) {
    return completed.join(", ");
  }
  return [...completed, suggestion].join(", ");
}

const CATEGORY_SUGGESTIONS = [
  "Clothing, Shoes & Accessories > Women > Women's Clothing > Tops",
  "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > T-Shirts",
  "Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts > Polos",
  "Clothing, Shoes & Accessories > Women > Women's Clothing > Dresses",
  "Clothing, Shoes & Accessories > Men > Men's Clothing > Sweaters",
  "Clothing, Shoes & Accessories > Women > Women's Clothing > Sweaters",
  "Clothing, Shoes & Accessories > Men > Men's Clothing > Jeans",
  "Clothing, Shoes & Accessories > Women > Women's Clothing > Jeans",
];

const DEFAULTS: ItemDetailsData = {
  condition: "",
  cog: "",
  packageDimensions: "13x10x3",
  pitToPit: "",
  length: "",
  sleeve: "",
  vendooLabels: "",
  categoryOverride: "",
  poshmarkOriginalPrice: "0",
};

function parseNotes(notes: string | null): ItemDetailsData {
  if (!notes) return { ...DEFAULTS };
  try {
    const parsed = JSON.parse(notes);
    return {
      condition: parsed.condition || "",
      cog: parsed.cog || "",
      packageDimensions: parsed.packageDimensions || "13x10x3",
      pitToPit: parsed.pitToPit || "",
      length: parsed.length || "",
      sleeve: parsed.sleeve || "",
      vendooLabels: parsed.vendooLabels ?? DEFAULTS.vendooLabels,
      categoryOverride: parsed.categoryOverride || "",
      poshmarkOriginalPrice: parsed.poshmarkOriginalPrice ?? "0",
    };
  } catch {
    return { ...DEFAULTS };
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

  const recentLabels = useMemo(() => {
    const seen = new Set<string>();
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
  }, [conversations, uiPrefs?.recent_vendoo_labels]);

  const [details, setDetails] = useState<ItemDetailsData>({ ...DEFAULTS });

  useEffect(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    saveGenRef.current += 1;
    if (conv) setDetails(parseNotes(conv.notes));
    else setDetails({ ...DEFAULTS });
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
  }, [convId]);

  const save = useCallback(async (updated: ItemDetailsData) => {
    const gen = ++saveGenRef.current;
    setSaving(true);
    setSaveError(null);
    setDetails(updated);
    rememberLabels(updated.vendooLabels, queryClient);
    const persist = async () => {
      try {
        if (gen !== saveGenRef.current) return;
        await api.conversations.update(convId, { notes: JSON.stringify({
          condition: updated.condition,
          cog: updated.cog,
          packageDimensions: updated.packageDimensions,
          pitToPit: updated.pitToPit,
          length: updated.length,
          sleeve: updated.sleeve,
          vendooLabels: updated.vendooLabels,
          categoryOverride: updated.categoryOverride,
          poshmarkOriginalPrice: updated.poshmarkOriginalPrice,
        })});
        if (gen !== saveGenRef.current) return;
        queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
      } catch (err: any) {
        if (gen !== saveGenRef.current) return;
        setSaveError(err?.message || "Could not save seller details");
      } finally {
        if (gen === saveGenRef.current) setSaving(false);
      }
    };
    const queued = saveChainRef.current.catch(() => undefined).then(persist);
    saveChainRef.current = queued;
    await queued;
  }, [convId, queryClient]);

  const scheduleSave = useCallback((updated: ItemDetailsData) => {
    setDetails(updated);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => save(updated), 500);
  }, [save]);

  const f = (key: keyof ItemDetailsData, type = "text") => ({
    className: "input",
    type,
    value: details[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => scheduleSave({ ...details, [key]: e.target.value }),
  });

  const currentLabels = splitLabels(details.vendooLabels);
  const selectedKeys = new Set(currentLabels.map((label) => label.toLowerCase()));
  const trailing = /,\s*$/.test(details.vendooLabels);
  const lastToken = trailing || !details.vendooLabels.trim()
    ? ""
    : (details.vendooLabels.includes(",")
        ? details.vendooLabels.slice(details.vendooLabels.lastIndexOf(",") + 1)
        : details.vendooLabels).trim().toLowerCase();
  const token = lastToken && !recentLabels.some((label) => label.toLowerCase() === lastToken)
    ? lastToken
    : "";
  const labelSuggestions = recentLabels.filter((label) => {
    const key = label.toLowerCase();
    if (selectedKeys.has(key) && key !== token) return false;
    return !token || key.includes(token);
  });

  const chooseLabel = (suggestion: string) => {
    const next = { ...details, vendooLabels: applyLabelSuggestion(details.vendooLabels, suggestion, recentLabels) };
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    void save(next);
    setActiveSuggestion(0);
    setLabelMenuOpen(true);
  };

  return (
    <div className="item-details">
      <div className="item-row">
        <div className="item-field">
          <label className="label">Condition</label>
          <input {...f("condition")} placeholder="Good" />
        </div>
        <div className="item-field">
          <label className="label">Category</label>
          <input {...f("categoryOverride")} placeholder="Select a category" list="cats" />
          <datalist id="cats">{CATEGORY_SUGGESTIONS.map(c => <option key={c} value={c} />)}</datalist>
        </div>
        <div className="item-field">
          <label className="label">Labels</label>
          <input
            {...f("vendooLabels")}
            placeholder="Add labels"
            autoComplete="off"
            role="combobox"
            aria-expanded={labelMenuOpen && labelSuggestions.length > 0}
            aria-controls="label-history"
            aria-autocomplete="list"
            onFocus={() => { setLabelMenuOpen(true); setActiveSuggestion(0); }}
            onClick={() => { setLabelMenuOpen(true); setActiveSuggestion(0); }}
            onBlur={() => setTimeout(() => setLabelMenuOpen(false), 120)}
            onKeyDown={(e) => {
              if (!labelMenuOpen && (e.key === "ArrowDown" || e.key === "Enter")) {
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
              } else if (e.key === "Enter" && labelMenuOpen) {
                e.preventDefault();
                chooseLabel(labelSuggestions[activeSuggestion] || labelSuggestions[0]);
              } else if (e.key === "Escape") {
                setLabelMenuOpen(false);
              }
            }}
          />
          {labelMenuOpen && labelSuggestions.length > 0 && (
            <div className="label-history" id="label-history" role="listbox">
              {labelSuggestions.map((label, i) => (
                <button
                  key={label}
                  type="button"
                  role="option"
                  aria-selected={i === activeSuggestion}
                  className={`label-history-item${i === activeSuggestion ? " active" : ""}`}
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setActiveSuggestion(i)}
                  onClick={() => chooseLabel(label)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="item-field">
          <label className="label">Package L×W×H</label>
          <input {...f("packageDimensions")} placeholder="13x10x3" />
        </div>
      </div>
      <div className="item-row item-row-measures">
        <div className="item-field">
          <label className="label">COG ($)</label>
          <input {...f("cog", "number")} step="0.01" placeholder="0.00" />
        </div>
        <div className="item-field">
          <label className="label">Posh Orig ($)</label>
          <input {...f("poshmarkOriginalPrice", "number")} step="1" placeholder="0" />
        </div>
        <div className="item-field">
          <label className="label">Pit to Pit</label>
          <input {...f("pitToPit", "number")} step="0.25" placeholder="22.5" />
        </div>
        <div className="item-field">
          <label className="label">Length</label>
          <input {...f("length", "number")} step="0.25" placeholder="27" />
        </div>
        <div className="item-field">
          <label className="label">Sleeve</label>
          <input {...f("sleeve", "number")} step="0.25" placeholder="9" />
        </div>
      </div>
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
