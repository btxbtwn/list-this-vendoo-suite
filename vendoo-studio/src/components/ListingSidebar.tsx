import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { fetchVendooItemLive } from "../api/vendooItemQuery";
import { addToast } from "../ui/toast";
import { UpdateButton } from "./UpdateButton";
import {
  SETTINGS_NAV_ITEMS,
  SETTINGS_SECTION_LABELS,
  searchSettings,
  type SettingsSearchItem,
  type SettingsSectionId,
} from "./settingsNav";
import { statusFromListingStatus } from "./fillLogForms";

const SETTLED_SHELF_KEY = "vendoo-studio.settled-expanded";
const SETTLED_TAIL_INITIAL_COUNT = 10;
const SETTLED_TAIL_PAGE_COUNT = 25;
const BUSY_STATUSES = new Set(["in_progress", "listing"]);
const MANUAL_STATUSES = ["draft", "completed", "failed"] as const;
const HOVER_STATUS_DELAY_MS = 280;
const MARKETPLACE_STATUS_ORDER = [
  "general",
  "ebay",
  "etsy",
  "poshmark",
  "mercari",
  "depop",
  "facebook",
  "shopify",
  "vinted",
  "whatnot",
  "sellwild",
];
const MARKETPLACE_STATUS_LABELS: Record<string, string> = {
  general: "Vendoo",
  ebay: "eBay",
  etsy: "Etsy",
  poshmark: "Poshmark",
  mercari: "Mercari",
  depop: "Depop",
  facebook: "Facebook",
  shopify: "Shopify",
  vinted: "Vinted",
  whatnot: "Whatnot",
  sellwild: "Sellwild",
  grailed: "Grailed",
};
const INVALID_LIVE_STATUSES = new Set(["BETA", "NEW", "ALPHA"]);

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
  settingsSection: SettingsSectionId;
  creating?: boolean;
  canCreate?: boolean;
  mobileOpen?: boolean;
  listingQuery: string;
  onSearchQueryChange: (query: string) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string, title: string) => void;
  onOpenSettings: () => void;
  onCloseSettings: () => void;
  onSettingsSectionChange: (section: SettingsSectionId) => void;
  onSettingsSearchResult: (item: SettingsSearchItem) => void;
}

