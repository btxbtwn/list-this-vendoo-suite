/** Vendoo Inventory's filter bar, sized for Studio's sidebar. */

import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { MarketplaceLogo } from "./MarketplaceLogo";
import { marketplaceLabel } from "./fillLogForms";
import {
  DEFAULT_LISTING_FILTERS,
  LISTING_SORTS,
  LISTING_STATUS_TABS,
  STALE_DAY_OPTIONS,
  activeFilterCount,
  compactCount,
  toggleValue,
  type ListingFilters as Filters,
  type ListingSortId,
  type ListingStatusFilter,
} from "./inventoryFilters";

const STATUS_LABELS: Record<string, string> = {
  all: "All",
  draft: "Draft",
  active: "Active",
  sold: "Sold",
  failed: "Failed",
};

function CheckGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8.5l3.5 3.5L13 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** One narrowing, as a checkable menu row: check, glyph, name, count. */
function FilterRow({
  checked,
  disabled,
  title,
  count,
  glyph,
  label,
  onSelect,
}: {
  checked: boolean;
  disabled?: boolean;
  title?: string;
  count: number;
  glyph: ReactNode;
  label: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={checked}
      className="listing-filter-row"
      disabled={disabled}
      title={title}
      onClick={onSelect}
    >
      <span className="listing-filter-row-check" aria-hidden="true">
        {checked ? <CheckGlyph /> : null}
      </span>
      {glyph}
      <span className="listing-filter-row-text">{label}</span>
      <span className="listing-filter-row-count">{count}</span>
    </button>
  );
}

export function ListingFilters({
  filters,
  counts,
  labels,
  labelCounts,
  marketplaces,
  marketplaceCounts,
  notListedCount,
  staleCounts,
  onChange,
}: {
  filters: Filters;
  counts: Record<string, number>;
  labels: string[];
  /** Label counts, keyed lowercase the way `labelCounts` returns them. */
  labelCounts: Record<string, number>;
  marketplaces: string[];
  marketplaceCounts: Record<string, number>;
  notListedCount: number;
  /** How many listings each staleness cutoff would keep, keyed by its days. */
  staleCounts: Record<number, number>;
  onChange: (next: Filters) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const chosen = activeFilterCount(filters);
  // Vendoo hides the tab it has nothing for; "failed" is Studio's own state.
  const tabs: ListingStatusFilter[] = [
    "all",
    ...LISTING_STATUS_TABS.filter((status) => status !== "failed" || counts.failed),
  ];

  // The menu closes the way every other menu in Studio does, and hands the
  // focus back to the button that opened it.
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>(".listing-filter-row:not(:disabled)")?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  /** Arrow keys walk the rows, the way a menu is expected to. */
  const moveFocus = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
    if (!keys.includes(event.key)) return;
    const rows = [...(menu.current?.querySelectorAll<HTMLButtonElement>(".listing-filter-row:not(:disabled)") || [])];
    if (!rows.length) return;
    event.preventDefault();
    const here = rows.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? rows.length - 1
          : event.key === "ArrowDown"
            ? (here + 1) % rows.length
            : (here <= 0 ? rows.length : here) - 1;
    rows[next]?.focus();
  };

  return (
    <div className="listing-filters" ref={root}>
      <div className="listing-filter-tabs" role="tablist" aria-label="Listing status">
        {tabs.map((status) => (
          <button
            key={status}
            type="button"
            role="tab"
            aria-selected={filters.status === status}
            className={`listing-filter-tab${filters.status === status ? " selected" : ""}`}
            // A narrow sidebar drops the counts, so the tab itself carries one.
            title={`${STATUS_LABELS[status]} · ${counts[status] || 0}`}
            onClick={() => onChange({ ...filters, status })}
          >
            <span className="listing-filter-tab-inner">
              <span className="listing-filter-tab-label">{STATUS_LABELS[status]}</span>
              <span className="listing-filter-tab-count">{compactCount(counts[status] || 0)}</span>
            </span>
          </button>
        ))}
      </div>

      <div className="listing-filter-controls">
        <div className="listing-filter-menu-wrap">
          <button
            ref={trigger}
            type="button"
            className={`listing-filter-toggle${open ? " open" : ""}${chosen ? " active" : ""}`}
            aria-expanded={open}
            aria-haspopup="menu"
            onClick={() => setOpen((value) => !value)}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M2 4h12M4 8h8M6.5 12h3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            <span>Filters</span>
            {chosen ? <span className="listing-filter-badge">{chosen}</span> : null}
          </button>

          {open ? (
            <div
              ref={menu}
              className="listing-filter-menu"
              role="menu"
              aria-label="Filter listings"
              onKeyDown={moveFocus}
            >
              <span className="listing-filter-menu-label">Marketplaces</span>
              {marketplaces.length ? (
                marketplaces.map((id) => (
                  <FilterRow
                    key={id}
                    checked={filters.marketplaces.includes(id)}
                    // "Not listed" asks the opposite question, so it takes the
                    // marketplaces over rather than fighting them.
                    disabled={filters.notListed}
                    title={filters.notListed ? "Turn off Not listed to pick marketplaces" : undefined}
                    count={marketplaceCounts[id] || 0}
                    glyph={<MarketplaceLogo id={id} label={marketplaceLabel(id)} size={14} />}
                    label={marketplaceLabel(id)}
                    onSelect={() => onChange({ ...filters, marketplaces: toggleValue(filters.marketplaces, id) })}
                  />
                ))
              ) : (
                <span className="listing-filter-empty">Nothing listed yet</span>
              )}
              <span className="listing-filter-menu-sep" role="separator" />
              <FilterRow
                checked={filters.notListed}
                count={notListedCount}
                glyph={<span className="listing-filter-row-dot" aria-hidden="true" />}
                label="Not listed"
                onSelect={() => onChange({ ...filters, notListed: !filters.notListed })}
              />

              <span className="listing-filter-menu-sep" role="separator" />
              <span className="listing-filter-menu-label">Stale since listed</span>
              {STALE_DAY_OPTIONS.map((days) => (
                <FilterRow
                  key={days}
                  checked={filters.staleDays === days}
                  count={staleCounts[days] || 0}
                  glyph={<span className="listing-filter-row-dot" aria-hidden="true" />}
                  label={`${days}+ days`}
                  // One cutoff at a time: picking the one already on turns it off.
                  onSelect={() => onChange({ ...filters, staleDays: filters.staleDays === days ? 0 : days })}
                />
              ))}

              {labels.length ? (
                <>
                  <span className="listing-filter-menu-sep" role="separator" />
                  <span className="listing-filter-menu-label">Vendoo labels</span>
                  {labels.map((label) => (
                    <FilterRow
                      key={label}
                      checked={filters.labels.includes(label)}
                      count={labelCounts[label.toLowerCase()] || 0}
                      glyph={<span className="listing-filter-row-dot" aria-hidden="true" />}
                      label={label}
                      onSelect={() => onChange({ ...filters, labels: toggleValue(filters.labels, label) })}
                    />
                  ))}
                </>
              ) : null}

              {chosen ? (
                <>
                  <span className="listing-filter-menu-sep" role="separator" />
                  <button
                    type="button"
                    role="menuitem"
                    className="listing-filter-row is-clear"
                    onClick={() => {
                      onChange({ ...DEFAULT_LISTING_FILTERS, sort: filters.sort });
                      close();
                    }}
                  >
                    <span className="listing-filter-row-check" aria-hidden="true" />
                    <span className="listing-filter-row-text">Clear filters</span>
                  </button>
                </>
              ) : null}
            </div>
          ) : null}
        </div>

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
    </div>
  );
}
