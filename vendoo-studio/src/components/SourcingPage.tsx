import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SourcingCart, SourcingLot, SourcingPrefs, SourcingSnapshot, SourcingState } from "../api/types";
import { addToast } from "../ui/toast";
import { formatMoney } from "./analyticsFormat";
import { formatRoi, freeShippingGap, isZip, lotCount, lotMeta, otherLots, whenChecked } from "./boxScout";

const QUERY_KEY = ["sourcing"];

export function SourcingPage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: api.sourcing.get,
    // While Studio is checking the stores, watch for the new list.
    refetchInterval: (current) => (current.state.data?.refreshing ? 3000 : false),
  });
  const onSaved = (state: SourcingState) => queryClient.setQueryData(QUERY_KEY, state);
  const onError = (error: Error) =>
    addToast({ type: "error", title: "Could not update sourcing", description: error.message });
  const refresh = useMutation({ mutationFn: api.sourcing.refresh, onSuccess: onSaved, onError });
  const savePrefs = useMutation({
    mutationFn: (prefs: Partial<SourcingPrefs>) => api.sourcing.savePrefs(prefs),
    onSuccess: onSaved,
    onError,
  });
  const data = query.data;
  const snapshot = data?.snapshot ?? null;

  return (
    <div className="analytics-page">
      <div className="analytics-inner">
        <header className="analytics-header">
          <p className="analytics-lead">
            Studio checks Raghouse and Thrift Vintage Fashion every 6 hours and picks the boxes worth buying,
            with shipping to the ZIP below. Open a cart, check it, and pay.
          </p>
          {data ? (
            <div className="sourcing-toolbar">
              <ZipField
                zip={data.prefs.zip}
                recent={data.prefs.recent_zips}
                disabled={savePrefs.isPending}
                onSave={(zip) => savePrefs.mutate({ zip })}
              />
              <BudgetField
                budget={data.prefs.budget}
                disabled={savePrefs.isPending}
                onSave={(budget) => savePrefs.mutate({ budget })}
              />
              <label className="sourcing-check">
                <input
                  type="checkbox"
                  checked={data.prefs.raghouse_vip}
                  disabled={savePrefs.isPending}
                  onChange={(event) => savePrefs.mutate({ raghouse_vip: event.target.checked })}
                />
                I have Raghouse VIP
              </label>
              <span className="sourcing-status">
                {data.refreshing
                  ? "Checking the stores…"
                  : snapshot
                    ? `Checked ${whenChecked(snapshot.updated_at)}`
                    : null}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => refresh.mutate()}
                disabled={data.refreshing || refresh.isPending}
              >
                Check now
              </button>
            </div>
          ) : null}
        </header>

        {query.isLoading ? <p className="analytics-status">Loading…</p> : null}
        {query.isError ? (
          <p className="analytics-status">{(query.error as Error).message || "Could not load sourcing."}</p>
        ) : null}
        {data && !snapshot ? (
          <p className="analytics-status">
            Studio is reading both stores and pricing what they have. The first check takes a few minutes.
          </p>
        ) : null}

        {data && snapshot ? (
          <>
            <StoreErrors snapshot={snapshot} />
            <BuyList data={data} snapshot={snapshot} />
            <Trending trend={data.trend} />
            <section className="analytics-section" aria-label="Other boxes">
              <h2 className="analytics-section-title">Next best boxes</h2>
              <ol className="sourcing-boxes">
                {otherLots(snapshot).map((lot) => (
                  <LotRow key={lot.variant_id} lot={lot} showStore />
                ))}
              </ol>
            </section>
            <p className="analytics-note sourcing-footnote">{assumptions(snapshot)}</p>
          </>
        ) : null}
      </div>
    </div>
  );
}

