import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PriceDropPreview } from "../api/types";
import { addToast } from "../ui/toast";
import { SoldCompsCard } from "./SoldCompsCard";

function money(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2)}`;
}

function formatDropWhen(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const days = Math.max(0, Math.round((Date.now() - date.getTime()) / 86_400_000));
  if (days <= 0) return "today";
  if (days === 1) return "1d ago";
  if (days < 30) return `${days}d ago`;
  return date.toLocaleDateString();
}

type Selection =
  | { kind: "percent"; percent: number; price: number }
  | { kind: "comps"; price: number }
  | { kind: "custom"; price: number };

function defaultSelection(preview: PriceDropPreview): Selection {
  if (preview.suggested_mode === "comps" && preview.comps.target_price != null) {
    return { kind: "comps", price: preview.comps.target_price };
  }
  return {
    kind: "percent",
    percent: preview.suggested_percent,
    price: preview.prices_by_percent[String(preview.suggested_percent)] ?? preview.suggested_price,
  };
}

/** Price-drop chooser shown when Regenerate is clicked on a priced listing. */
export function RegeneratePriceDialog({
  convId,
  open,
  onClose,
  onFullRegenerate,
  onDropped,
}: {
  convId: string;
  open: boolean;
  onClose: () => void;
  onFullRegenerate: () => void;
  onDropped?: () => void;
}) {
  const queryClient = useQueryClient();

  const previewQuery = useQuery({
    queryKey: ["price-drop-preview", convId],
    queryFn: () => api.listings.priceDropPreview(convId),
    enabled: open,
    staleTime: 30_000,
  });

  const [selection, setSelection] = useState<Selection | null>(null);
  const [customText, setCustomText] = useState("");

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) {
      setSelection(null);
      setCustomText("");
      return;
    }
    if (!previewQuery.data) return;
    const next = defaultSelection(previewQuery.data);
    setSelection(next);
    setCustomText(String(next.price));
  }, [open, previewQuery.data]);

  const selectedPrice = useMemo(() => {
    if (!selection) return null;
    if (selection.kind === "custom") {
      const parsed = Number(customText);
      return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : null;
    }
    return selection.price;
  }, [selection, customText]);

  const apply = useMutation({
    mutationFn: async () => {
      if (selectedPrice == null || !previewQuery.data) {
        throw new Error("Choose a lower price first.");
      }
      if (selectedPrice >= previewQuery.data.current_price) {
        throw new Error("New price must be lower than the current price.");
      }
      const percent =
        selection?.kind === "percent"
          ? selection.percent
          : Math.round((1 - selectedPrice / previewQuery.data.current_price) * 1000) / 10;
      const mode = selection?.kind === "comps" ? "comps" : selection?.kind === "percent" ? "percent" : "custom";
      return api.listings.applyPriceDrop(convId, { price: selectedPrice, percent, mode });
    },
    onSuccess: (result) => {
      onClose();
      void queryClient.invalidateQueries({ queryKey: ["listing", convId] });
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["price-drop-preview", convId] });
      onDropped?.();
      addToast({
        type: "success",
        title: "Price dropped",
        description: `${money(result.previous_price)} → ${money(result.price)}. Send to Vendoo when you want the live draft updated.`,
      });
    },
    onError: (err: Error) => {
      addToast({
        type: "error",
        title: "Could not drop price",
        description: err.message || "The price could not be updated.",
      });
    },
  });

  if (!open) return null;

  const preview = previewQuery.data;
  const belowComps =
    preview?.comps.target_price != null &&
    selectedPrice != null &&
    selectedPrice < preview.comps.target_price;

  return (
    <div className="confirm-dialog price-drop-dialog" role="presentation">
      <button
        type="button"
        className="confirm-dialog-backdrop"
        aria-label="Cancel"
        onClick={onClose}
      />
      <div
        className="confirm-dialog-popup price-drop-popup"
        role="dialog"
        aria-modal="true"
        aria-labelledby="price-drop-title"
      >
        <div className="confirm-dialog-header">
          <h2 id="price-drop-title" className="confirm-dialog-title">
            Regenerate
          </h2>
          <p className="confirm-dialog-description">
            Choose a percent cut or the live comps target. Title and description stay; only the price
            changes. Or wipe the listing and generate from scratch. Nothing changes on Vendoo until you
            Send.
          </p>
        </div>

        <div className="price-drop-body">
          {previewQuery.isLoading ? (
            <p className="price-drop-status">Researching sold comps…</p>
          ) : previewQuery.isError ? (
            <p className="price-drop-status is-error">
              {(previewQuery.error as Error).message || "Could not load a price suggestion."}
            </p>
          ) : preview ? (
            <>
              <div className="price-drop-summary">
                <div>
                  <span className="price-drop-label">Current</span>
                  <strong>{money(preview.current_price)}</strong>
                </div>
                <div>
                  <span className="price-drop-label">First listed</span>
                  <strong>{money(preview.first_price)}</strong>
                </div>
                <div>
                  <span className="price-drop-label">Selected</span>
                  <strong>{money(selectedPrice)}</strong>
                </div>
              </div>

              <p className="price-drop-reason">{preview.suggested_reason}</p>

              <div className="price-drop-section">
                <div className="price-drop-section-title">Percent</div>
                <div className="price-drop-chips" role="group" aria-label="Price drop percent">
                  {preview.percent_options.map((percent) => {
                    const price = preview.prices_by_percent[String(percent)];
                    const active = selection?.kind === "percent" && selection.percent === percent;
                    return (
                      <button
                        key={percent}
                        type="button"
                        className={`price-drop-chip${active ? " is-active" : ""}`}
                        onClick={() => {
                          setSelection({ kind: "percent", percent, price });
                          setCustomText(String(price));
                        }}
                      >
                        {percent}% · {money(price)}
                      </button>
                    );
                  })}
                  {preview.suggested_percent === 5 && !preview.percent_options.includes(5) ? (
                    <button
                      type="button"
                      className={`price-drop-chip${selection?.kind === "percent" && selection.percent === 5 ? " is-active" : ""}`}
                      onClick={() => {
                        const price = preview.prices_by_percent["5"] ?? Math.round(preview.current_price * 0.95);
                        setSelection({ kind: "percent", percent: 5, price });
                        setCustomText(String(price));
                      }}
                    >
                      5% · {money(preview.prices_by_percent["5"])}
                    </button>
                  ) : null}
                </div>
              </div>

              {preview.comps.target_price != null && preview.comps.target_price < preview.current_price ? (
                <div className="price-drop-section">
                  <div className="price-drop-section-title">Live comps</div>
                  <button
                    type="button"
                    className={`price-drop-chip price-drop-chip-wide${selection?.kind === "comps" ? " is-active" : ""}`}
                    onClick={() => {
                      const price = preview.comps.target_price!;
                      setSelection({ kind: "comps", price });
                      setCustomText(String(price));
                    }}
                  >
                    Comps target {money(preview.comps.target_price)}
                    {preview.comps.market ? ` · market ${preview.comps.market}` : ""}
                  </button>
                </div>
              ) : !preview.comps.available ? (
                <p className="price-drop-status">
                  Sold comps need ChatGPT signed in or a Brave Search API key in Settings.
                </p>
              ) : null}

              <div className="price-drop-section">
                <label className="price-drop-section-title" htmlFor="price-drop-custom">
                  Custom price
                </label>
                <input
                  id="price-drop-custom"
                  className="price-drop-custom"
                  type="number"
                  min={1}
                  step={1}
                  value={customText}
                  onChange={(event) => {
                    setCustomText(event.target.value);
                    setSelection({ kind: "custom", price: Number(event.target.value) || 0 });
                  }}
                />
                {belowComps ? (
                  <p className="price-drop-status">
                    Below the comps formula floor ({money(preview.comps.target_price)}). You can still apply it.
                  </p>
                ) : null}
              </div>

              {preview.history.length ? (
                <div className="price-drop-section">
                  <div className="price-drop-section-title">Prior drops</div>
                  <ul className="price-drop-history">
                    {preview.history.map((event) => (
                      <li key={event.revision_id}>
                        {money(event.from_price)} → {money(event.to_price)} (−{event.percent}%)
                        {event.created_at ? ` · ${formatDropWhen(event.created_at)}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {preview.comps.text ? <SoldCompsCard text={preview.comps.text} /> : null}
            </>
          ) : null}
        </div>

        <div className="confirm-dialog-footer price-drop-footer">
          <button
            type="button"
            className="btn btn-outline"
            disabled={apply.isPending}
            onClick={() => {
              onClose();
              onFullRegenerate();
            }}
          >
            Full regenerate
          </button>
          <div className="price-drop-footer-end">
            <button type="button" className="btn btn-outline" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={
                apply.isPending ||
                previewQuery.isLoading ||
                selectedPrice == null ||
                !preview ||
                selectedPrice >= preview.current_price
              }
              onClick={() => apply.mutate()}
            >
              {apply.isPending ? "Saving…" : `Drop to ${money(selectedPrice)}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
