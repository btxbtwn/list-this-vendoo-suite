import React, { useCallback, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { UpdateButton } from "./UpdateButton";

const SETTLED_SHELF_KEY = "vendoo-studio.settled-expanded";
const SETTLED_TAIL_INITIAL_COUNT = 10;
const SETTLED_TAIL_PAGE_COUNT = 25;
const BUSY_STATUSES = new Set(["in_progress", "listing"]);

type Listing = {
  id: string;
  title?: string | null;
  status?: string | null;
  settled_at?: string | null;
  unsettled_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

interface Props {
  conversations: Listing[] | undefined;
  selectedConvId: string | null;
  activeView: "listings" | "settings";
  creating?: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string, title: string) => void;
  onOpenSettings: () => void;
}

function readSettledExpanded(): boolean {
  try {
    const raw = localStorage.getItem(SETTLED_SHELF_KEY);
    if (raw === null) return true;
    return raw === "true";
  } catch {
    return true;
  }
}

function timestampMs(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function activeAnchorMs(listing: Listing): number {
  return Math.max(timestampMs(listing.updated_at), timestampMs(listing.unsettled_at), timestampMs(listing.created_at));
}

function settledAnchorMs(listing: Listing): number {
  return timestampMs(listing.settled_at) || timestampMs(listing.updated_at);
}

function compactRelativeTime(iso?: string | null, now = Date.now()): string {
  const then = timestampMs(iso);
  if (!then) return "";
  const sec = Math.max(0, Math.round((now - then) / 1000));
  if (sec < 45) return "now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h`;
  const day = Math.round(hr / 24);
  if (day < 7) return `${day}d`;
  const week = Math.round(day / 7);
  if (week < 5) return `${week}w`;
  const month = Math.round(day / 30);
  if (month < 12) return `${month}mo`;
  return `${Math.round(day / 365)}y`;
}

function matchesQuery(listing: Listing, needle: string): boolean {
  if (!needle) return true;
  const title = String(listing.title || "Untitled").toLowerCase();
  const status = String(listing.status || "draft").replace(/_/g, " ").toLowerCase();
  return title.includes(needle) || status.includes(needle);
}

export function ListingSidebar({
  conversations,
  selectedConvId,
  activeView,
  creating,
  onSelect,
  onCreate,
  onDelete,
  onOpenSettings,
}: Props) {
  const queryClient = useQueryClient();
  const [listingQuery, setListingQuery] = useState("");
  const [settledExpanded, setSettledExpanded] = useState(readSettledExpanded);
  const [settledVisibleCount, setSettledVisibleCount] = useState(SETTLED_TAIL_INITIAL_COUNT);

  const settleListing = useMutation({
    mutationFn: (id: string) => api.conversations.settle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });
  const unsettleListing = useMutation({
    mutationFn: (id: string) => api.conversations.unsettle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });

  const needle = listingQuery.trim().toLowerCase();
  const { activeListings, settledListings } = useMemo(() => {
    const visible = (conversations || []).filter((listing) => matchesQuery(listing, needle));
    const active = visible.filter((listing) => !listing.settled_at).sort((left, right) => activeAnchorMs(right) - activeAnchorMs(left));
    const settled = visible.filter((listing) => listing.settled_at).sort((left, right) => settledAnchorMs(right) - settledAnchorMs(left) || left.id.localeCompare(right.id));
    return { activeListings: active, settledListings: settled };
  }, [conversations, needle]);

  const visibleSettled = useMemo(() => {
    const visible = settledListings.slice(0, settledVisibleCount);
    const selected = settledListings.find((listing) => listing.id === selectedConvId && activeView === "listings");
    if (selected && !visible.some((listing) => listing.id === selected.id)) visible.push(selected);
    return visible;
  }, [activeView, selectedConvId, settledListings, settledVisibleCount]);

  const renderedSettled = settledExpanded
    ? visibleSettled
    : visibleSettled.filter((listing) => listing.id === selectedConvId && activeView === "listings");
  const hiddenSettledCount = Math.max(0, settledListings.length - visibleSettled.length);

  const toggleSettledShelf = useCallback(() => {
    setSettledExpanded((value) => {
      const next = !value;
      try {
        localStorage.setItem(SETTLED_SHELF_KEY, String(next));
      } catch {
        /* ignore quota / private-mode failures */
      }
      return next;
    });
  }, []);

  const handleSearchChange = (value: string) => {
    setListingQuery(value);
    setSettledVisibleCount(SETTLED_TAIL_INITIAL_COUNT);
  };

  return (
    <aside className="panel sidebar">
      <div className="sidebar-header pywebview-drag-region">
        <div className="sidebar-brand">
          <span className="sidebar-wordmark">Vendoo</span>
          <span className="sidebar-product">Studio</span>
        </div>
      </div>

      <div className="sidebar-toolbar">
        <label className="sidebar-search">
          <svg className="sidebar-search-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={listingQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search listings"
            aria-label="Search listings"
          />
        </label>
        <button
          className="sidebar-icon-btn"
          title="New listing"
          aria-label="New listing"
          disabled={creating}
          onClick={onCreate}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M8 3.5v9M3.5 8h9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="sidebar-list">
        {activeListings.map((listing) => (
          <ListingRow
            key={listing.id}
            listing={listing}
            selected={selectedConvId === listing.id && activeView === "listings"}
            settled={false}
            busy={BUSY_STATUSES.has(String(listing.status || "draft"))}
            settling={settleListing.isPending}
            onSelect={onSelect}
            onDelete={onDelete}
            onSettle={(id) => settleListing.mutate(id)}
          />
        ))}

        {settledListings.length > 0 && (
          <>
            <button
              type="button"
              className="sidebar-shelf-header"
              aria-expanded={settledExpanded}
              onClick={toggleSettledShelf}
            >
              <span className="sidebar-shelf-label">
                {settledExpanded ? "Settled" : `Settled (${settledListings.length})`}
              </span>
              <span className="sidebar-shelf-rule" aria-hidden="true" />
              <svg className="sidebar-shelf-chevron" width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            {renderedSettled.map((listing) => (
              <ListingRow
                key={listing.id}
                listing={listing}
                selected={selectedConvId === listing.id && activeView === "listings"}
                settled
                busy={false}
                settling={unsettleListing.isPending}
                onSelect={onSelect}
                onDelete={onDelete}
                onUnsettle={(id) => unsettleListing.mutate(id)}
              />
            ))}
            {settledExpanded && hiddenSettledCount > 0 && (
              <button
                type="button"
                className="sidebar-show-more"
                onClick={() => setSettledVisibleCount((count) => count + SETTLED_TAIL_PAGE_COUNT)}
              >
                Show {Math.min(hiddenSettledCount, SETTLED_TAIL_PAGE_COUNT)} more
              </button>
            )}
          </>
        )}

        {(!conversations || conversations.length === 0) && (
          <div className="sidebar-empty">No listings yet</div>
        )}
        {conversations && conversations.length > 0 && activeListings.length === 0 && settledListings.length === 0 && (
          <div className="sidebar-empty">No matching listings</div>
        )}
      </div>

      <div className="sidebar-footer">
        <button
          className={`sidebar-icon-btn${activeView === "settings" ? " selected" : ""}`}
          title="Settings"
          aria-label="Settings"
          onClick={onOpenSettings}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.5" />
            <path d="M8 2.4v1.5M8 12.1v1.5M2.4 8h1.5M12.1 8h1.5M4 4l1.1 1.1M10.9 10.9l1.1 1.1M12 4l-1.1 1.1M5.1 10.9L4 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
        <UpdateButton />
      </div>
    </aside>
  );
}

function ListingRow({
  listing,
  selected,
  settled,
  busy,
  settling,
  onSelect,
  onDelete,
  onSettle,
  onUnsettle,
}: {
  listing: Listing;
  selected: boolean;
  settled: boolean;
  busy: boolean;
  settling: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string, title: string) => void;
  onSettle?: (id: string) => void;
  onUnsettle?: (id: string) => void;
}) {
  const title = listing.title || "Untitled";
  const status = String(listing.status || "draft");
  const statusClass = status.replace(/_/g, "-");
  const statusLabel = status.replace(/_/g, " ");
  const settledAt = settled ? compactRelativeTime(listing.settled_at || listing.updated_at) : "";

  return (
    <div className="nav-item">
      <button
        className={`nav-link${selected ? " selected" : ""}${settled ? " settled" : ""}`}
        onClick={() => onSelect(listing.id)}
      >
        <div className="nav-link-title">{title}</div>
        <div className="nav-link-meta">
          <span className={`nav-status nav-status-${statusClass}`}>{statusLabel}</span>
          {settledAt ? <span className="nav-time">{settledAt}</span> : null}
        </div>
      </button>
      <div className="nav-actions">
        {!busy && onSettle && (
          <button
            className="nav-action"
            title="Settle listing"
            aria-label={`Settle ${title}`}
            disabled={settling}
            onClick={(e) => {
              e.stopPropagation();
              onSettle(listing.id);
            }}
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M3.5 8.5l3 3 6-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
        {onUnsettle && (
          <button
            className="nav-action"
            title="Un-settle listing"
            aria-label={`Un-settle ${title}`}
            disabled={settling}
            onClick={(e) => {
              e.stopPropagation();
              onUnsettle(listing.id);
            }}
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4.5 7.5H12a3 3 0 010 6H9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <path d="M7 4.5L4.5 7.5 7 10.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
        <button
          className="nav-action"
          title="Delete"
          aria-label={`Delete ${title}`}
          onClick={(e) => {
            e.stopPropagation();
            if (confirm(`Delete "${title}"?`)) onDelete(listing.id, title);
          }}
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
