import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SourceBoxes, SourcingCart, SourcingLot, SourcingPrefs, SourcingSnapshot, SourcingState } from "../api/types";
import { addToast } from "../ui/toast";
import { BoughtBoxes } from "./BoughtBoxes";
import { BOXES_QUERY_KEY, boxFromLot, calibrationNote, recentlyBought, shippingNote } from "./boxPurchases";
import { DraftInput } from "./DraftInput";
import { ScoutPanel } from "./ScoutPanel";
import { formatMoney } from "./analyticsFormat";
import {
  REFRESH_HOURS,
  boxCount,
  cartTotal,
  clockTime,
  exclusionSummary,
  freeShippingGap,
  isZip,
  lotReason,
  nextUpdate,
  otherLots,
  planMetrics,
  planNeedsUpdate,
  saleDate,
  storeName,
  whyNotPicked,
} from "./boxScout";

const QUERY_KEY = ["sourcing"];

interface Props {
  onOpenProviders: () => void;
  onOpenListing: (convId: string) => void;
}

const TAB_KEY = "studio.sourcing.tab";

export function SourcingPage({ onOpenProviders, onOpenListing }: Props) {
  const [tab, setTab] = useState(() => localStorage.getItem(TAB_KEY) === "scout" ? "scout" : "boxes");
  const choose = (next: "boxes" | "scout") => {
    localStorage.setItem(TAB_KEY, next);
    setTab(next);
  };
  return (
    <div className="analytics-page">
      <div className="analytics-inner sourcing-inner">
        <div className="pr-pills sourcing-tabs" role="tablist" aria-label="Sourcing">
          {([["boxes", "Wholesale boxes"], ["scout", "Scout an item"]] as const).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={`pr-pill${tab === id ? " is-active" : ""}`}
              onClick={() => choose(id)}
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "scout" ? (
          <>
            <header className="sourcing-header">
              <h1 className="sourcing-title">Is it worth buying?</h1>
              <p className="sourcing-lead">
                Photograph an item and its tag in the store. Studio identifies it, looks up what it has sold for,
                and tells you the most worth paying. Nothing is bought or listed.
              </p>
            </header>
            <ScoutPanel onOpenListing={onOpenListing} />
          </>
        ) : (
          <BoxSourcing onOpenProviders={onOpenProviders} onOpenListing={onOpenListing} />
        )}
      </div>
    </div>
  );
}

