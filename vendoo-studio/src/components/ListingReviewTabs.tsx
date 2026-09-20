import type { MouseEvent } from "react";

export type ListingReviewTab = "input" | "forms" | "fields";

const TABS: { id: ListingReviewTab; label: string }[] = [
  { id: "input", label: "Input" },
  { id: "forms", label: "Forms" },
  { id: "fields", label: "Fields" },
];

/** Input / Forms / Fields — same pill chrome as the inventory status tabs. */
export function ListingReviewTabs({
  value,
  onChange,
  className,
  onMouseDown,
}: {
  value: ListingReviewTab;
  onChange: (tab: ListingReviewTab) => void;
  className?: string;
  onMouseDown?: (event: MouseEvent<HTMLElement>) => void;
}) {
  return (
    <div
      className={`listing-filter-tabs listing-review-tabs${className ? ` ${className}` : ""}`}
      role="tablist"
      aria-label="Listing review"
      onMouseDown={onMouseDown}
    >
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={value === tab.id}
          className={`listing-filter-tab${value === tab.id ? " selected" : ""}`}
          onClick={() => onChange(tab.id)}
        >
          <span className="listing-filter-tab-inner">
            <span className="listing-filter-tab-label">{tab.label}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
