import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SourcingCart, SourcingLot, SourcingPrefs, SourcingSnapshot, SourcingState } from "../api/types";
import { addToast } from "../ui/toast";
import { formatMoney } from "./analyticsFormat";
import {
  REFRESH_HOURS,
  boxCount,
  cartTotal,
  clockTime,
  freeShippingGap,
  isZip,
  lotReason,
  moneyBack,
  nextUpdate,
  otherLots,
} from "./boxScout";

const QUERY_KEY = ["sourcing"];

interface Props {
  onOpenProviders: () => void;
}

export function SourcingPage({ onOpenProviders }: Props) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: api.sourcing.get,
    // While Studio is checking the stores, watch for the new list.
    refetchInterval: (current) => (current.state.data?.refreshing ? 3000 : false),
  });
  const onSaved = (state: SourcingState) => queryClient.setQueryData(QUERY_KEY, state);
  const onError = (error: Error) =>
    addToast({ type: "error", title: "Could not update your buy list", description: error.message });
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
      <div className="analytics-inner sourcing-inner">
        <header className="sourcing-header">
          <div className="sourcing-title-row">
            <h1 className="sourcing-title">Your buy list</h1>
            {data ? (
              <UpdateStatus
                snapshot={snapshot}
                refreshing={data.refreshing || refresh.isPending}
                onRefresh={() => refresh.mutate()}
              />
            ) : null}
          </div>
          <p className="sourcing-lead">
            Studio watches Raghouse and Thrift Vintage Fashion for you and picks the boxes worth buying. Open a
            cart, check it, and pay. Nothing is bought without you.
          </p>
          {data ? (
            <Settings prefs={data.prefs} saving={savePrefs.isPending} onSave={(prefs) => savePrefs.mutate(prefs)} />
          ) : null}
        </header>

        {query.isLoading ? <p className="analytics-status">Loading…</p> : null}
        {query.isError ? (
          <p className="analytics-status">{(query.error as Error).message || "Could not load your buy list."}</p>
        ) : null}

        {data && !snapshot ? (
          <div className="sourcing-empty">
            <div className="sourcing-empty-title">Getting your first list ready…</div>
            <p>Studio is reading both stores and looking up what their boxes resell for. This takes a few minutes.</p>
          </div>
        ) : null}

        {data && snapshot ? (
          <>
            <StoreProblems snapshot={snapshot} />
            <BuyList data={data} snapshot={snapshot} onOpenProviders={onOpenProviders} />
            <MoreBoxes snapshot={snapshot} />
            <Trending trend={data.trend} />
            <HowItWorks snapshot={snapshot} />
          </>
        ) : null}
      </div>
    </div>
  );
}

