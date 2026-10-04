import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Photo } from "../api/types";
import {
  GARMENTS,
  garmentFields,
  guessGarment,
  notesWithMeasurements,
  typedMeasurements,
  type Garment,
} from "./garmentMeasurements";

export interface BulkMeasureListing {
  convId: string;
  title: string;
}

interface RowState {
  sku: string;
  garment: Garment;
  values: Record<string, string>;
}

interface Props {
  listings: BulkMeasureListing[];
  onClose: () => void;
  /** Start generating these drafts, filled in or not. */
  onGenerate: (listings: BulkMeasureListing[]) => void;
}

/**
 * SKUs and measurements for a whole bulk upload in one grid, before anything
 * generates. Each row shows its photos, so the one with the tape in it is a
 * click away, and what is typed lands in Item Details, where generation takes
 * it as fact and keeps the SKU exactly as typed.
 */
export function BulkMeasurementsDialog({ listings, onClose, onGenerate }: Props) {
  const [rows, setRows] = useState<Record<string, RowState>>(() => Object.fromEntries(
    listings.map((listing) => [listing.convId, { sku: "", garment: guessGarment(listing.title), values: {} }]),
  ));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState<{ photos: Photo[]; index: number } | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef(zoom);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    zoomRef.current = zoom;
    onCloseRef.current = onClose;
  }, [zoom, onClose]);

  useEffect(() => {
    const focusTimer = window.setTimeout(() => {
      gridRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    }, 0);
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (zoomRef.current) setZoom(null);
      else onCloseRef.current();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const isMeasured = (row: RowState) => Object.keys(typedMeasurements(row.garment, row.values)).length > 0;
  const filledCount = listings.filter((listing) => {
    const row = rows[listing.convId];
    return row && (row.sku.trim() || isMeasured(row));
  }).length;
  const count = listings.length;
  const noun = count === 1 ? "listing" : "listings";

  const setSku = (convId: string, sku: string) => setRows((current) => ({
    ...current,
    [convId]: { ...current[convId]!, sku },
  }));
  const setGarment = (convId: string, garment: Garment) => setRows((current) => ({
    ...current,
    [convId]: { ...current[convId]!, garment },
  }));
  const setValue = (convId: string, key: string, value: string) => setRows((current) => ({
    ...current,
    [convId]: { ...current[convId]!, values: { ...current[convId]!.values, [key]: value } },
  }));

  const saveAndGenerate = async () => {
    setSaving(true);
    setError(null);
    try {
      for (const listing of listings) {
        const row = rows[listing.convId];
        if (!row) continue;
        const sku = row.sku.trim();
        // Notes merge on the server, so the SKU goes on its own.
        if (sku) await api.conversations.update(listing.convId, { notes: JSON.stringify({ sku }) });
        if (!isMeasured(row)) continue;
        const conv = await api.conversations.get(listing.convId);
        await api.conversations.update(listing.convId, {
          notes: notesWithMeasurements(conv.notes, row.garment, row.values),
        });
      }
    } catch (err) {
      setSaving(false);
      setError(err instanceof Error ? err.message : "Could not save SKUs and measurements");
      return;
    }
    onGenerate(listings);
  };

  // Enter moves on like a spreadsheet instead of submitting half a box.
  const onInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const inputs = Array.from(gridRef.current?.querySelectorAll<HTMLInputElement>("input") || []);
    const next = inputs[inputs.indexOf(event.currentTarget) + 1];
    next?.focus();
  };

  return createPortal(
    <div className="confirm-dialog bulk-measure-dialog" role="presentation">
      <button
        type="button"
        className="confirm-dialog-backdrop"
        aria-label="Close without generating"
        onClick={onClose}
      />
      <form
        className="confirm-dialog-popup bulk-measure-popup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bulk-measure-title"
        onSubmit={(event) => {
          event.preventDefault();
          if (!saving) void saveAndGenerate();
        }}
      >
        <div className="confirm-dialog-header">
          <h2 id="bulk-measure-title" className="confirm-dialog-title">
            SKU and measurements for {count} {noun}
          </h2>
          <p className="confirm-dialog-description">
            Type a SKU and measurements in inches, or leave them blank. A SKU typed here is kept as
            is; a blank one is made up from the brand and size. Tab or Enter moves to the next box.
            Studio then generates each draft from its photos, one at a time, and stops at a draft.
          </p>
        </div>
        <div className="bulk-measure-grid" ref={gridRef}>
          {listings.map((listing) => {
            const row = rows[listing.convId]!;
            return (
              <div className="bulk-measure-row" key={listing.convId}>
                <PhotoCarousel convId={listing.convId} onZoom={(photos, index) => setZoom({ photos, index })} />
                <div className="bulk-measure-body">
                  <div className="bulk-measure-head">
                    <span className="bulk-measure-title" title={listing.title}>{listing.title}</span>
                    <label className="bulk-measure-sku">
                      <span className="label">SKU</span>
                      <input
                        className="input"
                        type="text"
                        autoComplete="off"
                        spellCheck={false}
                        aria-label={`SKU for ${listing.title}`}
                        value={row.sku}
                        onChange={(event) => setSku(listing.convId, event.target.value)}
                        onKeyDown={onInputKeyDown}
                      />
                    </label>
                    <div className="pr-pills item-garment-pills" role="radiogroup" aria-label={`Garment type for ${listing.title}`}>
                      {GARMENTS.map((g) => (
                        <button
                          key={g.id}
                          type="button"
                          role="radio"
                          tabIndex={-1}
                          aria-checked={g.id === row.garment}
                          className={`pr-pill${g.id === row.garment ? " is-active" : ""}`}
                          onClick={() => setGarment(listing.convId, g.id)}
                        >
                          {g.label}
                        </button>
                      ))}
                    </div>
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
                          value={row.values[field.key] || ""}
                          onChange={(event) => setValue(listing.convId, field.key, event.target.value)}
                          onKeyDown={onInputKeyDown}
                        />
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {error ? <p className="bulk-measure-error" role="alert">{error}</p> : null}
        <div className="confirm-dialog-footer">
          <button type="button" className="btn btn-ghost" disabled={saving} onClick={onClose}>
            Not now
          </button>
          <span className="bulk-measure-spacer" />
          <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => onGenerate(listings)}>
            Continue without them
          </button>
          <button type="submit" className="btn btn-primary" disabled={saving || filledCount === 0}>
            {saving ? "Saving…" : `Save and generate ${count}`}
          </button>
        </div>
      </form>
      {zoom ? <PhotoZoom zoom={zoom} onStep={(index) => setZoom({ ...zoom, index })} onClose={() => setZoom(null)} /> : null}
    </div>,
    document.body,
  );
}

function PhotoCarousel({ convId, onZoom }: { convId: string; onZoom: (photos: Photo[], index: number) => void }) {
  const { data: photos } = useQuery({
    queryKey: ["photos", convId],
    queryFn: () => api.conversations.photos(convId),
  });
  const [index, setIndex] = useState(0);
  const list = photos || [];
  const current = list[Math.min(index, list.length - 1)];
  const step = (delta: number) => setIndex((value) => (value + delta + list.length) % list.length);

  return (
    <div className="bulk-measure-carousel">
      {current ? (
        <button
          type="button"
          tabIndex={-1}
          className="bulk-measure-photo"
          aria-label="Enlarge photo"
          onClick={() => onZoom(list, list.indexOf(current))}
        >
          <img src={current.url} alt="" draggable={false} />
        </button>
      ) : (
        <div className="bulk-measure-photo bulk-measure-photo-empty" aria-hidden="true" />
      )}
      {list.length > 1 ? (
        <div className="bulk-measure-carousel-nav">
          <button type="button" tabIndex={-1} aria-label="Previous photo" onClick={() => step(-1)}>‹</button>
          <span>{list.indexOf(current!) + 1} / {list.length}</span>
          <button type="button" tabIndex={-1} aria-label="Next photo" onClick={() => step(1)}>›</button>
        </div>
      ) : null}
    </div>
  );
}

function PhotoZoom({
  zoom,
  onStep,
  onClose,
}: {
  zoom: { photos: Photo[]; index: number };
  onStep: (index: number) => void;
  onClose: () => void;
}) {
  const { photos, index } = zoom;
  const photo = photos[index]!;
  const step = (delta: number) => onStep((index + delta + photos.length) % photos.length);
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
      aria-label={`Photo ${index + 1} of ${photos.length}`}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") step(-1);
        if (event.key === "ArrowRight") step(1);
      }}
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}
    >
      <button type="button" className="photo-lightbox-close" onClick={onClose} aria-label="Close">
        x
      </button>
      {photos.length > 1 && (
        <button type="button" className="photo-lightbox-nav photo-lightbox-prev" onClick={() => step(-1)} aria-label="Previous photo">
          ‹
        </button>
      )}
      <img className="photo-lightbox-image" src={photo.url} alt={`Photo ${index + 1}`} onClick={onClose} />
      {photos.length > 1 && (
        <button type="button" className="photo-lightbox-nav photo-lightbox-next" onClick={() => step(1)} aria-label="Next photo">
          ›
        </button>
      )}
      <div className="photo-lightbox-meta">{String(index + 1).padStart(2, "0")} / {String(photos.length).padStart(2, "0")}</div>
    </div>
  );
}