function BuyList({ data, snapshot }: { data: SourcingState; snapshot: SourcingSnapshot }) {
  const plan = snapshot.buy_list;
  // Prices found earlier stay good for two weeks, so a list can stand without a model connected.
  if (plan.carts.length === 0 && !data.research_available) {
    return (
      <section className="analytics-section" aria-label="Buy list">
        <h2 className="analytics-section-title">Buy these</h2>
        <p className="analytics-note">
          Connect ChatGPT, Cursor or MiMo in Settings → Providers so Studio can look up what these boxes resell
          for. Until then it can rank boxes but cannot tell which ones pay for themselves.
        </p>
      </section>
    );
  }
  return (
    <section className="analytics-section" aria-label="Buy list">
      <h2 className="analytics-section-title">Buy these</h2>
      {plan.carts.length === 0 ? (
        <p className="analytics-note">
          Nothing is expected to at least double your money within {formatMoney(plan.budget)} right now.{" "}
          {snapshot.priced_themes === 0 ? "Studio has not priced any boxes yet." : "Studio will check again soon."}
        </p>
      ) : (
        <>
          <div className="analytics-stats">
            <Stat label="Spend" value={formatMoney(Math.round(plan.total))} hint={`of ${formatMoney(plan.budget)}`} />
            <Stat label="Expected profit" value={formatMoney(Math.round(plan.expected_profit))} />
            <Stat label="Boxes" value={String(plan.carts.reduce((sum, cart) => sum + cart.lots.length, 0))} />
          </div>
          {plan.carts.map((cart) => (
            <Cart key={cart.store} cart={cart} />
          ))}
        </>
      )}
    </section>
  );
}

function Cart({ cart }: { cart: SourcingCart }) {
  const gap = freeShippingGap(cart);
  const shipping = cart.free_shipping ? "free shipping" : `about ${formatMoney(Math.round(cart.shipping))} shipping`;
  return (
    <div className="sourcing-cart">
      <div className="sourcing-cart-header">
        <div>
          <div className="sourcing-cart-name">{cart.name}</div>
          <div className="sourcing-box-meta">
            {lotCount(cart.lots.length)} · {formatMoney(cart.subtotal)} + {shipping}
            {gap ? ` · ${formatMoney(gap)} more ships free` : ""}
          </div>
        </div>
        <a className="btn btn-sm" href={cart.cart_url} target="_blank" rel="noopener noreferrer">
          Open cart
        </a>
      </div>
      <ol className="sourcing-boxes">
        {cart.lots.map((lot) => (
          <LotRow key={lot.variant_id} lot={lot} />
        ))}
      </ol>
    </div>
  );
}

function LotRow({ lot, showStore = false }: { lot: SourcingLot; showStore?: boolean }) {
  const resale =
    lot.resale_per_pc != null
      ? `resells ~${formatMoney(lot.resale_per_pc)}/pc`
      : lot.seller_resale != null
        ? `store says ~${formatMoney(lot.seller_resale)}/pc`
        : null;
  const meta = [showStore ? storeName(lot.store) : null, lotMeta(lot), resale].filter(Boolean).join(" · ");
  return (
    <li>
      <a className="sourcing-box" href={lot.url} target="_blank" rel="noopener noreferrer">
        <span className="sourcing-box-main">
          <span className="sourcing-box-title">{lot.title}</span>
          <span className="sourcing-box-meta">
            {meta}
            {lot.trend_hits.length ? <span className="sourcing-box-trend"> · {lot.trend_hits.join(", ")}</span> : null}
          </span>
        </span>
        <span className="sourcing-box-cost">
          <span className="sourcing-box-value">{formatMoney(Math.round(lot.landed))} landed</span>
          <span className="sourcing-box-meta">
            {formatMoney(lot.price)} + {formatMoney(Math.round(lot.ship_est))} ship
          </span>
        </span>
        <span className="sourcing-box-profit">
          {lot.expected_profit != null && lot.roi != null ? (
            <>
              <span className={lot.expected_profit >= 0 ? "is-positive" : "is-negative"}>
                {lot.expected_profit >= 0 ? "+" : "−"}
                {formatMoney(Math.abs(Math.round(lot.expected_profit)))}
              </span>
              <span className="sourcing-box-meta">{formatRoi(lot.roi)}</span>
            </>
          ) : (
            <span className="sourcing-box-meta">{formatMoney(lot.cog_per_usable_pc)}/pc</span>
          )}
        </span>
      </a>
    </li>
  );
}

function Trending({ trend }: { trend: SourcingState["trend"] }) {
  if (trend.terms.length === 0) return null;
  const when = trend.updated_at ? whenChecked(trend.updated_at) : "";
  return (
    <section className="analytics-section" aria-label="Trending">
      <h2 className="analytics-section-title">
        Selling now{when ? ` · ${trend.source ? `${trend.source}, ` : ""}${when}` : ""}
      </h2>
      <div className="sourcing-terms">
        {trend.terms.map((term) => (
          <span key={term} className="sourcing-term">
            {term}
          </span>
        ))}
      </div>
    </section>
  );
}