function BoxSourcing({ onOpenProviders, onOpenListing }: Props) {
  const queryClient = useQueryClient();
  const [choice, setChoice] = useState("all");
  const query = useQuery({
    queryKey: QUERY_KEY,
    queryFn: api.sourcing.get,
    // Keep watching until the list catches up with saved shipping and budget settings.
    refetchInterval: (current) => {
      const state = current.state.data;
      return state && (state.refreshing || planNeedsUpdate(state)) ? 3000 : false;
    },
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
  const selectedSnapshot = snapshot ? {
    ...snapshot,
    buy_list: choice === "all" ? snapshot.buy_list : snapshot.store_buy_lists[choice],
    lots: snapshot.lots.filter((lot) => choice === "all" || lot.store === choice),
  } : null;
  const updating = !!data && (data.refreshing || refresh.isPending || savePrefs.isPending
    || planNeedsUpdate(data));

  return (
    <>
        <header className="sourcing-header">
          <div className="sourcing-title-row">
            <h1 className="sourcing-title">Source with sales evidence</h1>
            {data ? (
              <UpdateStatus
                snapshot={snapshot}
                refreshing={data.refreshing || refresh.isPending}
                onRefresh={() => refresh.mutate()}
              />
            ) : null}
          </div>
          <p className="sourcing-lead">
            Compare wholesale boxes using recent comparable sales, current competition, and your costs.
            A mixed box’s contents and future sales remain uncertain.
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
            <p>Studio is reading both stores and collecting dated sold listings. Only boxes with enough recent evidence can qualify. This takes a few minutes.</p>
          </div>
        ) : null}
        {data && !snapshot ? <BoughtBoxes /> : null}

        {data && snapshot ? (
          <>
            <StoreProblems snapshot={snapshot} />
            <SeasonalContext snapshot={snapshot} />
            <ResearchCoverage snapshot={snapshot} />
            <Choices snapshot={snapshot} choice={choice} onChoose={setChoice} />
            {updating ? <p className="sourcing-hint" role="status">Updating your options. Cart links will be ready when the check finishes.</p> : null}
            {selectedSnapshot ? <>
              <BuyList data={data} snapshot={selectedSnapshot} choice={choice} updating={updating} onOpenProviders={onOpenProviders} onOpenListing={onOpenListing} />
              <AvailableBoxes snapshot={selectedSnapshot} onOpenListing={onOpenListing} />
            </> : null}
            <BoughtBoxes />
            <Trending trend={data.trend} />
            <HowItWorks snapshot={snapshot} />
          </>
        ) : null}
    </>
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
        Minimum ROI
        <DraftInput
          value={String(Math.round(prefs.min_roi * 100))}
          label="Minimum estimated profit as a percentage of purchase cost"
          suffix="%"
          width="5.5rem"
          inputMode="decimal"
          disabled={saving}
          clean={(text) => text.replace(/[^\d.]/g, "")}
          accept={(text) => text !== "" && Number.isFinite(Number(text)) && Number(text) >= 0}
          onCommit={(text) => onSave({ min_roi: Number(text) / 100 })}
        />
      </span>
      <span className="sourcing-setting">
        Purchase budget
        <DraftInput
          value={String(prefs.budget)}
          label="Most to spend on boxes and inbound shipping before tax"
          prefix="$"
          width="5.5rem"
          inputMode="decimal"
          disabled={saving}
          clean={(text) => text.replace(/[^\d.]/g, "")}
          accept={(text) => Number.isFinite(Number(text)) && Number(text) > 0}
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
      <div className="sourcing-settings sourcing-window-settings" aria-label="Selling window settings">
        <span className="sourcing-setting">Ready to sell in
          <DraftInput value={String(prefs.ready_in_weeks)} label="Weeks for shipping, preparation and listing" suffix="weeks" width="6rem" inputMode="numeric" disabled={saving}
            clean={(text) => text.replace(/\D/g, "")} accept={(text) => text !== "" && Number(text) <= 26}
            onCommit={(text) => onSave({ ready_in_weeks: Number(text) })} />
        </span>
        <span className="sourcing-setting">Then selling for
          <DraftInput value={String(prefs.selling_window_weeks)} label="Length of the target selling window in weeks" suffix="weeks" width="6rem" inputMode="numeric" disabled={saving}
            clean={(text) => text.replace(/\D/g, "")} accept={(text) => Number(text) >= 1 && Number(text) <= 26}
            onCommit={(text) => onSave({ selling_window_weeks: Number(text) })} />
        </span>
      </div>
      <details className="sourcing-assumptions">
        <summary>Your planning assumptions: {Math.round(prefs.sell_through * 100)}% sell, {Math.round(prefs.fees * 100)}% fees, {formatMoney(prefs.cost_per_piece)} costs per usable piece</summary>
        <div className="sourcing-settings">
          <span className="sourcing-setting">Usable pieces expected to sell
            <DraftInput value={String(Math.round(prefs.sell_through * 100))} label="Percentage of usable pieces you plan to sell" suffix="%" width="5rem" inputMode="decimal" disabled={saving}
              clean={(text) => text.replace(/[^\d.]/g, "")} accept={(text) => Number(text) > 0 && Number(text) <= 100}
              onCommit={(text) => onSave({ sell_through: Number(text) / 100 })} />
          </span>
          <span className="sourcing-setting">Effective marketplace fees
            <DraftInput value={String(Math.round(prefs.fees * 100))} label="Effective marketplace and payment fees as a percentage of item revenue" suffix="%" width="5rem" inputMode="decimal" disabled={saving}
              clean={(text) => text.replace(/[^\d.]/g, "")} accept={(text) => text !== "" && Number(text) >= 0 && Number(text) < 100}
              onCommit={(text) => onSave({ fees: Number(text) / 100 })} />
          </span>
          <span className="sourcing-setting">Other costs per usable piece
            <DraftInput value={String(prefs.cost_per_piece)} label="Operating allowance per usable piece" prefix="$" width="5.5rem" inputMode="decimal" disabled={saving}
              clean={(text) => text.replace(/[^\d.]/g, "")} accept={(text) => text !== "" && Number.isFinite(Number(text)) && Number(text) >= 0}
              onCommit={(text) => onSave({ cost_per_piece: Number(text) })} />
          </span>
        </div>
        <p className="sourcing-hint">These are your planning inputs, not measured probabilities. Use your actual costs for cleaning, repairs, photography, labor, packaging, seller-paid postage, fixed fees and returns. The allowance is charged for every usable piece, even those that don’t sell. Purchase tax is extra.</p>
      </details>
    </div>
  );
}