export function HamburgerIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M2.5 4.25h11M2.5 8h8.5M2.5 11.75h6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export function BackIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M10.25 3.25 5.5 8l4.75 4.75" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ComposeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M18.375 2.625a2.121 2.121 0 013 3L8.5 18.5 4 20l1.5-4.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SearchIcon() {
  return (
    <svg className="sidebar-search-icon" width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function SettingsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

function readLegacySettledExpanded(): boolean | null {
  try {
    const raw = localStorage.getItem(SETTLED_SHELF_KEY);
    if (raw === null) return null;
    return raw === "true";
  } catch {
    return null;
  }
}

function clearLegacySettledExpanded() {
  try {
    localStorage.removeItem(SETTLED_SHELF_KEY);
  } catch {
    /* ignore quota / private-mode failures */
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

function SettingsSectionIcon({ section }: { section: SettingsSectionId }) {
  if (section === "general") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.75" />
      </svg>
    );
  }
  if (section === "providers") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 8V4H8" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="4" y="8" width="16" height="12" rx="2" stroke="currentColor" strokeWidth="1.75" />
        <path d="M2 14h2M20 14h2" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
        <circle cx="9" cy="14" r="1" fill="currentColor" />
        <circle cx="15" cy="14" r="1" fill="currentColor" />
      </svg>
    );
  }
  if (section === "integrations") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.75" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.75" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.75" />
        <path d="M14 17.5h7M17.5 14v7" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M10 13a5 5 0 0 0 7.07 0l2.12-2.12a5 5 0 0 0-7.07-7.07L11 4.93" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 11a5 5 0 0 0-7.07 0L4.81 13.12a5 5 0 0 0 7.07 7.07L13 19.07" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ListingSidebar({
  conversations,
  selectedConvId,
  activeView,
  settingsSection,
  creating,
  canCreate = true,
  mobileOpen,
  listingQuery,
  onSearchQueryChange,
  onSelect,
  onCreate,
  onDelete,
  onOpenSettings,
  onCloseSettings,
  onSettingsSectionChange,
  onSettingsSearchResult,
}: Props) {
  const queryClient = useQueryClient();
  const legacySettled = readLegacySettledExpanded();
  const [settledExpanded, setSettledExpanded] = useState(legacySettled ?? true);
  const [settledVisibleCount, setSettledVisibleCount] = useState(SETTLED_TAIL_INITIAL_COUNT);
  const [settingsQuery, setSettingsQuery] = useState("");
  const [activeResultIndex, setActiveResultIndex] = useState(0);
  const settingsSearchRef = useRef<HTMLInputElement>(null);
  const migratedSettledRef = useRef(false);
  const settingsMode = activeView === "settings";

  const { data: uiPrefs } = useQuery({
    queryKey: ["settings-ui"],
    queryFn: api.settings.ui,
  });

  useEffect(() => {
    if (!uiPrefs) return;
    if (!migratedSettledRef.current) {
      migratedSettledRef.current = true;
      const legacy = readLegacySettledExpanded();
      if (legacy !== null) {
        clearLegacySettledExpanded();
        if (legacy !== uiPrefs.settled_shelf_expanded) {
          setSettledExpanded(legacy);
          void api.settings
            .setUi({ settled_shelf_expanded: legacy })
            .then(() => {
              queryClient.invalidateQueries({ queryKey: ["settings-ui"] });
            })
            .catch(() => {
              migratedSettledRef.current = false;
            });
          return;
        }
      }
    }
    setSettledExpanded(uiPrefs.settled_shelf_expanded);
  }, [uiPrefs, queryClient]);

  const settleListing = useMutation({
    mutationFn: (id: string) => api.conversations.settle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });
  const unsettleListing = useMutation({
    mutationFn: (id: string) => api.conversations.unsettle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });
  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.jobs.list(),
    refetchInterval: 2000,
  });
  const jobIdByConversation = useMemo(() => {
    const map = new Map<string, string>();
    for (const job of jobs || []) {
      if (!job?.conversation_id || job.status === "cancelled") continue;
      if (!job.vendoo_item_id && !job.vendoo_url) continue;
      if (!map.has(job.conversation_id)) map.set(job.conversation_id, job.id);
    }
    return map;
  }, [jobs]);

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
  const settingsResults = useMemo(() => searchSettings(settingsQuery), [settingsQuery]);
  const isSettingsSearching = settingsQuery.trim().length > 0;

  useEffect(() => {
    if (!settingsMode) {
      setSettingsQuery("");
      setActiveResultIndex(0);
    }
  }, [settingsMode]);

  useEffect(() => {
    setActiveResultIndex((index) => Math.min(index, Math.max(settingsResults.length - 1, 0)));
  }, [settingsResults.length]);

  useEffect(() => {
    if (!settingsMode) return;
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable ||
          target.closest('[role="dialog"], [aria-modal="true"]') !== null)
      ) {
        return;
      }
      event.preventDefault();
      settingsSearchRef.current?.focus();
      settingsSearchRef.current?.select();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [settingsMode]);

  const toggleSettledShelf = useCallback(() => {
    setSettledExpanded((value) => {
      const next = !value;
      void api.settings
        .setUi({ settled_shelf_expanded: next })
        .then(() => {
          queryClient.invalidateQueries({ queryKey: ["settings-ui"] });
        })
        .catch(() => {
          /* keep in-memory toggle if disk write fails */
        });
      return next;
    });
  }, [queryClient]);

  const handleSearchChange = (value: string) => {
    onSearchQueryChange(value);
    setSettledVisibleCount(SETTLED_TAIL_INITIAL_COUNT);
  };

  const clearSettingsSearch = useCallback(() => {
    setSettingsQuery("");
    setActiveResultIndex(0);
  }, []);

  const handleSettingsResult = useCallback(
    (item: SettingsSearchItem) => {
      clearSettingsSearch();
      onSettingsSearchResult(item);
    },
    [clearSettingsSearch, onSettingsSearchResult],
  );

  const handleSettingsSearchKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Escape" && isSettingsSearching) {
        event.preventDefault();
        event.stopPropagation();
        clearSettingsSearch();
        return;
      }
      if (settingsResults.length === 0) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveResultIndex((index) => (index + 1) % settingsResults.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveResultIndex((index) => (index - 1 + settingsResults.length) % settingsResults.length);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const result = settingsResults[activeResultIndex];
        if (result) handleSettingsResult(result);
      }
    },
    [activeResultIndex, clearSettingsSearch, handleSettingsResult, isSettingsSearching, settingsResults],
  );

  return (
    <aside
      id="listings-sidebar"
      className={`panel sidebar${settingsMode ? " sidebar-settings" : ""}`}
      aria-label={settingsMode ? "Settings" : "Listings"}
      aria-hidden={mobileOpen === false ? true : undefined}
    >
      <div className="sidebar-header pywebview-drag-region">
        <div className="sidebar-brand">
          <span className="sidebar-wordmark">Vendoo</span>
          <span className="sidebar-product">Studio</span>
        </div>
        {!settingsMode ? (
          <button
            type="button"
            className="sidebar-icon-btn sidebar-header-settings"
            title="Settings"
            aria-label="Settings"
            onClick={onOpenSettings}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="3.5" cy="8" r="1.15" fill="currentColor" />
              <circle cx="8" cy="8" r="1.15" fill="currentColor" />
              <circle cx="12.5" cy="8" r="1.15" fill="currentColor" />
            </svg>
          </button>
        ) : (
          <button
            type="button"
            className="sidebar-icon-btn sidebar-header-settings"
            title="Back to listings"
            aria-label="Back to listings"
            onClick={onCloseSettings}
          >
            <BackIcon />
          </button>
        )}
      </div>

      {settingsMode ? (
        <>
          <div className="sidebar-toolbar">
            <label className="sidebar-search settings-sidebar-search">
              <SearchIcon />
              <input
                ref={settingsSearchRef}
                type="search"
                value={settingsQuery}
                onChange={(e) => {
                  setSettingsQuery(e.target.value);
                  setActiveResultIndex(0);
                }}
                onKeyDown={handleSettingsSearchKeyDown}
                placeholder="Search"
                aria-label="Search settings"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={isSettingsSearching && settingsResults.length > 0}
                aria-controls={isSettingsSearching && settingsResults.length > 0 ? "settings-search-results" : undefined}
                aria-activedescendant={
                  isSettingsSearching && settingsResults[activeResultIndex]
                    ? `settings-search-result-${settingsResults[activeResultIndex].id}`
                    : undefined
                }
              />
              {isSettingsSearching ? (
                <button
                  type="button"
                  className="settings-search-clear"
                  aria-label="Clear search"
                  onClick={() => {
                    clearSettingsSearch();
                    settingsSearchRef.current?.focus();
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  </svg>
                </button>
              ) : (
                <kbd className="settings-search-kbd">/</kbd>
              )}
            </label>
          </div>

          <div className="sidebar-list settings-sidebar-nav">
            {isSettingsSearching && settingsResults.length === 0 ? (
              <div className="sidebar-empty">No settings found</div>
            ) : null}
            {isSettingsSearching ? (
              <div id="settings-search-results" role="listbox" aria-label="Settings search results">
                {settingsResults.map((item, index) => (
                  <button
                    key={item.id}
                    id={`settings-search-result-${item.id}`}
                    type="button"
                    role="option"
                    aria-selected={index === activeResultIndex}
                    className={`settings-nav-result${index === activeResultIndex ? " selected" : ""}`}
                    onMouseEnter={() => setActiveResultIndex(index)}
                    onClick={() => handleSettingsResult(item)}
                  >
                    <span className="settings-nav-result-title">{item.title}</span>
                    <span className="settings-nav-result-section">{SETTINGS_SECTION_LABELS[item.section]}</span>
                  </button>
                ))}
              </div>
            ) : (
              <nav aria-label="Settings sections">
                {SETTINGS_NAV_ITEMS.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`settings-nav-item${settingsSection === item.id ? " selected" : ""}`}
                    onClick={() => onSettingsSectionChange(item.id)}
                  >
                    <SettingsSectionIcon section={item.id} />
                    <span>{item.label}</span>
                  </button>
                ))}
              </nav>
            )}
          </div>
        </>
      ) : (
        <>
          <div className="sidebar-toolbar">
            <label className="sidebar-search">
              <SearchIcon />
              <input
                type="search"
                value={listingQuery}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="Search"
                aria-label="Search listings"
              />
            </label>
            <button
              className="sidebar-icon-btn"
              title={canCreate ? "New listing" : "Sign in with ChatGPT or add a MiMo or Cursor key first"}
              aria-label={canCreate ? "New listing" : "Sign in with ChatGPT or add a MiMo or Cursor key first"}
              disabled={creating || !canCreate}
              onClick={onCreate}
            >
              <ComposeIcon />
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
                jobId={jobIdByConversation.get(listing.id)}
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
                    jobId={jobIdByConversation.get(listing.id)}
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
        </>
      )}

      <div className="sidebar-footer">
        <div className="sidebar-footer-actions">
          {settingsMode ? (
            <button
              type="button"
              className="sidebar-back-btn"
              aria-label="Back"
              onClick={onCloseSettings}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M19 12H5M12 19l-7-7 7-7" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>Back</span>
            </button>
          ) : (
            <button
              type="button"
              className="sidebar-icon-btn"
              title="Settings"
              aria-label="Settings"
              onClick={onOpenSettings}
            >
              <SettingsIcon />
            </button>
          )}
          <UpdateButton />
        </div>
      </div>
    </aside>
  );
}