function StoreErrors({ snapshot }: { snapshot: SourcingSnapshot }) {
  const errors = Object.values(snapshot.stores).filter((store) => store.error);
  if (errors.length === 0) return null;
  return (
    <div className="sourcing-errors">
      {errors.map((store) => (
        <p key={store.name} className="analytics-note">
          {store.error} Its boxes are missing from this check.
        </p>
      ))}
    </div>
  );
}

function ZipField({
  zip,
  recent,
  disabled,
  onSave,
}: {
  zip: string;
  recent: string[];
  disabled: boolean;
  onSave: (zip: string) => void;
}) {
  const [draft, setDraft] = useState(zip);
  const [saved, setSaved] = useState(zip);
  if (saved !== zip) {
    setSaved(zip);
    setDraft(zip);
  }
  const commit = () => {
    const next = draft.trim();
    if (isZip(next) && next !== zip) onSave(next);
    else setDraft(zip);
  };
  const others = recent.filter((item) => item !== zip);
  return (
    <div className="sourcing-zip">
      <label className="sourcing-budget">
        <span className="label">Ship to</span>
        <input
          className="input input-sm"
          type="text"
          inputMode="numeric"
          autoComplete="postal-code"
          maxLength={5}
          placeholder="ZIP"
          aria-label="Ship to ZIP code"
          value={draft}
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value.replace(/\D/g, ""))}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit();
          }}
        />
      </label>
      {others.map((item) => (
        <button
          key={item}
          type="button"
          className="sourcing-zip-recent"
          disabled={disabled}
          title={`Ship to ${item}`}
          onClick={() => onSave(item)}
        >
          {item}
        </button>
      ))}
    </div>
  );
}

function BudgetField({ budget, disabled, onSave }: { budget: number; disabled: boolean; onSave: (v: number) => void }) {
  const [draft, setDraft] = useState(String(budget));
  const [saved, setSaved] = useState(budget);
  if (saved !== budget) {
    setSaved(budget);
    setDraft(String(budget));
  }
  const commit = () => {
    const value = Number(draft);
    if (Number.isFinite(value) && value > 0 && value !== budget) onSave(value);
    else setDraft(String(budget));
  };
  return (
    <label className="sourcing-budget">
      <span className="label">Budget</span>
      <input
        className="input input-sm"
        type="number"
        inputMode="decimal"
        min={1}
        step={25}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
        }}
      />
    </label>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="analytics-stat">
      <div className="analytics-stat-label">{label}</div>
      <div className="analytics-stat-value">{value}</div>
      {hint ? <div className="analytics-stat-hint">{hint}</div> : null}
    </div>
  );
}

function zones(snapshot: SourcingSnapshot): string {
  return Object.values(snapshot.stores)
    .filter((store) => store.zone != null)
    .map((store) => `zone ${store.zone} from ${store.name}`)
    .join(", ");
}

function storeName(store: string): string {
  return store === "tvf" ? "Thrift Vintage Fashion" : "Raghouse";
}

function assumptions(snapshot: SourcingSnapshot): string {
  const a = snapshot.assumptions;
  const s = snapshot.shipping;
  return (
    `Profit assumes ${Math.round(a.sell_through * 100)}% of the usable pieces sell at an average-demand ` +
    `price, more for boxes that sell out fast, less for slow ones, and ${Math.round(a.fees * 100)}% ` +
    `marketplace fees. Usable pieces: 90% of a plain box, 75% of Recycle & Good, 60% of Recycle or B grade. ` +
    `Resale prices come from sold listings your connected model found, rechecked every two weeks. Shipping is ` +
    `the UPS Ground list price to ${snapshot.destination_zip} (${zones(snapshot)}) plus ${formatMoney(s.residential_surcharge)} home ` +
    `delivery and ${s.fuel_surcharge_pct}% fuel (as of ${s.fuel_surcharge_as_of}); stores quote discounted ` +
    `rates, so expect to pay less. Studio never buys anything: the cart links only fill the cart.`
  );
}
