import React, { useState, useEffect, useRef, useCallback } from "react";
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
  vendooLabels: string;
  categoryOverride: string;
  poshmarkOriginalPrice: string;
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
  vendooLabels: "To List",
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
      vendooLabels: parsed.vendooLabels || DEFAULTS.vendooLabels,
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
  const [saving, setSaving] = useState(false);

  const { data: conv } = useQuery({
    queryKey: ["conversation", convId],
    queryFn: () => api.conversations.get(convId),
  });

  const [details, setDetails] = useState<ItemDetailsData>({ ...DEFAULTS });

  useEffect(() => {
    if (conv) setDetails(parseNotes(conv.notes));
  }, [conv]);

  const save = useCallback(async (updated: ItemDetailsData) => {
    setSaving(true);
    setDetails(updated);
    await api.conversations.update(convId, { notes: JSON.stringify({
      condition: updated.condition,
      cog: updated.cog,
      packageDimensions: updated.packageDimensions,
      pitToPit: updated.pitToPit,
      length: updated.length,
      vendooLabels: updated.vendooLabels,
      categoryOverride: updated.categoryOverride,
      poshmarkOriginalPrice: updated.poshmarkOriginalPrice,
    })});
    queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
    setSaving(false);
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

  return (
    <div className="item-details">
      <div className="item-row">
        <div className="item-field">
          <label className="label">Condition</label>
          <input {...f("condition")} placeholder="Good" />
        </div>
        <div className="item-field">
          <label className="label">Category</label>
          <input {...f("categoryOverride")} placeholder="Clothing > Women > Tops" list="cats" />
          <datalist id="cats">{CATEGORY_SUGGESTIONS.map(c => <option key={c} value={c} />)}</datalist>
        </div>
        <div className="item-field">
          <label className="label">Labels</label>
          <input {...f("vendooLabels")} placeholder="To List" />
        </div>
        <div className="item-field">
          <label className="label">Package L×W×H</label>
          <input {...f("packageDimensions")} placeholder="13x10x3" />
        </div>
      </div>
      <div className="item-row">
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
      </div>
      {saving && <span className="item-saving">SAVING…</span>}
    </div>
  );
}