function marketplaceLabel(id: string): string {
  return MARKETPLACE_STATUS_LABELS[id] || id.charAt(0).toUpperCase() + id.slice(1);
}

function normalizeLiveStatus(raw: unknown): string | undefined {
  if (typeof raw !== "string") return undefined;
  const cleaned = raw.replace(/\s+/g, " ").trim().toUpperCase();
  if (!cleaned || INVALID_LIVE_STATUSES.has(cleaned)) return undefined;
  return cleaned;
}

function liveStatusClass(status?: string): string {
  const key = (status || "").toLowerCase().replace(/\s+/g, "-");
  if (key === "listed" || key === "complete" || key === "sold") return "is-listed";
  if (key === "not-listed" || key === "draft" || key === "incomplete") return "is-not-listed";
  if (key === "failed") return "is-failed";
  return "";
}

function marketplaceStatusesFromDraft(draft: Record<string, unknown> | undefined | null): {
  id: string;
  label: string;
  status: string;
}[] {
  if (!draft) return [];
  const scrapedRaw = draft.statuses && typeof draft.statuses === "object" && !Array.isArray(draft.statuses)
    ? draft.statuses as Record<string, unknown>
    : undefined;
  const form = draft.form && typeof draft.form === "object" && !Array.isArray(draft.form)
    ? draft.form as Record<string, unknown>
    : undefined;
  const formStatuses = form?.statuses && typeof form.statuses === "object" && !Array.isArray(form.statuses)
    ? form.statuses as Record<string, unknown>
    : undefined;
  const scraped = scrapedRaw || formStatuses || {};
  const item = draft.item && typeof draft.item === "object" && !Array.isArray(draft.item)
    ? draft.item as Record<string, unknown>
    : undefined;
  const listings = item?.listings && typeof item.listings === "object" && !Array.isArray(item.listings)
    ? item.listings as Record<string, unknown>
    : {};

  const ids = [
    ...MARKETPLACE_STATUS_ORDER,
    ...Object.keys(scraped).filter((id) => !MARKETPLACE_STATUS_ORDER.includes(id)),
    ...Object.keys(listings).filter(
      (id) => id !== "validate" && !MARKETPLACE_STATUS_ORDER.includes(id) && !(id in scraped),
    ),
  ];

  const rows: { id: string; label: string; status: string }[] = [];
  for (const id of ids) {
    let status = normalizeLiveStatus(scraped[id]);
    if (!status && id !== "general") {
      const listing = listings[id] as Record<string, unknown> | undefined;
      status = statusFromListingStatus(listing?.status) || "";
    }
    if (!status) continue;
    rows.push({ id, label: marketplaceLabel(id), status });
  }
  return rows;
}

