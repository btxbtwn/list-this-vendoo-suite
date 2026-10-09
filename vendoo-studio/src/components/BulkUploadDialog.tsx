import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BulkUploadDefaults, BulkUploadItem } from "../bulkPhotoUpload";
import { formatMoney } from "./analyticsFormat";
import { BOXES_QUERY_KEY, boxStoreName } from "./boxPurchases";
import { GARMENTS, garmentFields, guessGarment, type Garment } from "./garmentMeasurements";
import { dragHasFiles, listingTitleForFolder, moveItem, type PhotoFolderGroup } from "../photoDrop";

interface Props {
  groups: PhotoFolderGroup[];
  onCancel: () => void;
  /** Create every draft; `generate` also starts generating them from their photos. */
  onConfirm: (defaults: BulkUploadDefaults, items: BulkUploadItem[], generate: boolean) => void;
}

const EMPTY_DEFAULTS: BulkUploadDefaults = { cog: "", labels: "" };

type DragSpot = { group: number; photo: number };

type Row = { sku: string; garment: Garment; measurements: Record<string, string> };

/**
 * Everything a bulk upload needs in one window, before anything is created:
 * photo order, the box, COG and labels every draft shares, and each item's
 * own SKU and measurements. Click a photo to read the tape in it.
 */
export function BulkUploadDialog({ groups: initialGroups, onCancel, onConfirm }: Props) {
  const [defaults, setDefaults] = useState<BulkUploadDefaults>(EMPTY_DEFAULTS);
  const boxes = useQuery({ queryKey: BOXES_QUERY_KEY, queryFn: api.boxes.list }).data?.boxes ?? [];
  const box = boxes.find((row) => row.id === defaults.boxId);
  const [groups, setGroups] = useState(initialGroups);
  const [rows, setRows] = useState<Row[]>(() => initialGroups.map((group) => ({
    sku: "",
    garment: guessGarment(listingTitleForFolder(group.folder)),
    measurements: {},
  })));
  const [dragFrom, setDragFrom] = useState<DragSpot | null>(null);
  const [dropOn, setDropOn] = useState<DragSpot | null>(null);
  const [zoom, setZoom] = useState<DragSpot | null>(null);
  // One preview URL per picked file; reordering only shuffles which file sits where.
  const [previewUrls, setPreviewUrls] = useState<Map<File, string>>(() => new Map());
  const formRef = useRef<HTMLFormElement>(null);
  const cogRef = useRef<HTMLInputElement>(null);
  const zoomRef = useRef(zoom);
  const onCancelRef = useRef(onCancel);
  const count = groups.length;

  // Created and revoked in the same effect so StrictMode's remount gets fresh URLs.
  useEffect(() => {
    const urls = new Map(initialGroups.flatMap((group) => group.files).map((file) => [file, URL.createObjectURL(file)]));
    setPreviewUrls(urls);
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, [initialGroups]);

  const resetDrag = () => {
    setDragFrom(null);
    setDropOn(null);
  };

  // Photos only move within their own listing; the first one becomes the cover.
  const dropPhoto = (target: DragSpot) => {
    const source = dragFrom;
    resetDrag();
    if (!source || source.group !== target.group) return;
    setGroups((current) => current.map((group, index) => (
      index === target.group ? { ...group, files: moveItem(group.files, source.photo, target.photo) } : group
    )));
  };

  const setRow = (index: number, patch: Partial<Row>) => setRows((current) => current.map((row, i) => (
    i === index ? { ...row, ...patch } : row
  )));

  useEffect(() => {
    zoomRef.current = zoom;
    onCancelRef.current = onCancel;
  }, [zoom, onCancel]);

  useEffect(() => {
    const focusTimer = window.setTimeout(() => cogRef.current?.focus(), 0);
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (zoomRef.current) setZoom(null);
      else onCancelRef.current();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const cogNumber = defaults.cog.trim() ? Number(defaults.cog) : null;
  const invalidCog = cogNumber !== null && (!Number.isFinite(cogNumber) || cogNumber < 0);

  const confirm = (generate: boolean) => {
    if (invalidCog) return;
    onConfirm(defaults, groups.map((group, index) => ({ ...group, ...rows[index]! })), generate);
  };

  // Enter moves on like a spreadsheet instead of submitting half a box.
  const onInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const inputs = Array.from(formRef.current?.querySelectorAll<HTMLInputElement>("input") || []);
    inputs[inputs.indexOf(event.currentTarget) + 1]?.focus();
  };

  const zoomFiles = zoom ? groups[zoom.group]!.files : [];

  return createPortal(
    <div className="confirm-dialog bulk-upload-dialog" role="presentation">
      <button
        type="button"
        className="confirm-dialog-backdrop"
        aria-label="Cancel bulk upload"
        onClick={onCancel}
      />
      <form
        ref={formRef}
        className="confirm-dialog-popup bulk-upload-popup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bulk-upload-title"
        onSubmit={(event) => {
          event.preventDefault();
          confirm(true);
        }}
      >
        <div className="confirm-dialog-header">
          <h2 id="bulk-upload-title" className="confirm-dialog-title">
            Set details for {count} listings
          </h2>
          <p className="confirm-dialog-description">
            Box, COG and labels go on every draft. Drag photos to set their order; the first one is
            the cover, and a click enlarges one. Type each item's SKU and measurements in inches, or
            leave them blank: a typed SKU is kept as is, a blank one is made up from the brand and size.
          </p>
        </div>
        <div className="bulk-upload-fields">
          {boxes.length ? (
            <label className="bulk-upload-field">
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
              onKeyDown={onInputKeyDown}
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
              onKeyDown={onInputKeyDown}
            />
            <span className="bulk-upload-help">Separate multiple labels with commas.</span>
          </label>
        </div>
        <ul className="bulk-upload-groups" aria-label="Each listing's photos, SKU and measurements">
          {groups.map((group, groupIndex) => {
            const title = listingTitleForFolder(group.folder);
            const row = rows[groupIndex]!;
            return (
              <li key={group.folder ?? groupIndex} className="bulk-upload-group">
                <div className="bulk-measure-head">
                  <span className="bulk-measure-title" title={title}>
                    {title}
                    <span className="photo-tray-meta"> · {group.files.length} photos</span>
                  </span>
                  <label className="bulk-measure-sku">
                    <span className="label">SKU</span>
                    <input
                      className="input"
                      type="text"
                      autoComplete="off"
                      spellCheck={false}
                      aria-label={`SKU for ${title}`}
                      value={row.sku}
                      onChange={(event) => setRow(groupIndex, { sku: event.target.value })}
                      onKeyDown={onInputKeyDown}
                    />
                  </label>
                  <div className="pr-pills item-garment-pills" role="radiogroup" aria-label={`Garment type for ${title}`}>
                    {GARMENTS.map((g) => (
                      <button
                        key={g.id}
                        type="button"
                        role="radio"
                        tabIndex={-1}
                        aria-checked={g.id === row.garment}
                        className={`pr-pill${g.id === row.garment ? " is-active" : ""}`}
                        onClick={() => setRow(groupIndex, { garment: g.id })}
                      >
                        {g.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="photo-strip">
                  {group.files.map((file, photoIndex) => {
                    const spot = { group: groupIndex, photo: photoIndex };
                    const canReorder = group.files.length > 1;
                    const isDragging = dragFrom?.group === groupIndex && dragFrom.photo === photoIndex;
                    const isDropTarget = dropOn?.group === groupIndex && dropOn.photo === photoIndex;
                    return (
                      <div
                        key={`${file.name}-${file.lastModified}-${file.size}`}
                        className={[
                          "photo-thumb",
                          canReorder ? "photo-thumb-reorderable" : "",
                          isDragging ? "is-dragging" : "",
                          isDropTarget ? "is-drop-target" : "",
                        ].filter(Boolean).join(" ")}
                        draggable={canReorder}
                        title={canReorder ? `${file.name} · drag to reorder, click to enlarge` : file.name}
                        onClick={() => setZoom(spot)}
                        onDragStart={(event) => {
                          event.dataTransfer.effectAllowed = "move";
                          event.dataTransfer.setData("text/plain", file.name);
                          setDragFrom(spot);
                        }}
                        onDragOver={(event) => {
                          if (!dragFrom || dragFrom.group !== groupIndex || isDragging) return;
                          event.preventDefault();
                          event.stopPropagation();
                          event.dataTransfer.dropEffect = "move";
                          if (!isDropTarget) setDropOn(spot);
                        }}
                        onDrop={(event) => {
                          if (dragHasFiles(event.dataTransfer)) return;
                          event.preventDefault();
                          event.stopPropagation();
                          dropPhoto(spot);
                        }}
                        onDragEnd={resetDrag}
                      >
                        {previewUrls.has(file) ? <img src={previewUrls.get(file)} alt="" draggable={false} /> : null}
                        <div className="photo-thumb-num">{String(photoIndex + 1).padStart(2, "0")}</div>
                      </div>
                    );
                  })}
                </div>
                <div className="bulk-measure-fields">
                  {garmentFields(row.garment).map((field) => (
                    <label className="bulk-measure-field" key={`${row.garment}-${field.key}`}>
                      <span className="label">{field.label}</span>
                      <input
                        className="input"
                        type="number"
                        step="0.25"
                        min="0"
                        inputMode="decimal"
                        value={row.measurements[field.key] || ""}
                        onChange={(event) => setRow(groupIndex, {
                          measurements: { ...row.measurements, [field.key]: event.target.value },
                        })}
                        onKeyDown={onInputKeyDown}
                      />
                    </label>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="confirm-dialog-footer">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <span className="bulk-measure-spacer" />
          <button type="button" className="btn btn-secondary" disabled={invalidCog} onClick={() => confirm(false)}>
            Create drafts only
          </button>
          <button type="submit" className="btn btn-primary" disabled={invalidCog}>
            Create and generate {count}
          </button>
        </div>
      </form>
      {zoom ? (
        <PhotoZoom
          urls={zoomFiles.map((file) => previewUrls.get(file) || "")}
          index={zoom.photo}
          onStep={(photo) => setZoom({ ...zoom, photo })}
          onClose={() => setZoom(null)}
        />
      ) : null}
    </div>,
    document.body,
  );
}

function PhotoZoom({
  urls,
  index,
  onStep,
  onClose,
}: {
  urls: string[];
  index: number;
  onStep: (index: number) => void;
  onClose: () => void;
}) {
  const step = (delta: number) => onStep((index + delta + urls.length) % urls.length);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  return (
    <div
      ref={ref}
      className="photo-lightbox"
      role="dialog"
      aria-modal="true"
      tabIndex={-1}
      aria-label={`Photo ${index + 1} of ${urls.length}`}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") step(-1);
        if (event.key === "ArrowRight") step(1);
      }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
    >
      <button type="button" className="photo-lightbox-close" onClick={onClose} aria-label="Close">
        x
      </button>
      {urls.length > 1 && (
        <button type="button" className="photo-lightbox-nav photo-lightbox-prev" onClick={() => step(-1)} aria-label="Previous photo">
          ‹
        </button>
      )}
      <img className="photo-lightbox-image" src={urls[index]} alt={`Photo ${index + 1}`} onClick={onClose} />
      {urls.length > 1 && (
        <button type="button" className="photo-lightbox-nav photo-lightbox-next" onClick={() => step(1)} aria-label="Next photo">
          ›
        </button>
      )}
      <div className="photo-lightbox-meta">{String(index + 1).padStart(2, "0")} / {String(urls.length).padStart(2, "0")}</div>
    </div>
  );
}