function SeasonalContext({ snapshot }: { snapshot: SourcingSnapshot }) {
  const { window, seller_history: history } = snapshot.seasonality;
  const date = (value: string) => new Date(`${value}T12:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  return <section className="sourcing-coverage" aria-label="Seasonal sourcing context">
    <strong>Buying now for {date(window.start_date)} – {date(window.end_date)}</strong>
    <p className="sourcing-hint">Research targets this selling window. Matching themes get priority among qualifying boxes; seasonality does not raise estimated prices or sales.</p>
    {history.groups.length ? <details>
      <summary>Your sales in the same calendar windows: {history.groups.length} category {history.groups.length === 1 ? "group" : "groups"}</summary>
      <p className="sourcing-hint">Looking back up to three years. These are recorded sales, not a measure of demand or your chance of selling a box. Prices below are historical; box estimates use recent sold evidence.</p>
      {history.groups.map((group) => <p className="sourcing-hint" key={`${group.category_path}:${group.item_type}`}>
        {group.category_path}{group.item_type ? ` · ${group.item_type}` : ""}: {group.count} sales · historical median {formatMoney(group.historical_median_price)}
      </p>)}
    </details> : <p className="sourcing-hint">{history.matching_window_sales} recorded sales in the same calendar windows over the previous three years. No category/type group has the {history.minimum_group_sales} sales needed for personal context yet. Studio can still research seasonal themes.</p>}
  </section>;
}

function Choices({ snapshot, choice, onChoose }: {
  snapshot: SourcingSnapshot;
  choice: string;
  onChoose: (choice: string) => void;
}) {
  const hasRecommendations = [snapshot.buy_list, ...Object.values(snapshot.store_buy_lists)].some((plan) => plan.carts.length > 0);
  return (
    <section aria-label="Compare sourcing options">
      <h2 className="sourcing-section-title">{hasRecommendations ? "Choose a buy list" : "Browse by supplier"}</h2>
      <p className="sourcing-hint">{hasRecommendations
        ? `Each option uses the same ${formatMoney(snapshot.buy_list.budget)} budget including estimated shipping. Choose one; these are alternatives. Tax is extra.`
        : "Choose all boxes or a supplier to browse what Studio checked. Recommendations appear when the evidence and cost checks pass."}</p>
      {Object.entries(snapshot.calibration ?? {}).map(([store, calibration]) => {
        const note = calibrationNote(storeName(store), calibration);
        return note ? <p key={store} className="sourcing-hint">{note}</p> : null;
      })}
      {snapshot.vip_upside && snapshot.vip_upside.boxes > 0 ? <p className="sourcing-hint">
        Raghouse VIP ({formatMoney(snapshot.vip_upside.monthly_fee)}/month) would add {boxCount(snapshot.vip_upside.boxes)} to this list,
        about {formatMoney(Math.round(snapshot.vip_upside.extra_profit))} more estimated profit. Turn on “I'm a Raghouse VIP” above once you join.
      </p> : null}
      <div className="sourcing-choices">
        {["all", ...Object.keys(snapshot.stores)].map((key) => {
          const plan = key === "all" ? snapshot.buy_list : snapshot.store_buy_lists[key];
          const count = plan.carts.reduce((sum, cart) => sum + cart.lots.length, 0);
          const metrics = planMetrics(plan);
          return (
            <button key={key} type="button" className="sourcing-choice" aria-pressed={choice === key} onClick={() => onChoose(key)}>
              <strong>{key === "all" ? (hasRecommendations ? "Combined list" : "All suppliers") : storeName(key)}</strong>
              {count ? <>
                <span>{boxCount(count)} · {formatMoney(plan.total)}</span>
                <span>Est. profit {formatMoney(Math.round(plan.expected_profit))}</span>
                <span>Lower-sales test {formatMoney(Math.round(metrics.downside))}</span>
              </> : <>
                <span>{snapshot.stores[key]?.error ? "Store unavailable" : boxCount(snapshot.lots.filter((lot) => key === "all" || lot.store === key).length)}</span>
                <span>No recommendations yet</span>
              </>}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function BuyList({
  data,
  snapshot,
  choice,
  updating,
  onOpenProviders,
  onOpenListing,
}: {
  data: SourcingState;
  snapshot: SourcingSnapshot;
  choice: string;
  updating: boolean;
  onOpenProviders: () => void;
  onOpenListing: (convId: string) => void;
}) {
  const plan = snapshot.buy_list;
  const hasEvidence = snapshot.lots.some((lot) => lot.resale_per_pc != null);
  if (plan.carts.length === 0) {
    if (choice !== "all" && snapshot.stores[choice]?.error) {
      return <div className="sourcing-empty">
        <div className="sourcing-empty-title">{storeName(choice)} is unavailable</div>
        <p>Studio couldn’t check this store. Try updating again, or compare the other buy lists.</p>
      </div>;
    }
    // Prices found earlier stay good for one week, so a list can stand without a model connected.
    if (!data.research_available && snapshot.lots.length > 0 && !hasEvidence) {
      return (
        <div className="sourcing-empty">
          <div className="sourcing-empty-title">One step before Studio can pick boxes</div>
          <p>Connect ChatGPT, Cursor or MiMo to research recent sold items. A box qualifies only when the evidence and cost checks pass.</p>
          <button type="button" className="btn btn-primary btn-sm" onClick={onOpenProviders}>
            Connect an AI
          </button>
        </div>
      );
    }
    return (
      <div className="sourcing-empty">
        <div className="sourcing-empty-title">{!snapshot.lots.length ? "No boxes available in this check"
          : hasEvidence ? "No recommendations within these settings" : "No recommendations yet — sold evidence is missing"}</div>
        <p>{snapshot.lots.length ? (hasEvidence
          ? `No box passes all the evidence, return and lower-sales checks within ${formatMoney(plan.budget)} including shipping. Of ${boxCount(snapshot.lots.length)}: ${exclusionSummary(plan)}. Browse the boxes below to see what ruled each one out, or change the settings above.`
          : `Studio found ${boxCount(snapshot.lots.length)}, but has no usable recent sold evidence to estimate their resale. Each theme needs at least 3 distinct comparable sales within 30 days. The boxes are shown below for you to review.`)
          : "This check returned no available boxes for the selected suppliers. Review any supplier errors above."}</p>
        <p className="sourcing-hint">Next automatic check around {clockTime(nextUpdate(snapshot.updated_at))}.</p>
      </div>
    );
  }
  const boxes = plan.carts.reduce((sum, cart) => sum + cart.lots.length, 0);
  const metrics = planMetrics(plan);
  return (
    <>
      <section className="sourcing-summary" aria-label="Summary">
        <div className="sourcing-summary-main">
          {boxCount(boxes)} to review · {formatMoney(Math.round(plan.total))} with shipping
        </div>
        <div className="sourcing-summary-sub">
          Estimated profit <strong className="sourcing-profit">{formatMoney(Math.round(plan.expected_profit))}</strong> after fees and {formatMoney(metrics.operating)} in operating costs, before tax.
        </div>
        <dl className="sourcing-metrics">
          <div><dt>Usable pieces (estimate)</dt><dd>{Math.round(metrics.usable)}</dd></div>
          <div><dt>Sales in your plan</dt><dd>~{Math.round(metrics.sold)}</dd></div>
          <div><dt>Lower-sales test profit</dt><dd>{formatMoney(Math.round(metrics.downside))}</dd></div>
        </dl>
      </section>
      <p className="sourcing-hint">{formatMoney(Math.max(0, plan.budget - plan.total))} of your purchase budget remains before tax. Keep another {formatMoney(metrics.operating)} for operating costs. The lower-sales test assumes only half your planned sales, at each theme’s lowest retained sale price, with operating costs on those pieces. It is a sensitivity test, not a guaranteed minimum profit.</p>
      {plan.carts.map((cart, index) => (
        <Cart key={cart.store} cart={cart} updating={updating} step={plan.carts.length > 1 ? index + 1 : null} of={plan.carts.length} onOpenListing={onOpenListing} />
      ))}
    </>
  );
}

function Cart({ cart, step, of, updating, onOpenListing }: {
  cart: SourcingCart; step: number | null; of: number; updating: boolean; onOpenListing: (convId: string) => void;
}) {
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
          <Item key={`${lot.store}:${lot.variant_id}`} lot={lot} storeName={cart.name} onOpenListing={onOpenListing} />
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
          Free shipping starts at {formatMoney(cart.free_shipping_over!)} in boxes ({formatMoney(gap)} more).
        </p>
      ) : null}
      {updating ? <button className="btn btn-primary sourcing-cart-button" disabled>Updating cart…</button> : <a className="btn btn-primary sourcing-cart-button" href={cart.cart_url} target="_blank" rel="noopener noreferrer">
        {cart.cart_fills ? `Open ${cart.name} cart` : `Open on ${cart.name}`}
      </a>}
      <p className="sourcing-hint sourcing-cart-note">{cart.cart_fills
        ? "The cart opens with these boxes already in it. Check it, then pay."
        : `Each ${cart.name} lot is bought from its own page after signing in; shipping and card processing are itemised at checkout. Open each box above.`}</p>
    </section>
  );
}

function Item({ lot, storeName, onOpenListing }: { lot: SourcingLot; storeName: string; onOpenListing: (convId: string) => void }) {
  const queryClient = useQueryClient();
  const boxes = useQuery({ queryKey: BOXES_QUERY_KEY, queryFn: api.boxes.list });
  const record = useMutation({
    mutationFn: () => api.boxes.create(boxFromLot(lot)),
    onSuccess: (data: SourceBoxes) => {
      queryClient.setQueryData(BOXES_QUERY_KEY, data);
      addToast({
        type: "success",
        title: "Added to your boxes",
        description: `Correct the shipping under Boxes you bought once ${storeName} charges it.`,
      });
    },
    onError: (error: Error) =>
      addToast({ type: "error", title: "Could not record the box", description: error.message }),
  });
  const bought = recentlyBought(lot, boxes.data?.boxes ?? []);
  return (
    <li className="sourcing-item">
      <div className="sourcing-item-main">
        <a className="sourcing-item-title" href={lot.url} target="_blank" rel="noopener noreferrer">
          {lot.title}
        </a>
        <div className="sourcing-item-reason">
          {lotReason(lot)}
          {lot.trend_hits.length ? <span className="sourcing-trend"> · selling-window match: {lot.trend_hits.join(", ")}</span> : null}
        </div>
        <div className="sourcing-item-reason">About {formatMoney(lot.cog_per_usable_pc)} per usable piece, including shipping</div>
        {lot.break_even_pcs != null ? <div className="sourcing-item-reason">
          Break even after {lot.break_even_pcs} sales · plan assumes ~{Math.round(lot.usable_pcs * lot.sell_through)} sales
        </div> : null}
        {lot.pcs_estimated || lot.lbs_estimated ? <div className="sourcing-item-why">{lot.pcs_estimated ? "Piece count is estimated from weight. " : ""}{lot.lbs_estimated ? "Shipping weight is estimated. " : ""}Check the supplier’s lot details.</div> : null}
        <ResearchEvidence lot={lot} onOpenListing={onOpenListing} />
      </div>
      <div className="sourcing-item-money">
        <div>{formatMoney(Math.round(lot.landed))}</div>
        {lot.expected_profit != null ? (
          <div className={lot.expected_profit >= 0 ? "sourcing-profit" : "sourcing-loss"}>
            {lot.expected_profit >= 0 ? "+" : "−"}
            {formatMoney(Math.abs(Math.round(lot.expected_profit)))} profit
          </div>
        ) : null}
        {lot.downside_profit != null ? <div className="sourcing-item-why">Lower-sales test {formatMoney(Math.round(lot.downside_profit))}</div> : null}
        <button
          type="button"
          className="sourcing-link sourcing-bought"
          disabled={bought || record.isPending || !boxes.data}
          onClick={() => record.mutate()}
        >
          {bought ? "Bought" : "I bought this"}
        </button>
      </div>
    </li>
  );
}

function AvailableBoxes({ snapshot, onOpenListing }: { snapshot: SourcingSnapshot; onOpenListing: (convId: string) => void }) {
  const lots = otherLots(snapshot);
  if (lots.length === 0) return null;
  return (
    <section className="sourcing-section" aria-label="Available boxes">
      <h2 className="sourcing-section-title">{snapshot.buy_list.carts.length ? "Other available boxes" : "Available boxes"} · {boxCount(lots.length)}</h2>
      <p className="sourcing-hint">Every box both stores have in stock, best first. Each row shows why it isn’t in the recommended buy list; you can still open the supplier’s listing.</p>
      <ol className="sourcing-items">
        {lots.map((lot) => (
          <li key={`${lot.store}:${lot.variant_id}`} className="sourcing-item">
            <div className="sourcing-item-main">
              <a className="sourcing-item-title" href={lot.url} target="_blank" rel="noopener noreferrer">
                {lot.title}
              </a>
              <div className="sourcing-item-reason">{lotReason(lot, true)}</div>
              <ResearchEvidence lot={lot} onOpenListing={onOpenListing} />
            </div>
            <div className="sourcing-item-money">
              <div>{formatMoney(Math.round(lot.landed))}</div>
              <div className="sourcing-item-why">{whyNotPicked(lot, snapshot.buy_list)}</div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ResearchEvidence({ lot, onOpenListing }: { lot: SourcingLot; onOpenListing: (convId: string) => void }) {
  const [open, setOpen] = useState(false);
  // The examples are fetched when the seller opens them, so the page itself stays light.
  const evidence = useQuery({
    queryKey: ["sourcing", "evidence", lot.theme],
    queryFn: () => api.sourcing.evidence(lot.theme),
    enabled: open,
    staleTime: 5 * 60_000,
  });
  if (!lot.comps_count) return <div className="sourcing-item-why">Not enough recent sold evidence to estimate resale.</div>;
  const data = evidence.data;
  return <details className="sourcing-evidence" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{lot.comps_count} {lot.research_source === "Your sales" ? "of your sales" : "reported sales"} · {lot.research_at ? clockTime(lot.research_at) : ""}</summary>
    {evidence.isLoading ? <p className="sourcing-hint">Loading the sales…</p> : null}
    {evidence.isError ? <p className="sourcing-hint">{(evidence.error as Error).message}</p> : null}
    {data ? <>
      <p className="sourcing-hint">{data.source === "Your sales"
        ? "These are your own recorded sales of this kind of piece."
        : `${data.source} reported the web sales. Studio leaves out any whose title shows a different garment, a bundle or new with tags. Sale status, dates, brand, era and condition are AI-reported, and Studio does not independently verify each source page. Your own recorded sales count too. Review the links before buying.`}</p>
      <ul className="sourcing-comps">
        {data.comps.map((comp) => <li key={comp.conversation_id ?? comp.url}>
          {comp.conversation_id
            ? <button type="button" className="sourcing-link" onClick={() => onOpenListing(comp.conversation_id!)}>{comp.title}</button>
            : <a href={comp.url} target="_blank" rel="noopener noreferrer">{comp.title}</a>}
          <span>{comp.conversation_id ? "Your sale" : comp.marketplace} · {formatMoney(comp.price)} · {comp.conversation_id ? "sold" : "reported sold"} {saleDate(comp.sold_at)}</span>
          {comp.conversation_id ? null : <q>{comp.snippet}</q>}
        </li>)}
      </ul>
      {data.active_median != null ? <p className="sourcing-hint">Current asking-price median {formatMoney(data.active_median)}; the resale estimate is capped at this price.</p>
        : <p className="sourcing-hint">Current competition sample is too small to cap the price. Market sell-through and time to sell are unknown.</p>}
      {data.active.length ? <ul className="sourcing-comps">
        {data.active.map((comp) => <li key={comp.url}>
          <a href={comp.url} target="_blank" rel="noopener noreferrer">{comp.title}</a>
          <span>{comp.marketplace} · asking {formatMoney(comp.price)}</span>
        </li>)}
      </ul> : null}
    </> : null}
  </details>;
}

function ResearchCoverage({ snapshot }: { snapshot: SourcingSnapshot }) {
  const priced = snapshot.lots.filter((lot) => lot.resale_per_pc != null).length;
  return <div className="sourcing-research-status" role="status">
    <strong>{boxCount(snapshot.lots.length)} in this check · {priced} with enough recent sold evidence.</strong>
    <span>At least 3 distinct reported sales within 30 days. Older sales provide context. Prices are checked weekly. Sales evidence supports an estimate; it does not measure the chance your box will sell.</span>
  </div>;
}

function Trending({ trend }: { trend: SourcingState["trend"] }) {
  if (trend.terms.length === 0) return null;
  return (
    <section className="sourcing-section" aria-label="Selling-window research">
      <h2 className="sourcing-section-title">Themes to research</h2>
      <p className="sourcing-hint">Seasonal reports and your selling window guide research and prioritize qualifying boxes. A theme match cannot qualify a box or increase its projected sales. {trend.updated_at ? `Researched ${clockTime(trend.updated_at)}.` : ""}</p>
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
        <li>Every {REFRESH_HOURS} hours it reads every box Raghouse, Thrift Vintage Fashion and PaperCrane list. Raghouse Recycle boxes, Thrift Vintage Fashion A/B, B, B/C and C grades and PaperCrane Mixed/As-Is (C) lots are never considered; PaperCrane Cream (A) and Standard (B) lots are covered by its Buyer Protection beyond a 5% or 10% tolerance for unsellable pieces.</li>
        <li>
          It groups boxes by the kind of piece inside (“vintage graphic t-shirts”, “hawaiian shirts”) and prices each kind from your own recorded sales of that kind
          plus what your AI finds sold on eBay, Poshmark, Depop and Mercari, rechecked weekly. It requires dated sold examples and computes their median, capped by comparable asking prices when enough are available.
        </li>
        <li>
          Profit uses your {Math.round(a.sell_through * 100)}% sales assumption, {Math.round(a.fees * 100)}% effective fees,
          {" "}{formatMoney(a.cost_per_piece)} operating allowance per usable piece, and purchase cost with shipping. Usable-piece shares are planning estimates based on grade, not inspected counts.
        </li>
        <li>Each recommended box must meet your ROI target and avoid a loss when only half your planned pieces sell, at the lower of its lowest retained sold price and resale estimate, after operating costs on those pieces.</li>
        <li>It prefers researched selling-window matches among qualifying boxes, then incremental return, one box per theme, and checks the whole cart’s shipping. It also tests pairs that unlock free shipping. This is a greedy selection; it doesn’t guarantee the best possible combination.</li>
        <li>
          Raghouse shipping is FedEx Ground from Phoenix to {snapshot.destination_zip}, Thrift Vintage Fashion is UPS Ground from Hialeah, and PaperCrane is UPS Ground from each seller’s state
          ({snapshot.stores.papercrane?.origins ?? 0} states this check) plus card processing at Stripe’s standard rate, which PaperCrane does not publish; each store is
          scaled to what it charged your recorded orders ({Object.entries(snapshot.shipping.factors).map(([store, factor]) => `${storeName(store)} ${Math.round(factor * 100)}%`).join(", ")} of list).
          {" "}{Object.keys(snapshot.shipping.factors).map((store) => shippingNote(storeName(store), snapshot.shipping.calibration[store])).filter(Boolean).join(" ")}
          {" "}Correct a box’s shipping under Boxes you bought once the store charges it, and the estimates follow.
        </li>
        <li>Studio never buys. The cart buttons only fill a cart for you to check and pay.</li>
        <li>Inspect supplier photos and grade notes before buying. Check sale sources against the likely brand, era, condition and garment mix. Confirm final shipping and tax at checkout; a wholesale box is not an inspected set of identical products.</li>
      </ul>
    </details>
  );
}
