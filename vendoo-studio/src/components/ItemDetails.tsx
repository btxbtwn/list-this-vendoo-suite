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
  measurements: string;
  vendooLabels: string;
}

const DEFAULTS: ItemDetailsData = {
  condition: "",
  cog: "",
  packageDimensions: "13x10x3",
  measurements: "",
  vendooLabels: "To List",
};

function parseNotes(notes: string | null): ItemDetailsData {
  if (!notes) return { ...DEFAULTS };
  try {
    const parsed = JSON.parse(notes);
    return {
      condition: parsed.condition || "",
      cog: parsed.cog || "",
      packageDimensions: parsed.packageDimensions || "13x10x3",
      measurements: parsed.measurements || "",
      vendooLabels: parsed.vendooLabels || DEFAULTS.vendooLabels,
    };
  } catch {
    return { ...DEFAULTS, measurements: notes || "" };
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
    if (conv) {
      setDetails(parseNotes(conv.notes));
    }
  }, [conv]);

  const save = useCallback(async (updated: ItemDetailsData) => {
    setSaving(true);
    setDetails(updated);
    const notes = JSON.stringify({
      condition: updated.condition,
      cog: updated.cog,
      packageDimensions: updated.packageDimensions,
      measurements: updated.measurements,
      vendooLabels: updated.vendooLabels,
    });
    await api.conversations.update(convId, { notes });
    queryClient.invalidateQueries({ queryKey: ["conversation", convId] });
    setSaving(false);
  }, [convId, queryClient]);

  const scheduleSave = useCallback((updated: ItemDetailsData) => {
    setDetails(updated);
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => save(updated), 500);
  }, [save]);

  const fieldProps = (key: keyof ItemDetailsData, type = "text") => ({
    className: "input",
    type,
    value: details[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      scheduleSave({ ...details, [key]: e.target.value });
    },
    style: { padding: "6px 8px", fontSize: 12 },
  });

  return (
    <div
      style={{
        padding: "8px 16px",
        borderBottom: "1px solid var(--color-border)",
        background: "var(--color-bg)",
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          alignItems: "flex-end",
        }}
      >
        <div style={{ minWidth: 140 }}>
          <label className="label">Condition</label>
          <input {...fieldProps("condition")} placeholder="Good, Excellent, Fair..." />
        </div>

        <div style={{ minWidth: 80 }}>
          <label className="label">COG ($)</label>
          <input {...fieldProps("cog", "number")} step="0.01" placeholder="0.00" />
        </div>

        <div style={{ minWidth: 100 }}>
          <label className="label">Package (LxWxH)</label>
          <input {...fieldProps("packageDimensions")} placeholder="13x10x3" />
        </div>

        <div style={{ minWidth: 130 }}>
          <label className="label">Labels</label>
          <input {...fieldProps("vendooLabels")} placeholder="To List, A19" />
        </div>

        {saving && (
          <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>Saving…</span>
        )}
      </div>

      <div style={{ marginTop: 6 }}>
        <label className="label">Measurements</label>
        <textarea
          {...fieldProps("measurements")}
          placeholder='e.g. Pit to pit: 23"
Length: 27"'
          style={{ height: 44, fontSize: 12, padding: "6px 8px" }}
        />
      </div>
    </div>
  );
}
