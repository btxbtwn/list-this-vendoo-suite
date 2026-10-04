import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BulkUploadDefaults } from "../bulkPhotoUpload";
import { formatMoney } from "./analyticsFormat";
import { BOXES_QUERY_KEY, boxStoreName } from "./boughtBoxes";

interface Props {
  count: number;
  onCancel: () => void;
  onConfirm: (defaults: BulkUploadDefaults) => void;
}

const EMPTY_DEFAULTS: BulkUploadDefaults = { cog: "", labels: "" };

export function BulkUploadDialog({ count, onCancel, onConfirm }: Props) {
  const [defaults, setDefaults] = useState<BulkUploadDefaults>(EMPTY_DEFAULTS);
  const boxes = useQuery({ queryKey: BOXES_QUERY_KEY, queryFn: api.boxes.list }).data?.boxes ?? [];
  const box = boxes.find((row) => row.id === defaults.boxId);
  const cogRef = useRef<HTMLInputElement>(null);
  const onCancelRef = useRef(onCancel);

  useEffect(() => {
    onCancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    const focusTimer = window.setTimeout(() => cogRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancelRef.current();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const cogNumber = defaults.cog.trim() ? Number(defaults.cog) : null;
  const invalidCog = cogNumber !== null && (!Number.isFinite(cogNumber) || cogNumber < 0);

  return createPortal(
    <div className="confirm-dialog bulk-upload-dialog" role="presentation">
      <button
        type="button"
        className="confirm-dialog-backdrop"
        aria-label="Cancel bulk upload"
        onClick={onCancel}
      />
      <form
        className="confirm-dialog-popup bulk-upload-popup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bulk-upload-title"
        onSubmit={(event) => {
          event.preventDefault();
          if (!invalidCog) onConfirm(defaults);
        }}
      >
        <div className="confirm-dialog-header">
          <h2 id="bulk-upload-title" className="confirm-dialog-title">
            Set details for {count} listings
          </h2>
          <p className="confirm-dialog-description">
            These optional values will be added to every draft in this bulk upload.
          </p>
        </div>
        <div className="bulk-upload-fields">
          {boxes.length ? (
            <label className="bulk-upload-field is-wide">
              <span className="label">Box</span>
              <select
                className="input"
                value={defaults.boxId || ""}
                onChange={(event) => setDefaults((current) => ({ ...current, boxId: event.target.value || undefined }))}
              >
                <option value="">Not from a box</option>
                {boxes.map((row) => (
                  <option key={row.id} value={row.id}>{boxStoreName(row.store)} · {row.title}</option>
                ))}
              </select>
              <span className="bulk-upload-help">See what this box makes back under Sourcing → Boxes you bought.</span>
            </label>
          ) : null}
          <label className="bulk-upload-field">
            <span className="label">Cost of goods (COG)</span>
            <input
              ref={cogRef}
              className="input"
              type="number"
              min="0"
              step="0.01"
              inputMode="decimal"
              placeholder={box?.cost_per_piece != null ? box.cost_per_piece.toFixed(2) : "0.00"}
              value={defaults.cog}
              onChange={(event) => setDefaults((current) => ({ ...current, cog: event.target.value }))}
            />
            {box?.cost_per_piece != null ? (
              <span className="bulk-upload-help">Leave blank to use the box's {formatMoney(box.cost_per_piece)} a piece.</span>
            ) : null}
          </label>
          <label className="bulk-upload-field">
            <span className="label">Labels</span>
            <input
              className="input"
              type="text"
              placeholder="To List, Bin 4"
              value={defaults.labels}
              onChange={(event) => setDefaults((current) => ({ ...current, labels: event.target.value }))}
            />
            <span className="bulk-upload-help">Separate multiple labels with commas.</span>
          </label>
        </div>
        <div className="confirm-dialog-footer">
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={invalidCog}>
            Create {count} listings
          </button>
        </div>
      </form>
    </div>,
    document.body,
  );
}
