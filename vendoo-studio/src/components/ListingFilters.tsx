/** Vendoo Inventory's filter bar, sized for Studio's sidebar. */

import { useState } from "react";
import { MarketplaceLogo } from "./MarketplaceLogo";
import { marketplaceLabel } from "./fillLogForms";
import {
  DEFAULT_LISTING_FILTERS,
  LISTING_SORTS,
  LISTING_STATUS_TABS,
  activeFilterCount,
  toggleValue,
  type ListingFilters as Filters,
  type ListingSortId,
  type ListingStatusFilter,
} from "./listingFilters";

const STATUS_LABELS: Record<string, string> = {
  all: "All",
  draft: "Draft",
  active: "Active",
  sold: "Sold",
  failed: "Failed",
};

export function ListingFilters({
  filters,
  counts,
  labels,
  marketplaces,
  onChange,
}: {
  filters: Filters;
  counts: Record<string, number>;
  labels: string[];
  marketplaces: string[];
  onChange: (next: Filters) => void;
}) {
  const [open, setOpen] = useState(false);
  const chosen = activeFilterCount(filters);
  // Vendoo hides the tab it has nothing for; "failed" is Studio's own state.
  const tabs: ListingStatusFilter[] = [
    "all",
    ...LISTING_STATUS_TABS.filter((status) => status !== "failed" || counts.failed),
  ];

  return (
    <div className="listing-filters">
      <div className="listing-filter-tabs" role="tablist" aria-label="Listing status">
        {tabs.map((status) => (
          <button
            key={status}
            type="button"
            role="tab"
            aria-selected={filters.status === status}
            className={`listing-filter-tab${filters.status === status ? " selected" : ""}`}
            onClick={() => onChange({ ...filters, status })}
          >
            {STATUS_LABELS[status]}
            <span className="listing-filter-tab-count">{counts[status] || 0}</span>
          </button>
        ))}
      </div>

      <div className="listing-filter-controls">
        <button
          type="button"
          className={`listing-filter-toggle${open ? " open" : ""}`}
          aria-expanded={open}
          aria-controls="listing-filter-panel"
          onClick={() => setOpen((value) => !value)}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M2 4h12M4 8h8M6.5 12h3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          <span>Filters</span>
          {chosen ? <span className="listing-filter-badge">{chosen}</span> : null}
        </button>
        <select
          className="listing-filter-sort"
          value={filters.sort}
          aria-label="Sort listings"
          onChange={(event) => onChange({ ...filters, sort: event.target.value as ListingSortId })}
        >
          {LISTING_SORTS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {open ? (
        <div className="listing-filter-panel" id="listing-filter-panel">
          <div className="listing-filter-group">
            <span className="listing-filter-group-label">Marketplaces</span>
            {marketplaces.length ? (
              <div className="listing-filter-chips">
                {marketplaces.map((id) => {
                  const selected = filters.marketplaces.includes(id);
                  return (
                    <button
                      key={id}
                      type="button"
                      className={`listing-filter-logo${selected ? " selected" : ""}`}
                      aria-pressed={selected}
                      title={marketplaceLabel(id)}
                      disabled={filters.notListed}
                      onClick={() => onChange({ ...filters, marketplaces: toggleValue(filters.marketplaces, id) })}
                    >
                      <MarketplaceLogo id={id} label={marketplaceLabel(id)} size={18} />
                    </button>
                  );
                })}
              </div>
            ) : (
              <span className="listing-filter-empty">Nothing listed yet</span>
            )}
          </div>

          <label className="listing-filter-check">
            <input
              type="checkbox"
              checked={filters.notListed}
              onChange={(event) => onChange({ ...filters, notListed: event.target.checked })}
            />
            <span>View not listed</span>
          </label>

          {labels.length ? (
            <div className="listing-filter-group">
              <span className="listing-filter-group-label">Vendoo labels</span>
              <div className="listing-filter-chips">
                {labels.map((label) => {
                  const selected = filters.labels.includes(label);
                  return (
                    <button
                      key={label}
                      type="button"
                      className={`listing-filter-chip${selected ? " selected" : ""}`}
                      aria-pressed={selected}
                      onClick={() => onChange({ ...filters, labels: toggleValue(filters.labels, label) })}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {chosen ? (
            <button
              type="button"
              className="listing-filter-clear"
              onClick={() => onChange({ ...DEFAULT_LISTING_FILTERS, sort: filters.sort })}
            >
              Clear filters
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
