import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { BulkUploadDefaults } from "../bulkPhotoUpload";

interface Props {
  count: number;
  onCancel: () => void;
  onConfirm: (defaults: BulkUploadDefaults) => void;
}

const EMPTY_DEFAULTS: BulkUploadDefaults = { cog: "", labels: "" };

export function BulkUploadDialog({ count, onCancel, onConfirm }: Props) {
  const [defaults, setDefaults] = useState<BulkUploadDefaults>(EMPTY_DEFAULTS);
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
          <label className="bulk-upload-field">
            <span className="label">Cost of goods (COG)</span>
            <input
              ref={cogRef}
              className="input"
              type="number"
              min="0"
              step="0.01"
              inputMode="decimal"
              placeholder="0.00"
              value={defaults.cog}
              onChange={(event) => setDefaults((current) => ({ ...current, cog: event.target.value }))}
            />
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
