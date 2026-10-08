import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SaleCalendarItem, SaleEvent, SaleEventStatus, SaleMarketplace, SalePlan, SaleRecord } from "../api/saleCalendar";
import { confirmDialog } from "../ui/confirmDialog";
import { formatMoney } from "./analyticsFormat";
import { marketplaceName } from "./marketplaceNames";
import { calendarDate, dateOnly, monthDays, saleProfit, shiftMonth } from "./saleCalendarDates";
import "../styles/sale-calendar.css";

const MARKETS: SaleMarketplace[] = ["ebay", "depop", "etsy"];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
type CalendarSave = { kind: "plan"; input: SalePlan } | { kind: "record"; input: SaleRecord };
type FormSeed = { start: string; end: string; marketplace: string; event?: SaleEvent; record?: boolean };

function displayDate(day: string): string {
  return dateOnly(day).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function SaleCalendar({ onOpenListing }: { onOpenListing: (id: string) => void }) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const [today, setToday] = useState(() => calendarDate(new Date()));
  useEffect(() => {
    const timer = window.setInterval(() => setToday(calendarDate(new Date())), 60000);
    return () => window.clearInterval(timer);
  }, []);
  const [month, setMonth] = useState(today.slice(0, 7));
  const [market, setMarket] = useState<SaleMarketplace | "all">("all");
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [form, setForm] = useState<FormSeed | null>(null);
  const [notice, setNotice] = useState("");
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["sale-calendar", timezone], queryFn: () => api.saleCalendar.get(timezone) });
  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: SaleEventStatus }) => api.saleCalendar.status(id, status),
    onSuccess: () => Promise.all([queryClient.invalidateQueries({ queryKey: ["sale-calendar"] }), queryClient.invalidateQueries({ queryKey: ["analytics"] })]),
  });
  const deleteMutation = useMutation({
    mutationFn: api.saleCalendar.remove,
    onSuccess: () => Promise.all([queryClient.invalidateQueries({ queryKey: ["sale-calendar"] }), queryClient.invalidateQueries({ queryKey: ["analytics"] })]),
  });
  const busy = statusMutation.isPending || deleteMutation.isPending;
  const events = (query.data?.events ?? []).filter(event => market === "all" || event.marketplace === market);
  const visible = events.filter(event => selectedDay
    ? event.start_date <= selectedDay && event.end_date >= selectedDay
    : event.start_date <= monthDays(month)[41]! && event.end_date >= `${month}-01`);
  const activeEvents = events.filter(event => event.status !== "cancelled");

  function newPlan(start = selectedDay ?? today, end = start, marketplace: SaleMarketplace = market === "all" ? "ebay" : market) {
    setForm({ start, end, marketplace });
    setMonth(start.slice(0, 7));
    setNotice("");
  }

  async function remove(event: SaleEvent) {
    if (await confirmDialog(`Delete “${event.title}” from your calendar?\nThis removes its local promotion history.`, { variant: "destructive", confirmLabel: "Delete event" })) {
      deleteMutation.mutate(event.id);
    }
  }

  return (
    <section className="analytics-section sale-calendar" aria-label="Sale calendar">
      <div className="analytics-title-row">
        <h2 className="analytics-section-title">Sale calendar</h2>
        <div className="sale-actions">
          <button type="button" className="pr-pill" disabled={query.isFetching} onClick={() => void query.refetch()}>Refresh calendar</button>
          <button type="button" className="pr-pill" disabled={!query.data} onClick={() => newPlan()}>Plan a sale</button>
          <button type="button" className="pr-pill" disabled={!query.data} onClick={() => setForm({ start: today, end: today, marketplace: market === "all" ? "ebay" : market, record: true })}>Record a sale I ran</button>
        </div>
      </div>
      <p className="analytics-note">Plan, run the sale on the marketplace, then mark it as run here. Saving a plan only adds it to this calendar.</p>
      {query.isLoading ? <p className="analytics-status" role="status">Loading sale calendar…</p> : null}
      {query.isError ? <p className="sale-error" role="alert">{query.error.message}</p> : null}
      {statusMutation.isError || deleteMutation.isError ? <p className="sale-error" role="alert">{(statusMutation.error ?? deleteMutation.error)?.message}</p> : null}
      {notice ? <p className="analytics-status" role="status">{notice}</p> : null}
      {query.data ? <>
        <div className="sale-patterns">
          {query.data.patterns.map(pattern => (
            <article key={pattern.marketplace} className="sale-pattern">
              <h3>{marketplaceName(pattern.marketplace)}</h3>
              <p>{pattern.reason}</p>
              <div className="sale-weekdays" aria-label={`${marketplaceName(pattern.marketplace)} sales by weekday`}>
                {pattern.weekdays.map((day, index) => (
                  <div key={day.label} title={`${day.label}: ${day.count} sales; ${day.average ?? "—"} per week`}>
                    <span>{WEEKDAYS[index]}</span><strong>{day.count}</strong>
                  </div>
                ))}
              </div>
              {pattern.weeks > 0 ? <small>{pattern.sales} dated sales · {displayDate(pattern.history_start)}–{displayDate(pattern.history_end)}</small> : null}
              {pattern.suggested_start && pattern.suggested_end ? <button type="button" className="pr-pill" onClick={() => newPlan(pattern.suggested_start!, pattern.suggested_end!, pattern.marketplace)}>Try {displayDate(pattern.suggested_start)}{pattern.suggested_end === pattern.suggested_start ? "" : `–${displayDate(pattern.suggested_end)}`}</button> : null}
            </article>
          ))}
        </div>
        <p className="analytics-note">Suggested windows are experiments based on imported sales in {timezone}, assuming complete history. They don’t predict extra sales from a discount. Stock, traffic, seasonality, and previous promotions can affect the pattern.</p>
        <div className="sale-calendar-toolbar">
          <div className="sale-actions">
            <button type="button" className="pr-pill" aria-label="Previous month" onClick={() => { setMonth(shiftMonth(month, -1)); setSelectedDay(null); }}>←</button>
            <h3>{dateOnly(`${month}-01`).toLocaleDateString(undefined, { month: "long", year: "numeric" })}</h3>
            <button type="button" className="pr-pill" aria-label="Next month" onClick={() => { setMonth(shiftMonth(month, 1)); setSelectedDay(null); }}>→</button>
            <button type="button" className="pr-pill" onClick={() => { setMonth(today.slice(0, 7)); setSelectedDay(today); }}>Today</button>
          </div>
          <label>Marketplace <select value={market} onChange={event => setMarket(event.target.value as typeof market)}>
            <option value="all">All marketplaces</option>{MARKETS.map(value => <option key={value} value={value}>{marketplaceName(value)}</option>)}
          </select></label>
        </div>
        <div className="sale-month" role="group" aria-label="Promotion dates">
          {WEEKDAYS.map(day => <div className="sale-weekday" key={day}>{day}</div>)}
          {monthDays(month).map(day => {
            const onDay = activeEvents.filter(event => event.start_date <= day && event.end_date >= day);
            return <button key={day} type="button" aria-pressed={selectedDay === day} aria-label={`${displayDate(day)}, ${onDay.length} sale events`} aria-current={day === today ? "date" : undefined}
              className={`sale-day${day.slice(0, 7) !== month ? " is-outside" : ""}${day === today ? " is-today" : ""}${day === selectedDay ? " is-selected" : ""}`}
              onClick={() => { setSelectedDay(day); if (day.slice(0, 7) !== month) setMonth(day.slice(0, 7)); }}>
              <span>{dateOnly(day).getDate()}</span>
              {onDay.slice(0, 3).map(event => <small className={`sale-chip sale-${event.marketplace}`} key={event.id}>{marketplaceName(event.marketplace)}{event.discount_percent == null ? "" : ` · ${event.discount_percent}%`}</small>)}
              {onDay.length > 3 ? <small>+{onDay.length - 3} more</small> : null}
            </button>;
          })}
        </div>
        <div className="analytics-title-row sale-agenda-title">
          <h3>{selectedDay ? `Events on ${displayDate(selectedDay)}` : "Events this month"}</h3>
          {selectedDay ? <button type="button" className="pr-pill" onClick={() => setSelectedDay(null)}>Show month</button> : null}
        </div>
        {visible.length === 0 ? <p className="analytics-note">No events here yet. Select a day and plan a sale.</p> : null}
        <div className="sale-agenda">
          {visible.map(event => <article className="sale-event" key={event.id}>
            <div className="analytics-title-row"><h3>{event.title}</h3><span className={`sale-chip sale-${event.marketplace}`}>{marketplaceName(event.marketplace)} · {event.status === "ran" ? "Marked as run" : event.status === "planned" ? "Planned" : "Cancelled"}</span></div>
            <p>{displayDate(event.start_date)}–{displayDate(event.end_date)} · {event.timezone}{event.discount_percent == null ? "" : ` · ${event.discount_percent}% off`}{event.items.length ? ` · ${event.items.length} items` : " · Entire marketplace"}</p>
            {event.status === "planned" && event.start_date <= today ? <p className="analytics-note">{event.end_date < today ? "This plan has ended. Mark it as run if you ran the sale, or cancel it." : "This sale is due. Set it up on the marketplace, then mark it as run."}</p> : null}
            {event.minimum_profit != null && event.fee_percent != null && event.shipping_cost != null ? <p className="analytics-note">Estimated profit floor: {formatMoney(event.minimum_profit)} per item, using {event.fee_percent}% effective fees and {formatMoney(event.shipping_cost)} seller shipping per item. Actual profit can differ.</p> : null}
            {event.marketplace === "depop" && event.status !== "cancelled" ? <p className="analytics-note">Depop reminder: apply the discount at the start and remove it at the end.</p> : null}
            {event.notes ? <p className="sale-notes">{event.notes}</p> : null}
            {event.items.length ? <details><summary>Included items</summary><ul>{event.items.map(item => <li key={item.id}><button type="button" onClick={() => onOpenListing(item.id)}>{item.title}</button><span>{formatMoney(item.price)} asking · {formatMoney(item.estimated_profit)} estimated profit</span></li>)}</ul></details> : null}
            {event.result ? <div className="sale-results">
              <p>{event.result.ongoing ? "Results so far" : "Results"} through {displayDate(event.result.through)}: {event.result.selected.count}{event.items.length ? `/${event.items.length} selected items sold` : " marketplace sales"} · {formatMoney(event.result.selected.revenue)} revenue · {event.result.selected.profit == null ? "Profit needs complete costs and fees" : `${formatMoney(event.result.selected.profit)} recorded profit`}</p>
              <p className="analytics-note">Whole marketplace: {event.result.marketplace.count} sales · {formatMoney(event.result.marketplace.revenue)} revenue{event.result.marketplace.profit == null ? " · Profit needs complete costs and fees" : ` · ${formatMoney(event.result.marketplace.profit)} recorded profit`}.</p>
              {event.result.comparison ? <p className="analytics-note">Same weekdays before the event ({displayDate(event.result.comparison_start)}–{displayDate(event.result.comparison_end)}): {event.result.comparison.count} marketplace sales · {formatMoney(event.result.comparison.revenue)} revenue{event.result.comparison.profit == null ? " · Profit unavailable" : ` · ${formatMoney(event.result.comparison.profit)} recorded profit`}.</p> : <p className="analytics-note">Comparison unavailable: {event.result.comparison_unavailable}</p>}
              {event.result.after ? <p className="analytics-note">In the {event.result.after_days} days after the event (up to 14): {event.result.after.count} marketplace sales · {formatMoney(event.result.after.revenue)} recorded revenue.</p> : null}
              {event.result.marketplace.revenue_known < event.result.marketplace.count ? <p className="analytics-note">{event.result.marketplace.count - event.result.marketplace.revenue_known} sales have no recorded price; revenue includes recorded amounts only.</p> : null}
              <p className="analytics-note">Sales during the event are associated with it; this comparison doesn’t establish that the discount caused them. Shipping uses recorded amounts.</p>
            </div> : null}
            <div className="sale-actions">
              {event.status === "planned" && event.items.length > 0 ? <>
                <button type="button" className="pr-pill" disabled={busy} onClick={() => setForm({ start: event.start_date, end: event.end_date, marketplace: event.marketplace, event })}>Edit plan</button>
                <button type="button" className="pr-pill" disabled={busy} onClick={() => statusMutation.mutate({ id: event.id, status: "ran" })}>I ran this sale</button>
              </> : event.items.length === 0 ? <button type="button" className="pr-pill" disabled={busy} onClick={() => setForm({ start: event.start_date, end: event.end_date, marketplace: event.marketplace, event, record: true })}>Edit record</button> : <button type="button" className="pr-pill" disabled={busy} onClick={() => statusMutation.mutate({ id: event.id, status: "planned" })}>Return to planned</button>}
              {event.status === "planned" ? <button type="button" className="pr-pill" disabled={busy} onClick={() => statusMutation.mutate({ id: event.id, status: "cancelled" })}>Cancel plan</button> : null}
              <button type="button" className="pr-pill" disabled={busy} onClick={() => void remove(event)}>Delete</button>
            </div>
          </article>)}
        </div>
        {form ? <SalePlanForm key={`${form.event?.id ?? "new"}-${form.marketplace}-${form.start}`} seed={form} items={query.data.items} timezone={timezone}
          onClose={() => setForm(null)} onSaved={start => { setMonth(start.slice(0, 7)); setSelectedDay(null); setForm(null); setNotice(form.record ? "Sale record saved. Results will update as you resync Vendoo." : "Plan saved. Set up the sale on the marketplace when you’re ready."); }} /> : null}
      </> : null}
    </section>
  );
}

