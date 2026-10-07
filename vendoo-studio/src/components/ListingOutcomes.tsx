import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { EngagementOutcome, ListingEvidence, ShippingOutcome } from "../api/types";
import { marketplaceName } from "./marketplaceNames";

const today = () => new Date().toISOString().slice(0, 10);
const optionalNumber = (data: FormData, name: string): number | null => {
  const value = String(data.get(name) ?? "").trim();
  return value === "" ? null : Number(value);
};
const counts = ["impressions", "views", "offers", "returns"] as const;
const shippingFields = [
  ["packed_weight_oz", "Packed weight (oz)", true], ["length_in", "Length (in)", false],
  ["width_in", "Width (in)", false], ["height_in", "Height (in)", false], ["postage_paid", "Postage paid ($)", false],
] as const;

export function ListingOutcomes({ convId }: { convId: string }) {
  const [open, setOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<EngagementOutcome | null>(null);
  const [saved, setSaved] = React.useState("");
  const client = useQueryClient();
  const queryKey = ["listing-evidence", convId];
  const { data, error, isFetching } = useQuery({ queryKey, queryFn: () => api.evidence.get(convId), enabled: open });
  const remember = (value: ListingEvidence, message: string) => {
    client.setQueryData(queryKey, value);
    setSaved(message);
  };
  const shipping = useMutation({
    mutationFn: (value: ShippingOutcome | null) => api.evidence.shipping(convId, value),
    onSuccess: (value) => remember(value, "Shipping saved."),
  });
  const engagement = useMutation({
    mutationFn: (value: EngagementOutcome) => api.evidence.engagement(convId, value),
    onSuccess: (value) => { remember(value, "Buyer response saved."); setEditing(null); },
  });
  const remove = useMutation({
    mutationFn: (value: EngagementOutcome) => api.evidence.removeEngagement(convId, value),
    onSuccess: (value) => { remember(value, "Report removed."); setEditing(null); },
  });
  const saveShipping = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaved("");
    const values = new FormData(event.currentTarget);
    shipping.mutate({ shipped_on: String(values.get("shipped_on")), packed_weight_oz: Number(values.get("packed_weight_oz")),
      length_in: optionalNumber(values, "length_in"), width_in: optionalNumber(values, "width_in"),
      height_in: optionalNumber(values, "height_in"), postage_paid: optionalNumber(values, "postage_paid"), currency: "USD" });
  };
  const saveEngagement = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaved("");
    const values = new FormData(event.currentTarget);
    engagement.mutate({ marketplace: String(values.get("marketplace")), start_date: String(values.get("start_date")),
      end_date: String(values.get("end_date")), impressions: optionalNumber(values, "impressions"),
      views: optionalNumber(values, "views"), offers: optionalNumber(values, "offers"), returns: optionalNumber(values, "returns"),
      return_reason: (String(values.get("return_reason") || "") || null) as EngagementOutcome["return_reason"] });
  };
  const problem = error || shipping.error || engagement.error || remove.error;
  return (
    <details className="listing-outcomes" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Shipping and buyer response</summary>
      {open && <div className="listing-outcomes-body">
        <p className="text-sm text-muted">Record measured shipping and counts from your marketplace reports. Generation uses these records as evidence. Leave anything unknown empty.</p>
        {problem && <p role="alert" className="text-error">{problem.message}</p>}
        {saved && <p role="status">{saved}</p>}
        {isFetching && !data ? <p>Loading records…</p> : data && <>
          <form onSubmit={saveShipping} key={data.shipping?.recorded_at || "unmeasured"}>
            <fieldset disabled={shipping.isPending}>
              <legend>Measured packed shipping</legend>
              <div className="listing-outcomes-grid">
                <label>Shipment date<input className="input" name="shipped_on" type="date" max={today()} defaultValue={data.shipping?.shipped_on || today()} required /></label>
                {shippingFields.map(([name, label, required]) => <label key={name}>{label}<input className="input" name={name} type="number" min={name === "postage_paid" ? 0 : 0.01} step="0.01" required={required} defaultValue={data.shipping?.[name] ?? ""} /></label>)}
              </div>
              <p className="text-xs text-muted">Weigh the packed shipment. Enter all three dimensions together, if measured.</p>
              <button type="submit" className="btn btn-secondary btn-sm">{shipping.isPending ? "Saving…" : "Save measured shipping"}</button>
              {data.shipping && <button type="button" className="btn btn-ghost btn-sm" onClick={() => shipping.mutate(null)}>Remove measurement</button>}
            </fieldset>
          </form>
          <form onSubmit={saveEngagement} key={editing ? `${editing.marketplace}:${editing.start_date}:${editing.end_date}` : data.engagement.map((entry) => entry.recorded_at).join(",")}>
            <fieldset disabled={engagement.isPending}>
              <legend>{editing ? "Edit buyer-response report" : "Buyer-response report"}</legend>
              <div className="listing-outcomes-grid">
                <label>Marketplace<select className="input" name="marketplace" disabled={Boolean(editing)} defaultValue={editing?.marketplace || "ebay"}>{["ebay", "etsy", "poshmark", "mercari", "depop", "grailed"].map((market) => <option key={market} value={market}>{marketplaceName(market)}</option>)}</select>{editing && <input type="hidden" name="marketplace" value={editing.marketplace} />}</label>
                <label>Period starts<input className="input" name="start_date" type="date" readOnly={Boolean(editing)} max={today()} defaultValue={editing?.start_date || today()} required /></label>
                <label>Period ends<input className="input" name="end_date" type="date" readOnly={Boolean(editing)} max={today()} defaultValue={editing?.end_date || today()} required /></label>
                {counts.map((name) => <label key={name}>{name[0].toUpperCase() + name.slice(1)}<input className="input" name={name} type="number" min="0" step="1" defaultValue={editing?.[name] ?? ""} /></label>)}
                <label>Return reason<select className="input" name="return_reason" defaultValue={editing?.return_reason || ""}><option value="">Unknown / no return</option><option value="fit">Fit</option><option value="description">Description mismatch</option><option value="damage">Damage</option><option value="changed_mind">Changed mind</option><option value="other">Other</option></select></label>
              </div>
              <p className="text-xs text-muted">Use counts for this listing and this reporting period. Enter 0 only when the report shows zero. Overlapping periods stay separate.</p>
              <button type="submit" className="btn btn-secondary btn-sm">{engagement.isPending ? "Saving…" : "Save report"}</button>
              {editing && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel edit</button>}
            </fieldset>
          </form>
          {data.engagement.length > 0 && <ul className="listing-outcomes-reports">{[...data.engagement].sort((a, b) => b.end_date.localeCompare(a.end_date)).map((entry) => <li key={`${entry.marketplace}:${entry.start_date}:${entry.end_date}`}>
            <span>{marketplaceName(entry.marketplace)} · {entry.start_date} – {entry.end_date}<br />{counts.filter((key) => entry[key] !== null).map((key) => `${entry[key]} ${key}`).join(" · ")}</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(entry)}>Edit</button><button type="button" className="btn btn-ghost btn-sm" disabled={remove.isPending} onClick={() => remove.mutate(entry)}>Remove</button>
          </li>)}</ul>}
          <p className="text-xs text-muted">{data.sale_snapshots.length ? `${data.sale_snapshots.length} sale snapshot${data.sale_snapshots.length === 1 ? "" : "s"} preserved from Vendoo. Captured when Studio first observed the sale.` : "Studio preserves a sale snapshot when Vendoo sync first reports a dated sale."}</p>
        </>}
      </div>}
    </details>
  );
}
