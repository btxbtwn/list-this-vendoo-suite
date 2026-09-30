import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api/client";
import type { PriceDropPreview } from "../api/types";
import {
  BULK_DROP_PERCENTS,
  bulkPriceDrops,
  bulkRegenerateWarning,
  type BulkPriceChoice,
  type BulkPriceDrop,
  type BulkPriceSuggestion,
  type BulkRegenerateListing,
} from "../bulkRegenerate";

function money(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2)}`;
}

function suggestionFromPreview(preview: PriceDropPreview): BulkPriceSuggestion {
  const mode =
    preview.suggested_mode === "comps"
      ? "comps"
      : preview.suggested_mode === "percent" || preview.suggested_mode === "sell_through"
        ? "percent"
        : "custom";
  return {
    price: preview.suggested_price,
    percent: preview.suggested_effective_percent,
    mode,
  };
}

/**
 * Confirm a bulk rewrite, with the option to mark down every priced listing
 * first. Keep prices is the default, so a rewrite that only refreshes the
 * copy does not change what each listing asks.
 */
export function BulkRegeneratePriceDialog({
  listings,
  onClose,
  onConfirm,
}: {
  listings: BulkRegenerateListing[];
  onClose: () => void;
  onConfirm: (drops: Map<string, BulkPriceDrop>) => void;
}) {
  const [choice, setChoice] = useState<BulkPriceChoice>({ kind: "keep" });
  const [suggestions, setSuggestions] = useState<Map<string, BulkPriceSuggestion | null>>(new Map());
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const pricedIds = useMemo(
    () => listings.filter((listing) => listing.price != null && listing.price > 0).map((listing) => listing.id),
    [listings],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [onClose]);

  useEffect(() => {
    if (choice.kind !== "suggested" || pricedIds.length === 0) return;
    let cancelled = false;
    void Promise.all(
      pricedIds.map(async (id) => {
        try {
          const preview = await api.listings.priceDropPreview(id);
          return [id, suggestionFromPreview(preview)] as const;
        } catch {
          return [id, null] as const;
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      const next = new Map<string, BulkPriceSuggestion | null>();
      let failed = 0;
      for (const [id, suggestion] of results) {
        next.set(id, suggestion);
        if (!suggestion) failed += 1;
      }
      setSuggestions(next);
      setLoadError(
        failed
          ? `${failed} ${failed === 1 ? "listing" : "listings"} could not load a suggestion and will keep ${failed === 1 ? "its" : "their"} price.`
          : "",
      );
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [choice.kind, pricedIds]);

  const drops = useMemo(
    () => bulkPriceDrops(listings, choice, suggestions),
    [choice, listings, suggestions],
  );
  const warning = bulkRegenerateWarning(listings.length);
  const [title, description] = warning.split("\n");
  const dropping = drops.size > 0;

  return createPortal(
    <div className="confirm-dialog price-drop-dialog" role="presentation">
      <button type="button" className="confirm-dialog-backdrop" aria-label="Cancel" onClick={onClose} />
      <div
        className="confirm-dialog-popup price-drop-popup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="bulk-price-drop-title"
      >
        <div className="confirm-dialog-header">
          <h2 id="bulk-price-drop-title" className="confirm-dialog-title">{title}</h2>
          <p className="confirm-dialog-description">
            {description}
            {" "}
            Choose a markdown to drop every priced listing before the rewrite, or keep prices.
          </p>
        </div>

        <div className="price-drop-body">
          <div className="price-drop-section">
            <div className="price-drop-section-title">Price</div>
            <div className="price-drop-chips" role="group" aria-label="Price drop">
              <button
                type="button"
                className={`price-drop-chip${choice.kind === "keep" ? " is-active" : ""}`}
                onClick={() => setChoice({ kind: "keep" })}
              >
                Keep prices
              </button>
              {BULK_DROP_PERCENTS.map((percent) => (
                <button
                  key={percent}
                  type="button"
                  className={`price-drop-chip${choice.kind === "percent" && choice.percent === percent ? " is-active" : ""}`}
                  onClick={() => setChoice({ kind: "percent", percent })}
                >
                  −{percent}% each
                </button>
              ))}
              <button
                type="button"
                className={`price-drop-chip price-drop-chip-wide${choice.kind === "suggested" ? " is-active" : ""}`}
                onClick={() => {
                  if (choice.kind === "suggested") return;
                  setChoice({ kind: "suggested" });
                  setLoadError("");
                  setLoading(pricedIds.length > 0);
                }}
              >
                Each listing's suggestion
                <span className="price-drop-chip-note">
                  The same suggestion Regenerate offers on one listing, from its own sales and prior drops.
                </span>
              </button>
            </div>
          </div>

          {choice.kind === "suggested" && loadError ? (
            <p className="price-drop-status is-error">{loadError}</p>
          ) : null}
          {choice.kind === "suggested" && loading ? (
            <p className="price-drop-status">Loading a suggestion for each priced listing…</p>
          ) : null}

          <ul className="price-drop-rows">
            {listings.map((listing) => (
              <li key={listing.id} className="price-drop-row">
                <span className="price-drop-row-title">{listing.title}</span>
                <span className="price-drop-row-price">{rowPrice(listing, choice, drops, loading)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="confirm-dialog-footer">
          <button type="button" className="btn btn-outline" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={choice.kind === "suggested" && loading}
            onClick={() => onConfirm(drops)}
          >
            {dropping ? "Drop and rewrite" : "Rewrite"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function rowPrice(
  listing: BulkRegenerateListing,
  choice: BulkPriceChoice,
  drops: Map<string, BulkPriceDrop>,
  loading: boolean,
): string {
  const current = listing.price;
  if (current == null || !(current > 0)) return "No price";
  if (choice.kind === "suggested" && loading) return `${money(current)} → …`;
  const drop = drops.get(listing.id);
  if (!drop) return `${money(current)} · kept`;
  return `${money(current)} → ${money(drop.price)}`;
}
