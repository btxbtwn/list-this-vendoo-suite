import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BulkUploadDefaults } from "../bulkPhotoUpload";
import { formatMoney } from "./analyticsFormat";
import { BOXES_QUERY_KEY, boxStoreName } from "./boxPurchases";
import { dragHasFiles, listingTitleForFolder, moveItem, type PhotoFolderGroup } from "../photoDrop";

interface Props {
  groups: PhotoFolderGroup[];
  onCancel: () => void;
  onConfirm: (defaults: BulkUploadDefaults, groups: PhotoFolderGroup[]) => void;
}

const EMPTY_DEFAULTS: BulkUploadDefaults = { cog: "", labels: "" };

type DragSpot = { group: number; photo: number };

export function BulkUploadDialog({ groups: initialGroups, onCancel, onConfirm }: Props) {
  const [defaults, setDefaults] = useState<BulkUploadDefaults>(EMPTY_DEFAULTS);
  const boxes = useQuery({ queryKey: BOXES_QUERY_KEY, queryFn: api.boxes.list }).data?.boxes ?? [];
  const box = boxes.find((row) => row.id === defaults.boxId);
  const [groups, setGroups] = useState(initialGroups);
  const [dragFrom, setDragFrom] = useState<DragSpot | null>(null);
  const [dropOn, setDropOn] = useState<DragSpot | null>(null);
  // One preview URL per picked file; reordering only shuffles which file sits where.
  const [previewUrls, setPreviewUrls] = useState<Map<File, string>>(() => new Map());
  const cogRef = useRef<HTMLInputElement>(null);
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
          if (!invalidCog) onConfirm(defaults, groups);
        }}
      >
        <div className="confirm-dialog-header">
          <h2 id="bulk-upload-title" className="confirm-dialog-title">
            Set details for {count} listings
          </h2>
          <p className="confirm-dialog-description">
            These optional values will be added to every draft in this bulk upload.
            Drag photos to set their order; the first one is the cover.
          </p>
        </div>
        <ul className="bulk-upload-groups" aria-label="Photos for each listing">
          {groups.map((group, groupIndex) => (
            <li key={group.folder ?? groupIndex} className="bulk-upload-group">
              <span className="bulk-upload-group-title">
                {listingTitleForFolder(group.folder)}
                <span className="photo-tray-meta"> · {group.files.length} photos</span>
              </span>
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
                      title={canReorder ? `${file.name} · drag to reorder` : file.name}
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
            </li>
          ))}
        </ul>
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