function UpdateStatus({
  snapshot,
  refreshing,
  onRefresh,
}: {
  snapshot: SourcingSnapshot | null;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  if (refreshing) return <span className="sourcing-updated">Updating…</span>;
  return (
    <span className="sourcing-updated">
      {snapshot ? `Updated ${clockTime(snapshot.updated_at)} · next ${clockTime(nextUpdate(snapshot.updated_at))}` : ""}
      <button type="button" className="sourcing-link" onClick={onRefresh}>
        Update now
      </button>
    </span>
  );
}

function Settings({
  prefs,
  saving,
  onSave,
}: {
  prefs: SourcingPrefs;
  saving: boolean;
  onSave: (prefs: Partial<SourcingPrefs>) => void;
}) {
  const otherZips = prefs.recent_zips.filter((zip) => zip !== prefs.zip);
  return (
    <div className="sourcing-settings">
      <span className="sourcing-setting">
        Ship to
        <DraftInput
          value={prefs.zip}
          label="ZIP code the boxes ship to"
          width="5.5rem"
          inputMode="numeric"
          maxLength={5}
          disabled={saving}
          clean={(text) => text.replace(/\D/g, "")}
          accept={isZip}
          onCommit={(zip) => onSave({ zip })}
        />
        {otherZips.length ? <span className="sourcing-or">or</span> : null}
        {otherZips.map((zip) => (
          <button
            key={zip}
            type="button"
            className="sourcing-chip is-button"
            disabled={saving}
            title={`Ship to ${zip} instead`}
            onClick={() => onSave({ zip })}
          >
            {zip}
          </button>
        ))}
      </span>
      <span className="sourcing-setting">
        Spend up to
        <DraftInput
          value={String(prefs.budget)}
          label="Most to spend"
          prefix="$"
          width="5.5rem"
          inputMode="decimal"
          disabled={saving}
          clean={(text) => text.replace(/[^\d.]/g, "")}
          accept={(text) => Number(text) > 0}
          onCommit={(text) => onSave({ budget: Number(text) })}
        />
      </span>
      <label className="sourcing-setting sourcing-check">
        <input
          type="checkbox"
          checked={prefs.raghouse_vip}
          disabled={saving}
          onChange={(event) => onSave({ raghouse_vip: event.target.checked })}
        />
        I'm a Raghouse VIP
      </label>
    </div>
  );
}

function BuyList({
  data,
  snapshot,
  onOpenProviders,
}: {
  data: SourcingState;
  snapshot: SourcingSnapshot;
  onOpenProviders: () => void;
}) {
  const plan = snapshot.buy_list;
  if (plan.carts.length === 0) {
    // Prices found earlier stay good for two weeks, so a list can stand without a model connected.
    if (!data.research_available) {
      return (
        <div className="sourcing-empty">
          <div className="sourcing-empty-title">One step before Studio can pick boxes</div>
          <p>
            Studio asks your listing AI to look up what each kind of box resells for. Connect ChatGPT, Cursor or
            MiMo and your list fills in on the next update.
          </p>
          <button type="button" className="btn btn-primary btn-sm" onClick={onOpenProviders}>
            Connect an AI
          </button>
        </div>
      );
    }
    return (
      <div className="sourcing-empty">
        <div className="sourcing-empty-title">No box is worth buying right now</div>
        <p>
          Nothing is expected to at least double your money within {formatMoney(plan.budget)}. Studio checks again
          by itself around {clockTime(nextUpdate(snapshot.updated_at))}.
        </p>
      </div>
    );
  }
  const boxes = plan.carts.reduce((sum, cart) => sum + cart.lots.length, 0);
  return (
    <>
      <section className="sourcing-summary" aria-label="Summary">
        <div className="sourcing-summary-main">
          Buy {boxCount(boxes)} for {formatMoney(Math.round(plan.total))}
        </div>
        <div className="sourcing-summary-sub">
          Expected profit about{" "}
          <strong className="sourcing-profit">{formatMoney(Math.round(plan.expected_profit))}</strong>. Every $1 you
          spend should come back as about {moneyBack(plan.total, plan.expected_profit)}.
        </div>
      </section>
      {plan.carts.map((cart, index) => (
        <Cart key={cart.store} cart={cart} step={plan.carts.length > 1 ? index + 1 : null} of={plan.carts.length} />
      ))}
    </>
  );
}

function Cart({ cart, step, of }: { cart: SourcingCart; step: number | null; of: number }) {
  const gap = freeShippingGap(cart);
  return (
    <section className="sourcing-cart" aria-label={cart.name}>
      <div className="sourcing-cart-head">
        {step ? <span className="sourcing-step">Step {step} of {of}</span> : null}
        <h2 className="sourcing-cart-name">
          {cart.name} · {boxCount(cart.lots.length)}
        </h2>
      </div>
      <ol className="sourcing-items">
        {cart.lots.map((lot) => (
          <Item key={lot.variant_id} lot={lot} />
        ))}
      </ol>
      <dl className="sourcing-totals">
        <dt>Boxes</dt>
        <dd>{formatMoney(cart.subtotal)}</dd>
        <dt>Shipping{cart.free_shipping ? "" : " (estimate)"}</dt>
        <dd>{cart.free_shipping ? "Free" : formatMoney(Math.round(cart.shipping))}</dd>
        <dt className="is-total">Total</dt>
        <dd className="is-total">{formatMoney(Math.round(cartTotal(cart)))}</dd>
      </dl>
      {gap ? (
        <p className="sourcing-hint">
          Spend {formatMoney(gap)} more at {cart.name} and shipping is free.
        </p>
      ) : null}
      <a className="btn btn-primary sourcing-cart-button" href={cart.cart_url} target="_blank" rel="noopener noreferrer">
        Open {cart.name} cart
      </a>
      <p className="sourcing-hint sourcing-cart-note">The cart opens with these boxes already in it. Check it, then pay.</p>
    </section>
  );
}

function Item({ lot }: { lot: SourcingLot }) {
  return (
    <li className="sourcing-item">
      <div className="sourcing-item-main">
        <a className="sourcing-item-title" href={lot.url} target="_blank" rel="noopener noreferrer">
          {lot.title}
        </a>
        <div className="sourcing-item-reason">
          {lotReason(lot)}
          {lot.trend_hits.length ? <span className="sourcing-trend"> · trending: {lot.trend_hits.join(", ")}</span> : null}
        </div>
      </div>
      <div className="sourcing-item-money">
        <div>{formatMoney(Math.round(lot.landed))}</div>
        {lot.expected_profit != null ? (
          <div className={lot.expected_profit >= 0 ? "sourcing-profit" : "sourcing-loss"}>
            {lot.expected_profit >= 0 ? "+" : "−"}
            {formatMoney(Math.abs(Math.round(lot.expected_profit)))} profit
          </div>
        ) : null}
      </div>
    </li>
  );
}

function MoreBoxes({ snapshot }: { snapshot: SourcingSnapshot }) {
  const lots = otherLots(snapshot);
  if (lots.length === 0) return null;
  return (
    <details className="sourcing-more">
      <summary>See {lots.length} more boxes Studio looked at</summary>
      <ol className="sourcing-items">
        {lots.map((lot) => (
          <li key={lot.variant_id} className="sourcing-item">
            <div className="sourcing-item-main">
              <a className="sourcing-item-title" href={lot.url} target="_blank" rel="noopener noreferrer">
                {lot.title}
              </a>
              <div className="sourcing-item-reason">{lotReason(lot, true)}</div>
            </div>
            <div className="sourcing-item-money">
              <div>{formatMoney(Math.round(lot.landed))}</div>
              <div className="sourcing-item-why">{whyNotPicked(lot, snapshot)}</div>
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}

/** Why a box that was looked at is not on the list, in a few words. */
function whyNotPicked(lot: SourcingLot, snapshot: SourcingSnapshot): string {
  const profit = lot.expected_profit;
  if (profit == null) return "price not known yet";
  if (profit < 0) return `would lose ${formatMoney(Math.abs(Math.round(profit)))}`;
  if (lot.roi != null && lot.roi < 1) return `only +${formatMoney(Math.round(profit))} profit`;
  if (lot.landed > snapshot.buy_list.budget - snapshot.buy_list.total) return "over your budget";
  return `+${formatMoney(Math.round(profit))} profit`;
}

function Trending({ trend }: { trend: SourcingState["trend"] }) {
  if (trend.terms.length === 0) return null;
  return (
    <section className="sourcing-section" aria-label="Selling right now">
      <h2 className="sourcing-section-title">Selling right now</h2>
      <p className="sourcing-hint">Boxes with these in the name get picked first. Updated every week.</p>
      <div className="sourcing-chips">
        {trend.terms.map((term) => (
          <span key={term} className="sourcing-chip">
            {term}
          </span>
        ))}
      </div>
    </section>
  );
}

function StoreProblems({ snapshot }: { snapshot: SourcingSnapshot }) {
  const problems = Object.values(snapshot.stores).filter((store) => store.error);
  if (problems.length === 0) return null;
  return (
    <div className="sourcing-problem" role="status">
      {problems.map((store) => (
        <p key={store.name}>
          {store.error} Its boxes are left out until the next update.
        </p>
      ))}
    </div>
  );
}

function HowItWorks({ snapshot }: { snapshot: SourcingSnapshot }) {
  const a = snapshot.assumptions;
  return (
    <details className="sourcing-more">
      <summary>How Studio picks boxes</summary>
      <ul className="sourcing-how">
        <li>Every {REFRESH_HOURS} hours it reads every box both stores have in stock.</li>
        <li>
          It asks your AI what one piece of each kind of box sells for on eBay, Poshmark, Depop and Mercari, and
          checks again every two weeks.
        </li>
        <li>
          Profit assumes about {Math.round(a.sell_through * 100)}% of the sellable pieces sell (more for boxes that
          sell out fast), minus {Math.round(a.fees * 100)}% marketplace fees and the box's cost with shipping. Recycle
          lots count 60% of their pcs as sellable, Recycle &amp; Good 75%, B Grade 60%, C Grade 50% and every other lot 90%.
        </li>
        <li>It picks the best boxes that should at least double your money, one of each kind, up to your budget.</li>
        <li>
          Raghouse shipping is FedEx Ground from Phoenix to {snapshot.destination_zip}, scaled to a checkout you
          already paid. Thrift Vintage Fashion is a UPS Ground estimate, still at list price.
        </li>
        <li>Studio never buys. The cart buttons only fill a cart for you to check and pay.</li>
      </ul>
    </details>
  );
}

function DraftInput({
  value,
  label,
  prefix,
  width,
  inputMode,
  maxLength,
  disabled,
  clean,
  accept,
  onCommit,
}: {
  value: string;
  label: string;
  prefix?: string;
  width: string;
  inputMode: "numeric" | "decimal";
  maxLength?: number;
  disabled: boolean;
  clean: (text: string) => string;
  accept: (text: string) => boolean;
  onCommit: (text: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const [saved, setSaved] = useState(value);
  if (saved !== value) {
    // The saved value changed underneath the field, e.g. a recent ZIP was tapped.
    setSaved(value);
    setDraft(value);
  }
  const commit = () => {
    const next = draft.trim();
    if (next !== value && accept(next)) onCommit(next);
    else setDraft(value);
  };
  return (
    <span className="sourcing-input">
      {prefix ? <span className="sourcing-input-prefix">{prefix}</span> : null}
      <input
        className="input input-sm"
        style={{ width }}
        type="text"
        inputMode={inputMode}
        maxLength={maxLength}
        aria-label={label}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(clean(event.target.value))}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") setDraft(value);
        }}
      />
    </span>
  );
}