function SalePlanForm({ seed, items, timezone, onClose, onSaved }: {
  seed: FormSeed; items: SaleCalendarItem[]; timezone: string; onClose: () => void; onSaved: (start: string) => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => { formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, []);
  const event = seed.event;
  const recording = seed.record === true;
  const [title, setTitle] = useState(event?.title ?? `${marketplaceName(seed.marketplace)} sale`);
  const [market, setMarket] = useState(seed.marketplace);
  const [start, setStart] = useState(seed.start);
  const [end, setEnd] = useState(seed.end);
  const [tz, setTz] = useState(event?.timezone ?? timezone);
  const [discount, setDiscount] = useState(event ? String(event.discount_percent ?? "") : recording ? "" : "10");
  const [fees, setFees] = useState(event?.fee_percent == null ? "" : String(event.fee_percent));
  const [shipping, setShipping] = useState(String(event?.shipping_cost ?? 0));
  const [floor, setFloor] = useState(String(event?.minimum_profit ?? 0));
  const [notes, setNotes] = useState(event?.notes ?? "");
  const [selected, setSelected] = useState<string[]>(event?.items.map(item => item.id) ?? []);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: (command: CalendarSave) => {
      if (command.kind === "record") {
        return event ? api.saleCalendar.editRecord(event.id, command.input) : api.saleCalendar.record(command.input);
      }
      return event ? api.saleCalendar.update(event.id, command.input) : api.saleCalendar.create(command.input);
    },
    onSuccess: async (_result, command) => { await Promise.all([client.invalidateQueries({ queryKey: ["sale-calendar"] }), client.invalidateQueries({ queryKey: ["analytics"] })]); onSaved(command.input.start_date); },
  });
  const available = items.filter(item => item.marketplaces.includes(market as SaleMarketplace));
  const filtered = available.filter(item => `${item.title} ${item.category}`.toLowerCase().includes(search.toLowerCase()));
  function profit(item: SaleCalendarItem) {
    return fees.trim() === "" ? null : saleProfit(item.price, item.cost, Number(discount), Number(fees), Number(shipping));
  }
  const invalid = selected.some(id => {
    const item = available.find(row => row.id === id);
    return !item || profit(item) == null || profit(item)! < Number(floor);
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!recording && (selected.length === 0 || invalid)) { setError("Choose items with recorded costs that meet your profit floor."); return; }
    if (end < start) { setError("End date must be on or after the start date."); return; }
    const common = { title, marketplace: market, start_date: start, end_date: end, timezone: tz, notes };
    if (recording) {
      save.mutate({ kind: "record", input: { ...common, discount_percent: discount.trim() ? Number(discount) : null } });
    } else {
      save.mutate({ kind: "plan", input: { ...common, marketplace: market as SaleMarketplace, discount_percent: Number(discount), fee_percent: Number(fees), shipping_cost: Number(shipping), minimum_profit: Number(floor), item_ids: selected } });
    }
  }

  return <form ref={formRef} className="sale-plan-form" onSubmit={submit} aria-label={recording ? "Record marketplace sale" : event ? "Edit sale plan" : "New sale plan"}>
    <div className="analytics-title-row"><h3>{recording ? "Record a sale you ran" : event ? "Edit sale plan" : "New sale plan"}</h3><button type="button" className="pr-pill" disabled={save.isPending} onClick={onClose}>Close</button></div>
    <fieldset disabled={save.isPending}>
      <div className="sale-form-fields">
        <label>Title<input autoFocus required maxLength={120} value={title} onChange={e => setTitle(e.target.value)} /></label>
        <label>Marketplace<select aria-label="Marketplace" value={market} onChange={e => { setMarket(e.target.value as SaleMarketplace); setSelected([]); }}>{!MARKETS.includes(market as SaleMarketplace) ? <option value={market}>{marketplaceName(market)}</option> : null}{MARKETS.map(value => <option key={value} value={value}>{marketplaceName(value)}</option>)}</select></label>
        <label>Start date<input type="date" required value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>End date (inclusive)<input type="date" required min={start} value={end} onChange={e => setEnd(e.target.value)} /></label>
        <label>Event time zone<input required value={tz} onChange={e => setTz(e.target.value)} /></label>
        <label>Discount (%)<input type="number" required={!recording} min={recording ? 0 : 5} max={recording ? 95 : 75} step="0.1" value={discount} onChange={e => setDiscount(e.target.value)} /></label>
        {!recording ? <>
        <label>Estimated effective fees (%)<input type="number" required min={0} max={50} step="0.1" placeholder="Include ads and processing" value={fees} onChange={e => setFees(e.target.value)} /></label>
        <label>Seller shipping per item ($)<input type="number" required min={0} max={10000} step="0.01" value={shipping} onChange={e => setShipping(e.target.value)} /></label>
        <label>Minimum estimated profit per item ($)<input type="number" required min={0} max={100000} step="0.01" value={floor} onChange={e => setFloor(e.target.value)} /></label>
        </> : null}
      </div>
      {!recording ? <>
      <p className="analytics-note">Profit estimate = discounted price minus estimated effective fees, item cost, and seller shipping. Enter your own fees, including ads and processing, and any shipping you cover. This is a planning estimate, not a guaranteed margin. Missing costs and items below your floor cannot be included.</p>
      <label className="sale-search">Choose active items ({selected.length} selected)<input type="search" placeholder="Search title or category" value={search} onChange={e => setSearch(e.target.value)} /></label>
      <div className="sale-item-picker">
        {filtered.map(item => {
          const estimate = profit(item);
          const blocked = estimate == null || estimate < Number(floor);
          return <label className="sale-item" key={item.id}><input type="checkbox" disabled={blocked && !selected.includes(item.id)} checked={selected.includes(item.id)} onChange={e => setSelected(e.target.checked ? [...selected, item.id] : selected.filter(id => id !== item.id))} />
            <span>{item.title}<small>{item.category}{item.listed_at ? ` · Listed ${displayDate(item.listed_at.slice(0, 10))}` : ""}</small></span>
            <span>{item.cost == null ? "Add a cost first" : estimate == null ? "Enter fees first" : `${formatMoney(estimate)} estimated profit`}{estimate != null && estimate < Number(floor) ? <small>Below your floor</small> : null}</span>
          </label>;
        })}
        {filtered.length === 0 ? <p className="analytics-note">No matching active items with a recorded listing on {marketplaceName(market)}. Refresh your Vendoo import if needed.</p> : null}
      </div>
      {invalid ? <p className="sale-error">Some selected items are unavailable or no longer meet your profit floor. Remove them or adjust your plan.</p> : null}
      {selected.filter(id => !available.some(item => item.id === id)).map(id => <button key={id} type="button" className="pr-pill" onClick={() => setSelected(selected.filter(value => value !== id))}>Remove unavailable item: {event?.items.find(item => item.id === id)?.title ?? id}</button>)}
      </> : <p className="analytics-note">Records associate all sales on this marketplace during these dates with the event. Record the dates you actually ran it; a discount is optional.</p>}
      <label className="sale-search">Notes<textarea maxLength={2000} rows={3} value={notes} onChange={e => setNotes(e.target.value)} /></label>
      {error || save.isError ? <p className="sale-error" role="alert">{error || save.error?.message}</p> : null}
      <button type="submit" className="pr-pill" disabled={save.isPending || (!recording && (selected.length === 0 || invalid))}>{save.isPending ? "Saving…" : recording ? "Save record" : "Save plan"}</button>
    </fieldset>
  </form>;
}
