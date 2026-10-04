import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SaleEvent, SaleEventInput } from "../api/types";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";
import { formatMoney } from "./analyticsFormat";
import { marketplaceName } from "./marketplaceNames";
import {
  DEFAULT_EVENT_DISCOUNT,
  EVENT_MARKETPLACES,
  SALE_EVENTS_QUERY_KEY,
  eventDates,
  eventLift,
  eventMarketplaces,
} from "./saleEventFormat";

/**
 * Marketplace sale events the seller joined. A sale on one of the event's
 * marketplaces during its days counts as an event sale, so nothing is tagged by
 * hand; each event shows its pace against the weeks before and after it.
 */
export function SaleEvents({ onOpenListing }: { onOpenListing: (id: string) => void }) {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: SALE_EVENTS_QUERY_KEY, queryFn: api.saleEvents.list });
  const onSaved = (data: { events: SaleEvent[] }) => {
    queryClient.setQueryData(SALE_EVENTS_QUERY_KEY, data);
    // Recent sales on the Analytics page carry the event they fell in.
    void queryClient.invalidateQueries({ queryKey: ["analytics"] });
  };
  const onError = (error: Error) =>
    addToast({ type: "error", title: "Could not save the sale event", description: error.message });
  const create = useMutation({ mutationFn: api.saleEvents.create, onSuccess: onSaved, onError });
  const remove = useMutation({ mutationFn: api.saleEvents.remove, onSuccess: onSaved, onError });
  const [adding, setAdding] = useState(false);
  const events = query.data?.events ?? [];

  const onRemove = async (event: SaleEvent) => {
    const ok = await confirmDialog(`Remove “${event.name}”? Its sales stay; they just won't count as event sales.`, {
      variant: "destructive",
      confirmLabel: "Remove event",
    });
    if (ok) remove.mutate(event.id);
  };

  return (
    <section className="analytics-section" aria-label="Sale events">
      <div className="analytics-title-row">
        <h2 className="analytics-section-title">Sale events</h2>
        {!adding ? (
          <button type="button" className="sourcing-link analytics-title-link" onClick={() => setAdding(true)}>Add an event</button>
        ) : null}
      </div>
      <p className="analytics-note">
        Add each marketplace sale you join. Sales on those marketplaces during its days count toward it, and its pace
        is set against the 4 weeks before and the 2 weeks after.
      </p>
      {adding ? (
        <AddEventForm
          saving={create.isPending}
          onCancel={() => setAdding(false)}
          onSave={(input) => create.mutate(input, { onSuccess: () => setAdding(false) })}
        />
      ) : null}
      {query.isError ? <p className="analytics-note">{(query.error as Error).message}</p> : null}
      {query.data && events.length === 0 && !adding ? <p className="analytics-note">No sale events yet.</p> : null}
      {events.length ? (
        <ul className="analytics-recent analytics-events">
          {events.map((event) => (
            <li key={event.id}>
              <details className="analytics-age-group">
                <summary className="analytics-rank">
                  <span className="analytics-rank-label">
                    {event.name}
                    {event.status === "running" ? <span className="analytics-event-live"> · On now</span> : null}
                  </span>
                  <span className="analytics-age-count">
                    {eventDates(event)} · {eventMarketplaces(event.marketplaces)}
                    {event.discount_percent ? ` · ${event.discount_percent}% off` : ""}
                  </span>
                  <span className="analytics-rank-value">
                    {event.sold === 1 ? "1 sale" : `${event.sold} sales`} · {formatMoney(event.revenue)}
                  </span>
                </summary>
                <div className="analytics-event-body">
                  <p className="analytics-note">{eventLift(event)}</p>
                  {event.sales.length ? (
                    <ul className="analytics-recent">
                      {event.sales.map((sale) => (
                        <li key={sale.conversation_id}>
                          <button type="button" className="analytics-recent-row" onClick={() => onOpenListing(sale.conversation_id)}>
                            <span className="analytics-recent-title">{sale.title}</span>
                            <span className="analytics-recent-meta">{marketplaceName(sale.marketplace)}</span>
                            <span className="analytics-recent-price">
                              {sale.price == null ? "Price unknown" : formatMoney(sale.price)}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <button type="button" className="sourcing-link analytics-title-link" onClick={() => void onRemove(event)}>
                    Remove
                  </button>
                </div>
              </details>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function AddEventForm({
  saving,
  onCancel,
  onSave,
}: {
  saving: boolean;
  onCancel: () => void;
  onSave: (event: SaleEventInput) => void;
}) {
  const [name, setName] = useState("");
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [discount, setDiscount] = useState(String(DEFAULT_EVENT_DISCOUNT));
  const [marketplaces, setMarketplaces] = useState<string[]>([...EVENT_MARKETPLACES]);
  const percent = Number(discount);
  const valid =
    name.trim() && startsOn && endsOn && endsOn >= startsOn && marketplaces.length > 0 &&
    (discount === "" || (percent >= 1 && percent <= 90));
  const toggle = (market: string) =>
    setMarketplaces((current) =>
      current.includes(market) ? current.filter((item) => item !== market) : [...current, market],
    );
  return (
    <form
      className="bought-add"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || saving) return;
        onSave({
          name: name.trim(),
          starts_on: startsOn,
          ends_on: endsOn,
          marketplaces,
          discount_percent: discount ? percent : null,
        });
      }}
    >
      <label className="bought-add-field is-wide">
        <span className="label">Event</span>
        <input
          className="input input-sm"
          placeholder="Black Friday sale"
          value={name}
          onChange={(event) => setName(event.target.value)}
          autoFocus
        />
      </label>
      <label className="bought-add-field analytics-event-date">
        <span className="label">First day</span>
        <input
          className="input input-sm"
          type="date"
          value={startsOn}
          onChange={(event) => {
            setStartsOn(event.target.value);
            if (!endsOn || endsOn < event.target.value) setEndsOn(event.target.value);
          }}
        />
      </label>
      <label className="bought-add-field analytics-event-date">
        <span className="label">Last day</span>
        <input
          className="input input-sm"
          type="date"
          value={endsOn}
          min={startsOn || undefined}
          onChange={(event) => setEndsOn(event.target.value)}
        />
      </label>
      <label className="bought-add-field">
        <span className="label">% off</span>
        <input
          className="input input-sm"
          inputMode="numeric"
          value={discount}
          onChange={(event) => setDiscount(event.target.value.replace(/\D/g, ""))}
        />
      </label>
      <div className="bought-add-field analytics-event-markets" role="group" aria-labelledby="sale-event-markets">
        <span className="label" id="sale-event-markets">Marketplaces</span>
        <div className="analytics-event-market-list">
          {EVENT_MARKETPLACES.map((market) => (
            <label key={market} className="analytics-event-market">
              <input type="checkbox" checked={marketplaces.includes(market)} onChange={() => toggle(market)} />
              {marketplaceName(market)}
            </label>
          ))}
        </div>
      </div>
      <div className="bought-add-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn btn-primary btn-sm" disabled={!valid || saving}>Add event</button>
      </div>
    </form>
  );
}