function ListingRow({
  listing,
  selected,
  settled,
  busy,
  settling,
  jobId,
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
  jobId?: string;
  onSelect: (id: string) => void;
  onDelete: (id: string, title: string) => void;
  onSettle?: (id: string) => void;
  onUnsettle?: (id: string) => void;
}) {
  const title = listing.title || "Untitled";
  const status = String(listing.status || "draft");
  const statusClass = status.replace(/_/g, "-");
  const settledAt = settled ? compactRelativeTime(listing.settled_at || listing.updated_at) : "";
  const queryClient = useQueryClient();
  const itemRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const skipRenameBlur = useRef(false);
  const hoverTimer = useRef<number | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const pointerInsideRef = useRef(false);
  const [hoverOpen, setHoverOpen] = useState(false);
  const [popupPos, setPopupPos] = useState<{ top: number; left: number } | null>(null);
  const [contextMenu, setContextMenu] = useState<{ top: number; left: number } | null>(null);
  const [readingDraft, setReadingDraft] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draftTitle, setDraftTitle] = useState(title);

  const renameListing = useMutation({
    mutationFn: (nextTitle: string) => api.conversations.update(listing.id, { title: nextTitle }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setRenaming(false);
    },
  });

  const updateStatus = useMutation({
    mutationFn: (nextStatus: string) => api.conversations.update(listing.id, { status: nextStatus }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const statusOptions = useMemo(() => {
    if ((MANUAL_STATUSES as readonly string[]).includes(status)) return [...MANUAL_STATUSES];
    return [status, ...MANUAL_STATUSES];
  }, [status]);

  // Observe Fields-panel cache without fetching.
  const cachedDraftQuery = useQuery({
    queryKey: ["vendoo-item", jobId || ""],
    queryFn: () => api.jobs.vendooItem(jobId || ""),
    enabled: false,
  });

  const peekQuery = useQuery({
    queryKey: ["vendoo-item-peek", jobId],
    queryFn: async () => {
      const data = await api.jobs.vendooItem(jobId || "", { cacheOnly: true });
      if (data?.ok && (data.item || data.form || data.statuses)) {
        queryClient.setQueryData(["vendoo-item", jobId], data);
      }
      return data;
    },
    enabled: Boolean(hoverOpen && jobId && !cachedDraftQuery.data && !readingDraft),
    staleTime: Infinity,
    retry: 0,
  });

  const draft = (cachedDraftQuery.data || peekQuery.data) as Record<string, unknown> | undefined;
  const marketplaceStatuses = useMemo(() => marketplaceStatusesFromDraft(draft), [draft]);
  const loadingStatus = Boolean(
    hoverOpen && jobId && (readingDraft || (!draft && peekQuery.isFetching)),
  );
  const missingStatus = Boolean(
    hoverOpen && jobId && !draft && !readingDraft && peekQuery.isFetched && !peekQuery.isFetching,
  );

  const clearHoverTimer = () => {
    if (hoverTimer.current != null) {
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
  };

  const updatePopupPos = useCallback(() => {
    const el = itemRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setPopupPos({
      top: Math.max(8, Math.min(rect.top, window.innerHeight - 220)),
      left: Math.min(rect.right + 8, window.innerWidth - 220),
    });
  }, []);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  const openHover = () => {
    if (!jobId || renaming || contextMenu) return;
    clearHoverTimer();
    hoverTimer.current = window.setTimeout(() => {
      updatePopupPos();
      setHoverOpen(true);
    }, HOVER_STATUS_DELAY_MS);
  };

  const closeHover = () => {
    clearHoverTimer();
    if (!readingDraft) setHoverOpen(false);
  };

  const startRename = () => {
    closeHover();
    closeContextMenu();
    skipRenameBlur.current = false;
    setDraftTitle(title);
    setRenaming(true);
  };

  const readDraft = async () => {
    if (!jobId || readingDraft) return;
    closeContextMenu();
    clearHoverTimer();
    updatePopupPos();
    setHoverOpen(true);
    setReadingDraft(true);
    try {
      const fresh = await fetchVendooItemLive(queryClient, jobId, { force: true });
      if (fresh?.error || fresh?.api_error) {
        addToast({
          type: "error",
          title: "Could not read Vendoo draft",
          description: String(fresh.error || fresh.api_error),
        });
      }
    } catch (error) {
      addToast({ type: "error", title: (error as Error).message || "Could not read Vendoo draft" });
    } finally {
      setReadingDraft(false);
      if (!pointerInsideRef.current) {
        window.setTimeout(() => {
          if (!pointerInsideRef.current) setHoverOpen(false);
        }, 2500);
      }
    }
  };

  const cancelRename = () => {
    skipRenameBlur.current = true;
    setDraftTitle(title);
    setRenaming(false);
  };

  const commitRename = () => {
    if (skipRenameBlur.current) {
      skipRenameBlur.current = false;
      return;
    }
    const next = draftTitle.trim();
    if (!next || next === title) {
      setRenaming(false);
      return;
    }
    renameListing.mutate(next);
  };

  useEffect(() => () => clearHoverTimer(), []);

  useEffect(() => {
    if (!renaming) return;
    const input = renameInputRef.current;
    if (!input) return;
    input.focus();
    input.select();
  }, [renaming]);

  useEffect(() => {
    if (!hoverOpen) return;
    const onScroll = () => updatePopupPos();
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [hoverOpen, updatePopupPos]);

  useEffect(() => {
    if (!contextMenu) return;
    const onPointer = (event: MouseEvent) => {
      if (menuRef.current?.contains(event.target as Node | null)) return;
      closeContextMenu();
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeContextMenu();
    };
    const onScroll = () => closeContextMenu();
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onScroll);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onScroll);
    };
  }, [closeContextMenu, contextMenu]);

  return (
    <div
      className="nav-item"
      ref={itemRef}
      onMouseEnter={() => {
        pointerInsideRef.current = true;
        openHover();
      }}
      onMouseLeave={() => {
        pointerInsideRef.current = false;
        closeHover();
      }}
      onFocus={openHover}
      onBlur={(event) => {
        if (!itemRef.current?.contains(event.relatedTarget as Node | null)) closeHover();
      }}
      onContextMenu={(event) => {
        if (renaming) return;
        event.preventDefault();
        event.stopPropagation();
        clearHoverTimer();
        setHoverOpen(false);
        const menuWidth = 168;
        const menuHeight = 44;
        setContextMenu({
          top: Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8)),
          left: Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8)),
        });
      }}
    >
      <div
        className={`nav-link${selected ? " selected" : ""}${settled ? " settled" : ""}`}
        onClick={() => {
          if (!renaming) onSelect(listing.id);
        }}
      >
        {renaming ? (
          <input
            ref={renameInputRef}
            className="nav-rename-input"
            value={draftTitle}
            aria-label={`Rename ${title}`}
            disabled={renameListing.isPending}
            onChange={(e) => setDraftTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                e.currentTarget.blur();
              } else if (e.key === "Escape") {
                e.preventDefault();
                cancelRename();
              }
            }}
            onBlur={commitRename}
          />
        ) : (
          <button
            type="button"
            className="nav-link-title"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(listing.id);
            }}
            onDoubleClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              startRename();
            }}
          >
            {title}
          </button>
        )}
        <div className="nav-link-meta">
          <select
            className={`nav-status-select nav-status-${statusClass}`}
            value={status}
            aria-label={`Status for ${title}`}
            disabled={updateStatus.isPending}
            title="Change listing status"
            onClick={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onChange={(e) => {
              e.stopPropagation();
              const next = e.target.value;
              if (next === status) return;
              updateStatus.mutate(next);
            }}
          >
            {statusOptions.map((option) => (
              <option key={option} value={option} disabled={BUSY_STATUSES.has(option)}>
                {option.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          {settledAt ? <span className="nav-time">{settledAt}</span> : null}
        </div>
      </div>
      {!renaming && (
        <div className="nav-actions">
          <button
            className="nav-action"
            title="Rename listing"
            aria-label={`Rename ${title}`}
            disabled={renameListing.isPending}
            onClick={(e) => {
              e.stopPropagation();
              startRename();
            }}
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path
                d="M11.5 2.5l2 2L5.5 12.5H3.5v-2L11.5 2.5z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
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
      )}
      {contextMenu ? (
        <div
          ref={menuRef}
          className="nav-context-menu"
          style={{ top: contextMenu.top, left: contextMenu.left }}
          role="menu"
        >
          <button
            type="button"
            className="nav-context-menu-item"
            role="menuitem"
            disabled={!jobId || readingDraft}
            title={jobId ? "Read live marketplace statuses from Vendoo" : "No Vendoo draft linked yet"}
            onClick={() => {
              void readDraft();
            }}
          >
            {readingDraft ? "Reading…" : "Read draft"}
          </button>
        </div>
      ) : null}
      {hoverOpen && jobId && popupPos ? (
        <div
          className="nav-vendoo-status-popup"
          style={{ top: popupPos.top, left: popupPos.left }}
          role="tooltip"
        >
          <div className="nav-vendoo-status-title">Vendoo status</div>
          {loadingStatus ? (
            <div className="nav-vendoo-status-empty">Reading…</div>
          ) : marketplaceStatuses.length ? (
            <ul className="nav-vendoo-status-list">
              {marketplaceStatuses.map((row) => (
                <li key={row.id} className="nav-vendoo-status-row">
                  <span className="nav-vendoo-status-market">{row.label}</span>
                  <span className={`pr-live-status ${liveStatusClass(row.status)}`}>{row.status}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="nav-vendoo-status-empty">
              {missingStatus
                ? "Right-click and choose Read draft to load live status."
                : "No marketplace status yet."}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
