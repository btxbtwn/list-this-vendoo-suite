import { useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ScoutBox, ScoutResponse } from "../api/types";
import { addToast } from "../ui/toast";
import { formatMoney } from "./analyticsFormat";
import {
  DEFAULT_SCOUT_FILTERS,
  GRADE_LABELS,
  SCOUT_PRESETS,
  activePreset,
  normalizeTrend,
  scoutQuery,
  type ScoutFilters,
} from "./boxScout";

export function SourcingPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<ScoutFilters>(DEFAULT_SCOUT_FILTERS);
  const [trendDraft, setTrendDraft] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const queryKey = ["sourcing", "raghouse", scoutQuery(filters)];
  const query = useQuery({
    queryKey,
    queryFn: () => api.sourcing.raghouse(scoutQuery(filters)),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
  const data = query.data;
  const preset = activePreset(filters);

  const update = (patch: Partial<ScoutFilters>) => setFilters((current) => ({ ...current, ...patch }));
  const commitTrend = () => {
    const trend = normalizeTrend(trendDraft);
    setTrendDraft(trend);
    if (trend !== filters.trend) update({ trend });
  };
  const refresh = async () => {
    setRefreshing(true);
    try {
      queryClient.setQueryData(queryKey, await api.sourcing.raghouse(scoutQuery(filters, true)));
    } catch (error) {
      addToast({ type: "error", title: "Could not refresh Raghouse", description: (error as Error).message });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="analytics-page">
      <div className="analytics-inner">
        <header className="analytics-header">
          <p className="analytics-lead">
            Clothing boxes on raghouse.com, ranked by what they cost landed in{" "}
            {data?.shipping.destination_zip ?? "70115"} per usable piece and by how fast boxes like them sell out.
          </p>
          <div className="pr-pills" role="tablist" aria-label="Box type">
            {SCOUT_PRESETS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={preset === item.id}
                className={`pr-pill${preset === item.id ? " is-active" : ""}`}
                onClick={() => update(item.filters)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="sourcing-filters">
            <label className="sourcing-field sourcing-field-wide">
              <span className="label">Trending words</span>
              <input
                className="input"
                type="text"
                placeholder="carhartt, y2k, cartoon"
                value={trendDraft}
                onChange={(event) => setTrendDraft(event.target.value)}
                onBlur={commitTrend}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commitTrend();
                }}
              />
            </label>
            <NumberField label="Min pieces" value={filters.minPcs} min={1} step={1} onChange={(minPcs) => update({ minPcs })} />
            <NumberField
              label="Good $ / usable pc"
              value={filters.targetCog}
              min={0.25}
              step={0.25}
              onChange={(targetCog) => update({ targetCog })}
            />
            <NumberField
              label="Max $ / usable pc"
              value={filters.maxCog}
              min={0.25}
              step={0.25}
              onChange={(maxCog) => update({ maxCog })}
            />
            <NumberField
              label="Max box price"
              value={filters.maxPrice}
              min={0}
              step={5}
              placeholder="Any"
              onChange={(maxPrice) => update({ maxPrice })}
            />
          </div>
          <div className="sourcing-toolbar">
            <label className="sourcing-check">
              <input
                type="checkbox"
                checked={filters.includeVip}
                onChange={(event) => update({ includeVip: event.target.checked })}
              />
              Include VIP-only boxes
            </label>
            <button type="button" className="btn btn-sm btn-ghost" onClick={refresh} disabled={refreshing}>
              {refreshing ? "Checking Raghouse…" : "Check for new boxes"}
            </button>
          </div>
        </header>

        {query.isLoading && !data ? <p className="analytics-status">Reading the Raghouse catalog…</p> : null}
        {query.isError ? (
          <p className="analytics-status">{(query.error as Error).message || "Could not load Raghouse boxes."}</p>
        ) : null}

        {data ? (
          <section className="analytics-section" aria-label="Boxes">
            <h2 className="analytics-section-title">{summary(data)}</h2>
            {data.boxes.length === 0 ? (
              <p className="analytics-note">
                No boxes match. Raise the max $ per usable piece or lower the minimum pieces.
              </p>
            ) : (
              <ol className="sourcing-boxes">
                {data.boxes.map((box) => (
                  <BoxRow key={box.url} box={box} days={data.sellout_days} />
                ))}
              </ol>
            )}
            <p className="analytics-note sourcing-footnote">{shippingNote(data)}</p>
          </section>
        ) : null}
      </div>
    </div>
  );
}

function BoxRow({ box, days }: { box: ScoutBox; days: number }) {
  const meta = [GRADE_LABELS[box.grade], `${box.pcs} pcs`, `${box.lbs} lb`];
  if (box.vip) meta.push("VIP only");
  return (
    <li>
      <a className="sourcing-box" href={box.url} target="_blank" rel="noopener noreferrer">
        <span className="sourcing-box-main">
          <span className="sourcing-box-title">{box.title}</span>
          <span className="sourcing-box-meta">
            {meta.join(" · ")}
            {box.trend_hits.length ? <span className="sourcing-box-trend"> · {box.trend_hits.join(", ")}</span> : null}
          </span>
        </span>
        <span className="sourcing-box-cost">
          <span className="sourcing-box-value">{formatMoney(box.cog_per_usable_pc)} / usable pc</span>
          <span className="sourcing-box-meta">
            {formatMoney(box.price)}
            {box.compare_at ? ` (was ${formatMoney(box.compare_at)})` : ""} + {formatMoney(Math.round(box.ship_est))} ship ={" "}
            {formatMoney(Math.round(box.landed))}
          </span>
        </span>
        <span
          className={`sourcing-box-demand${box.demand >= 1.2 ? " is-hot" : ""}`}
          title={`Boxes like this sold out ${box.demand.toFixed(2)}× as often as the store average over the last ${days} days.`}
        >
          {box.demand.toFixed(1)}×
        </span>
      </a>
    </li>
  );
}

function NumberField({
  label,
  value,
  min,
  step,
  placeholder,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  step: number;
  placeholder?: string;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState(value ? String(value) : "");
  const [shown, setShown] = useState(value);
  if (shown !== value) {
    // A preset changed the value from outside this field.
    setShown(value);
    setDraft(value ? String(value) : "");
  }
  return (
    <label className="sourcing-field">
      <span className="label">{label}</span>
      <input
        className="input"
        type="number"
        inputMode="decimal"
        min={min}
        step={step}
        placeholder={placeholder}
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          const next = event.target.value === "" ? 0 : Number(event.target.value);
          if (Number.isFinite(next) && next >= min) {
            setShown(next);
            onChange(next);
          }
        }}
      />
    </label>
  );
}

function summary(data: ScoutResponse): string {
  const fetched = new Date(data.fetched_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const count = data.matched === 1 ? "1 box matches" : `${data.matched} boxes match`;
  const shown = data.boxes.length < data.matched ? `, top ${data.boxes.length} shown` : "";
  return `${count}${shown} · checked ${fetched}`;
}

function shippingNote(data: ScoutResponse): string {
  const s = data.shipping;
  const calibrated = s.ship_factor === 1 ? "" : ` Adjusted ×${s.ship_factor} to match real checkout quotes.`;
  return (
    `Shipping is the UPS Ground list price to ${s.destination_zip} (zone ${s.zone}) for each box's listed weight, ` +
    `plus ${formatMoney(s.residential_surcharge)} home delivery and ${s.fuel_surcharge_pct}% fuel ` +
    `(as of ${s.fuel_surcharge_as_of}). Raghouse quotes discounted rates at checkout, so expect to ` +
    `pay less.${calibrated} Usable pieces count 90% of a box, 75% of a Recycle & Good box and 60% of a ` +
    `Recycle box. Demand compares how often similar boxes sold out over the last ${data.sellout_days} days ` +
    `with Raghouse's ${Math.round(data.baseline_sellout * 100)}% average.`
  );
}
