import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import {
  bulkRegenerateToast,
  bulkRegenerateWarning,
  listingCanRegenerate,
  mergeRegenerateIds,
  toggleListingSelection,
} from "../bulkRegenerate";
import { confirmDialog, isConfirmDialogOpen } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";
import { hasOpenJob, INVENTORY_BUSY_POLL_MS, INVENTORY_IDLE_POLL_MS } from "../api/polling";
import { UpdateButton } from "./UpdateButton";
import { VendooImportButton } from "./VendooImportButton";
import {
  SETTINGS_NAV_ITEMS,
  SETTINGS_SECTION_LABELS,
  searchSettings,
  type SettingsSearchItem,
  type SettingsSectionId,
} from "./settingsNav";
import { statusFromListingStatus } from "./fillLogForms";
import { MarketplaceLogo } from "./MarketplaceLogo";
import { ListingFilters } from "./ListingFilters";
import { SuggestionsPanel } from "./SuggestionsPanel";
import { marketplacesNeedingRelist, relistStage } from "./relistStatus";
import { marketplaceName } from "./marketplaceNames";
import type { BulkRegenerate, BulkRegenerateRun } from "./useBulkRegenerate";
import { stopTitlebarDrag } from "./WorkspaceTopbar";
import type { WorkspaceView } from "./workspaceCrumbs";
import type { Suggestion } from "../api/types";
import {
  DEFAULT_LISTING_FILTERS,
  filterListings,
  labelCounts,
  labelOptions,
  listingStatusTab,
  matchesSearch,
  marketplaceCounts,
  marketplaceOptions,
  notListedCount,
  needsRelistCount,
  unsentCount,
  staleCounts,
  sortListings,
  statusCounts,
  type ListingFilters as Filters,
} from "./inventoryFilters";

const SETTLED_SHELF_KEY = "vendoo-studio.settled-expanded";
const SETTLED_TAIL_INITIAL_COUNT = 10;
const SETTLED_TAIL_PAGE_COUNT = 25;
const BUSY_STATUSES = new Set(["in_progress", "listing"]);
// Vendoo's Inventory labels, plus the states that are Studio's own doing.
const STATUS_HINTS: Record<string, string> = {
  draft: "Draft in Vendoo",
  active: "Listed on a marketplace, per Vendoo",
  sold: "Sold, per Vendoo",
  failed: "The last send to Vendoo failed",
  in_progress: "Studio is working on this listing",
  listing: "Studio is sending this listing to Vendoo",
};
const HOVER_STATUS_DELAY_MS = 280;
const NO_SUGGESTIONS: Suggestion[] = [];
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
  "grailed",
  "vestiaire",
  "sellwild",
];
// Vendoo keys Vestiaire's API integration separately; Settings treats it as one marketplace.
const MARKETPLACE_ID_ALIASES: Record<string, string> = { vestiaireApi: "vestiaire" };
const LISTED_LIVE_STATUSES = new Set(["LISTED", "SOLD"]);
const INVALID_LIVE_STATUSES = new Set(["BETA", "NEW", "ALPHA"]);

type Listing = {
  id: string;
  title?: string | null;
  status?: string | null;
  settled_at?: string | null;
  unsettled_at?: string | null;
  created_at?: string;
  updated_at?: string;
  cover_photo_url?: string | null;
  vendoo_cover_url?: string | null;
  sku?: string | null;
  price?: number | null;
  vendoo_labels?: string[];
  vendoo_listed_at?: string | null;
  vendoo_sold_at?: string | null;
  vendoo_marketplaces?: string[];
  vendoo_listed_dates?: Record<string, string>;
  vendoo_sold_dates?: Record<string, string>;
  vendoo_form_updated_at?: string | null;
  vendoo_relist_pending?: string[];
  unsent_edits?: boolean;
};

interface Props {
  conversations: Listing[] | undefined;
  selectedConvId: string | null;
  activeView: WorkspaceView;
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
  onOpenAnalytics: () => void;
  onOpenSourcing: () => void;
  onOpenQueue: () => void;
  queueCount: number;
  onCloseSettings: () => void;
  onSettingsSectionChange: (section: SettingsSectionId) => void;
  onSettingsSearchResult: (item: SettingsSearchItem) => void;
  /** The bulk Regenerate / Generate run, owned by App so it outlives the sidebar. */
  bulk: BulkRegenerate;
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

function SelectCheck() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3 8.5l3.5 3.5L13 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
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

export function AnalyticsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 19V10M10 19V5M16 19v-6M21 19H3" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  );
}

export function SourcingIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M21 8l-9-5-9 5v8l9 5 9-5V8zM3 8l9 5 9-5M12 13v8"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
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

/** Why a listing reads the way it does. Status follows Vendoo; it is never set here. */
export function statusHint(status: string): string {
  const hint = STATUS_HINTS[status];
  if (hint) return hint;
  return `${status.replace(/_/g, " ")} · follows Vendoo`;
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
  if (section === "listings") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12.59 2.59A2 2 0 0 0 11.17 2H4a2 2 0 0 0-2 2v7.17a2 2 0 0 0 .59 1.42l8.7 8.7a2.43 2.43 0 0 0 3.42 0l6.58-6.58a2.43 2.43 0 0 0 0-3.42z" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" />
        <circle cx="7.5" cy="7.5" r="1" fill="currentColor" />
      </svg>
    );
  }
  if (section === "data") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <ellipse cx="12" cy="5" rx="9" ry="3" stroke="currentColor" strokeWidth="1.75" />
        <path d="M3 5v14a9 3 0 0 0 18 0V5" stroke="currentColor" strokeWidth="1.75" />
        <path d="M3 12a9 3 0 0 0 18 0" stroke="currentColor" strokeWidth="1.75" />
      </svg>
    );
  }
  if (section === "logs") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
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
  onOpenAnalytics,
  onOpenSourcing,
  onOpenQueue,
  queueCount,
  onCloseSettings,
  onSettingsSectionChange,
  onSettingsSearchResult,
  bulk,
}: Props) {
  const queryClient = useQueryClient();
  const legacySettled = readLegacySettledExpanded();
  const [settledExpanded, setSettledExpanded] = useState(legacySettled ?? true);
  const [settledVisibleCount, setSettledVisibleCount] = useState(SETTLED_TAIL_INITIAL_COUNT);
  const [settingsQuery, setSettingsQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(DEFAULT_LISTING_FILTERS);
  const [activeResultIndex, setActiveResultIndex] = useState(0);
  const [selecting, setSelecting] = useState(false);
  const [pickedIds, setPickedIds] = useState<Set<string>>(() => new Set());
  const settingsSearchRef = useRef<HTMLInputElement>(null);
  const selectionAnchor = useRef<string | null>(null);
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
    refetchInterval: (query) => (hasOpenJob(query.state.data) ? INVENTORY_BUSY_POLL_MS : INVENTORY_IDLE_POLL_MS),
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
    const visible = filterListings(conversations || [], needle, filters);
    const active = visible.filter((listing) => !listing.settled_at).sort((left, right) => activeAnchorMs(right) - activeAnchorMs(left));
    const settled = visible.filter((listing) => listing.settled_at).sort((left, right) => settledAnchorMs(right) - settledAnchorMs(left) || left.id.localeCompare(right.id));
    // Every sort but "recent" replaces each shelf's own recency order.
    return {
      activeListings: sortListings(active, filters.sort),
      settledListings: sortListings(settled, filters.sort),
    };
  }, [conversations, filters, needle]);

  const listingEligibleIds = useMemo(
    () => activeListings.filter((listing) => listingCanRegenerate(listing)).map((listing) => listing.id),
    [activeListings],
  );
  const { data: suggestionData } = useQuery({
    queryKey: ["suggestions"],
    queryFn: api.suggestions.list,
  });
  const suggestions = suggestionData?.suggestions ?? NO_SUGGESTIONS;
  const listingsById = useMemo(
    () => new Map((conversations || []).map((listing) => [listing.id, listing])),
    [conversations],
  );
  const suggestionEligibleIds = useMemo(
    () => suggestions.filter((suggestion) => {
      const listing = listingsById.get(suggestion.conversation_id);
      if (listing) return listingCanRegenerate(listing);
      return Boolean(suggestion.cover_photo_url);
    }).map((suggestion) => suggestion.conversation_id),
    [listingsById, suggestions],
  );
  const eligibleIds = useMemo(
    () => mergeRegenerateIds(suggestionEligibleIds, listingEligibleIds),
    [listingEligibleIds, suggestionEligibleIds],
  );
  const selectedIds = useMemo(() => {
    if (pickedIds.size === 0) return pickedIds;
    const eligible = new Set(eligibleIds);
    let changed = false;
    const next = new Set<string>();
    for (const id of pickedIds) {
      if (eligible.has(id)) next.add(id);
      else changed = true;
    }
    return changed ? next : pickedIds;
  }, [eligibleIds, pickedIds]);

  useEffect(() => {
    if (!selecting || bulk.running) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || isConfirmDialogOpen()) return;
      setSelecting(false);
      setPickedIds(new Set());
      selectionAnchor.current = null;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selecting, bulk.running]);

  const exitSelecting = useCallback(() => {
    setSelecting(false);
    setPickedIds(new Set());
    selectionAnchor.current = null;
  }, []);

  const toggleSelect = useCallback((id: string, shift: boolean, orderedIds: readonly string[]) => {
    setPickedIds((prev) => {
      const eligible = new Set(eligibleIds);
      const visible = new Set<string>();
      for (const picked of prev) {
        if (eligible.has(picked)) visible.add(picked);
      }
      const next = toggleListingSelection(visible, id, orderedIds, shift, selectionAnchor.current);
      selectionAnchor.current = next.anchorId;
      return next.selected;
    });
  }, [eligibleIds]);

  const toggleSelectAll = useCallback(() => {
    setPickedIds((prev) => {
      const allSelected = eligibleIds.length > 0 && eligibleIds.every((id) => prev.has(id));
      selectionAnchor.current = null;
      return allSelected ? new Set() : new Set(eligibleIds);
    });
  }, [eligibleIds]);

  const regenerateSelected = useCallback(async () => {
    const ids = eligibleIds.filter((id) => selectedIds.has(id));
    if (!ids.length || bulk.running) return;
    const confirmed = await confirmDialog(bulkRegenerateWarning(ids.length), {
      variant: "destructive",
      confirmLabel: "Rewrite",
    });
    if (!confirmed) return;
    const titles = new Map(ids.map((id) => {
      const listing = listingsById.get(id);
      const suggestion = suggestions.find((item) => item.conversation_id === id);
      return [id, listing?.title || suggestion?.title || "Untitled"];
    }));
    const result = await bulk.start(ids, titles);
    if (!result) return;
    if (result.failed.length === 0) {
      exitSelecting();
    } else {
      const failed = new Set(result.failed.map((item) => item.id));
      setPickedIds(failed);
      selectionAnchor.current = null;
    }
    addToast(bulkRegenerateToast(result));
  }, [bulk, eligibleIds, exitSelecting, listingsById, selectedIds, suggestions]);

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

  const { data: marketplaceSettings } = useQuery({
    queryKey: ["settings-marketplaces"],
    queryFn: api.settings.marketplaces,
  });
  const visibleMarketplaces = useMemo(
    () => (marketplaceSettings ? new Set(marketplaceSettings.selected) : undefined),
    [marketplaceSettings],
  );
  // The filter bar offers what the inventory actually holds: the statuses it
  // wears, the marketplaces it sits on, and the Vendoo labels it carries.
  const searched = useMemo(
    () => (conversations || []).filter((listing) => matchesSearch(listing, needle)),
    [conversations, needle],
  );
  const counts = useMemo(() => statusCounts(searched), [searched]);
  // Each filter row carries how many listings it would keep, counted over the
  // status tab in front of the reader rather than the whole inventory.
  const facetSource = useMemo(
    () => searched.filter((listing) => filters.status === "all" || listingStatusTab(listing.status) === filters.status),
    [searched, filters.status],
  );
  const filterMarketplaceCounts = useMemo(() => marketplaceCounts(facetSource), [facetSource]);
  const filterLabelCounts = useMemo(() => labelCounts(facetSource), [facetSource]);
  const filterNotListedCount = useMemo(() => notListedCount(facetSource), [facetSource]);
  const filterStaleCounts = useMemo(() => staleCounts(facetSource), [facetSource]);
  const filterRelistCount = useMemo(() => needsRelistCount(facetSource), [facetSource]);
  const filterUnsentCount = useMemo(() => unsentCount(facetSource), [facetSource]);
  const labels = useMemo(() => labelOptions(conversations || []), [conversations]);
  const filterMarketplaces = useMemo(
    () => marketplaceOptions(conversations || [], marketplaceSettings?.selected || []),
    [conversations, marketplaceSettings],
  );
  // Cached Vendoo statuses for every rendered thread, so rows can badge where
  // they're listed without hovering. Reads the server cache only.
  const renderedJobIds = useMemo(
    () =>
      [...activeListings, ...renderedSettled]
        .map((listing) => jobIdByConversation.get(listing.id))
        .filter((id): id is string => Boolean(id))
        .sort(),
    [activeListings, renderedSettled, jobIdByConversation],
  );
  const { data: statusDrafts } = useQuery({
    queryKey: ["marketplace-statuses", renderedJobIds.join(",")],
    queryFn: () => api.jobs.marketplaceStatuses(renderedJobIds),
    enabled: renderedJobIds.length > 0,
    refetchInterval: 15000,
    placeholderData: (previous) => previous,
  });
  const statusDraftFor = (conversationId: string) => {
    const jobId = jobIdByConversation.get(conversationId);
    return jobId ? statusDrafts?.[jobId] : undefined;
  };
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

  const handleFiltersChange = (next: Filters) => {
    setFilters(next);
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
            onMouseDown={stopTitlebarDrag}
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
            onMouseDown={stopTitlebarDrag}
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
                placeholder="Search by title or SKU"
                aria-label="Search listings by title or SKU"
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
            <button
              type="button"
              className={`sidebar-select-btn${selecting ? " selected" : ""}`}
              title={selecting ? "Stop selecting" : "Select listings to regenerate"}
              aria-label={selecting ? "Stop selecting" : "Select listings to regenerate"}
              aria-pressed={selecting}
              onClick={() => {
                if (bulk.running) return;
                if (selecting) exitSelecting();
                else setSelecting(true);
              }}
            >
              Select
            </button>
          </div>

          <SuggestionsPanel
            variant="sidebar"
            selectedConvId={selectedConvId}
            onSelect={onSelect}
            selecting={selecting}
            selectedIds={selectedIds}
            selectLocked={bulk.running}
            canSelect={(suggestion) => suggestionEligibleIds.includes(suggestion.conversation_id)}
            onToggleSelect={(id, shift) => toggleSelect(id, shift, suggestionEligibleIds)}
          />

          <ListingFilters
            filters={filters}
            counts={counts}
            labels={labels}
            labelCounts={filterLabelCounts}
            marketplaces={filterMarketplaces}
            marketplaceCounts={filterMarketplaceCounts}
            notListedCount={filterNotListedCount}
            needsRelistCount={filterRelistCount}
            unsentCount={filterUnsentCount}
            staleCounts={filterStaleCounts}
            onChange={handleFiltersChange}
          />

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
                statusDraft={statusDraftFor(listing.id)}
                visibleMarketplaces={visibleMarketplaces}
                selecting={selecting}
                checked={selectedIds.has(listing.id)}
                canSelect={listingCanRegenerate(listing)}
                selectLocked={bulk.running}
                onToggleSelect={(id, shift) => toggleSelect(id, shift, listingEligibleIds)}
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
                    statusDraft={statusDraftFor(listing.id)}
                    visibleMarketplaces={visibleMarketplaces}
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

      {!settingsMode && (selecting || bulk.running) && (
        <div className="sidebar-bulk-bar" role="region" aria-label="Regenerate listings">
          <p className="sidebar-bulk-count">{bulkStatusLabel(bulk.run, selectedIds.size, eligibleIds.length)}</p>
          <div className="sidebar-bulk-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={bulk.running || eligibleIds.length === 0}
              onClick={toggleSelectAll}
            >
              {eligibleIds.length > 0 && eligibleIds.every((id) => selectedIds.has(id)) ? "None" : "All"}
            </button>
            <button
              type="button"
              className="btn btn-danger btn-sm"
              disabled={bulk.running || selectedIds.size === 0}
              onClick={() => { void regenerateSelected(); }}
            >
              Regenerate
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={Boolean(bulk.run?.cancelRequested)}
              onClick={() => {
                if (bulk.running) bulk.cancel();
                else exitSelecting();
              }}
            >
              {bulk.running ? (bulk.run?.cancelRequested ? "Finishing…" : "Stop after this") : "Cancel"}
            </button>
          </div>
        </div>
      )}

      <div className="sidebar-footer">
        <div className="sidebar-footer-actions">
          {settingsMode ? null : <VendooImportButton />}
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
            <>
              <button
                type="button"
                className={`sidebar-icon-btn queue-nav${activeView === "queue" ? " selected" : ""}`}
                title="Queue"
                aria-label={`Queue${queueCount ? ` (${queueCount})` : ""}`}
                aria-pressed={activeView === "queue"}
                onClick={onOpenQueue}
              >
                <span>Queue{queueCount ? ` · ${queueCount}` : ""}</span>
              </button>
              <button
                type="button"
                className={`sidebar-icon-btn${activeView === "sourcing" ? " selected" : ""}`}
                title="Sourcing"
                aria-label="Sourcing"
                aria-pressed={activeView === "sourcing"}
                onClick={onOpenSourcing}
              >
                <SourcingIcon />
              </button>
              <button
                type="button"
                className={`sidebar-icon-btn${activeView === "analytics" ? " selected" : ""}`}
                title="Analytics"
                aria-label="Analytics"
                aria-pressed={activeView === "analytics"}
                onClick={onOpenAnalytics}
              >
                <AnalyticsIcon />
              </button>
              <button
                type="button"
                className="sidebar-icon-btn"
                title="Settings"
                aria-label="Settings"
                onClick={onOpenSettings}
              >
                <SettingsIcon />
              </button>
            </>
          )}
          <UpdateButton />
        </div>
      </div>
    </aside>
  );
}


function marketplaceLabel(id: string): string {
  return marketplaceName(id);
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

/** Live Vendoo status per marketplace, limited to `visible` (Settings → Listings → Marketplaces) when given. */
function marketplaceStatusesFromDraft(
  draft: Record<string, unknown> | undefined | null,
  visible?: Set<string>,
): {
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
  const seen = new Set<string>();
  for (const rawId of ids) {
    const id = MARKETPLACE_ID_ALIASES[rawId] || rawId;
    if (seen.has(id)) continue;
    if (visible && id !== "general" && !visible.has(id)) continue;
    let status = normalizeLiveStatus(scraped[rawId]);
    if (!status && rawId !== "general") {
      const listing = listings[rawId] as Record<string, unknown> | undefined;
      status = statusFromListingStatus(listing?.status) || "";
    }
    if (!status) continue;
    seen.add(id);
    rows.push({ id, label: marketplaceLabel(id), status });
  }
  return rows;
}

/** Where the import says the listing is live, for rows whose cached draft holds
 *  no per-marketplace status.
 *
 * `vendoo_marketplaces` is written from the same Vendoo payload the draft comes
 * from (`vendoo_listed_marketplaces`), counting sold as live, so an imported
 * listing can badge without anyone hovering it or pulling it again.
 */
export function listedFromImport(
  listing: {
    vendoo_marketplaces?: string[];
    vendoo_sold_dates?: Record<string, string>;
  },
  visible?: Set<string>,
): { id: string; label: string; status: string }[] {
  const sold = listing.vendoo_sold_dates || {};
  const rows: { id: string; label: string; status: string }[] = [];
  const seen = new Set<string>();
  for (const rawId of listing.vendoo_marketplaces || []) {
    const id = MARKETPLACE_ID_ALIASES[rawId] || rawId;
    if (id === "general" || seen.has(id)) continue;
    if (visible && !visible.has(id)) continue;
    seen.add(id);
    rows.push({
      id,
      label: marketplaceLabel(id),
      status: sold[rawId] || sold[id] ? "SOLD" : "LISTED",
    });
  }
  // The sidebar's own order, so a badged row reads the same whichever source
  // filled it.
  return rows.sort((left, right) => statusOrderIndex(left.id) - statusOrderIndex(right.id));
}

function statusOrderIndex(id: string): number {
  const index = MARKETPLACE_STATUS_ORDER.indexOf(id);
  return index === -1 ? MARKETPLACE_STATUS_ORDER.length : index;
}

function bulkStatusLabel(
  run: BulkRegenerateRun | null,
  selectedCount: number,
  eligibleCount: number,
): string {
  if (run) {
    const { title } = run;
    const place = `${run.index + 1} of ${run.total}`;
    if (run.cancelRequested) return `Finishing ${title}…`;
    if (run.phase === "finishing") return `Finishing fields on ${title} (${place})`;
    return `${run.mode === "generate" ? "Generating" : "Rewriting"} ${title} (${place})`;
  }
  if (eligibleCount === 0) return "No listings with photos to rewrite";
  return `${selectedCount} selected`;
}

function ListingRow({
  listing,
  selected,
  settled,
  busy,
  settling,
  jobId,
  statusDraft,
  visibleMarketplaces,
  selecting = false,
  checked = false,
  canSelect = false,
  selectLocked = false,
  onToggleSelect,
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
  statusDraft?: Record<string, unknown>;
  visibleMarketplaces?: Set<string>;
  selecting?: boolean;
  checked?: boolean;
  canSelect?: boolean;
  selectLocked?: boolean;
  onToggleSelect?: (id: string, shift: boolean) => void;
  onSelect: (id: string) => void;
  onDelete: (id: string, title: string) => void;
  onSettle?: (id: string) => void;
  onUnsettle?: (id: string) => void;
}) {
  const title = listing.title || "Untitled";
  // A bulk-imported listing has no local photos yet; Vendoo's own image stands in.
  const coverUrl = listing.cover_photo_url || listing.vendoo_cover_url || null;
  const status = String(listing.status || "draft");
  const statusClass = status.replace(/_/g, "-");
  const settledAt = settled ? compactRelativeTime(listing.settled_at || listing.updated_at) : "";
  const queryClient = useQueryClient();
  const itemRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const skipRenameBlur = useRef(false);
  const hoverTimer = useRef<number | null>(null);
  const [hoverOpen, setHoverOpen] = useState(false);
  const [popupPos, setPopupPos] = useState<{ top: number; left: number } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [draftTitle, setDraftTitle] = useState(title);

  const renameListing = useMutation({
    mutationFn: (nextTitle: string) => api.conversations.update(listing.id, { title: nextTitle }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setRenaming(false);
    },
  });

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
    // Not gated on the Fields-panel cache: that observer is disabled, so a pull's
    // invalidate never refetches it. Re-peeking after invalidation is what picks
    // up the refreshed server draft.
    enabled: Boolean(hoverOpen && jobId),
    staleTime: Infinity,
    retry: 0,
  });

  const fullDraft = (
    peekQuery.data?.ok && peekQuery.dataUpdatedAt >= cachedDraftQuery.dataUpdatedAt
      ? peekQuery.data
      : cachedDraftQuery.data || (peekQuery.data?.ok ? peekQuery.data : undefined)
  ) as Record<string, unknown> | undefined;
  const draft = fullDraft || statusDraft;
  const marketplaceStatuses = useMemo(
    () => marketplaceStatusesFromDraft(draft, visibleMarketplaces),
    [draft, visibleMarketplaces],
  );
  // A cached draft that names any marketplace is the live word and wins, even
  // when it says the listing is live nowhere. Only a draft with nothing to say
  // hands over to what the import recorded.
  const importedRows = useMemo(
    () => listedFromImport(listing, visibleMarketplaces),
    [listing, visibleMarketplaces],
  );
  const draftRows = marketplaceStatuses.filter((row) => row.id !== "general");
  const listedMarketplaces = draftRows.length
    ? draftRows.filter((row) => LISTED_LIVE_STATUSES.has(row.status))
    : importedRows;
  const popupStatuses = marketplaceStatuses.length ? marketplaceStatuses : importedRows;
  // "active" alone would read as done. These listings are live on copy older
  // than Studio's last write, and only a delist + relist in Vendoo fixes that.
  const relistMarketplaces = useMemo(() => marketplacesNeedingRelist(listing), [listing]);
  const relistStageNow = useMemo(() => relistStage(listing), [listing]);
  const loadingStatus = Boolean(
    hoverOpen && jobId && !draft && peekQuery.isFetching,
  );
  const missingStatus = Boolean(
    hoverOpen && jobId && !draft && peekQuery.isFetched && !peekQuery.isFetching,
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

  const openHover = () => {
    if (!jobId || renaming) return;
    clearHoverTimer();
    hoverTimer.current = window.setTimeout(() => {
      updatePopupPos();
      setHoverOpen(true);
    }, HOVER_STATUS_DELAY_MS);
  };

  const closeHover = () => {
    clearHoverTimer();
    setHoverOpen(false);
  };

  const startRename = () => {
    closeHover();
    skipRenameBlur.current = false;
    setDraftTitle(title);
    setRenaming(true);
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

  return (
    <div
      className={`nav-item${selecting ? " is-selecting" : ""}`}
      ref={itemRef}
      onMouseEnter={openHover}
      onMouseLeave={closeHover}
      onFocus={openHover}
      onBlur={(event) => {
        if (!itemRef.current?.contains(event.relatedTarget as Node | null)) closeHover();
      }}
    >
      <div
        className={`nav-link${selected ? " selected" : ""}${settled ? " settled" : ""}`}
        onClick={() => {
          if (!renaming) onSelect(listing.id);
        }}
      >
        {selecting ? (
          <button
            type="button"
            role="checkbox"
            className={`nav-select${checked ? " is-checked" : ""}`}
            aria-checked={checked}
            aria-label={`${checked ? "Deselect" : "Select"} ${title}`}
            disabled={!canSelect || selectLocked}
            title={canSelect ? "Include in regenerate" : "Add photos before regenerating"}
            onClick={(event) => {
              event.stopPropagation();
              if (!canSelect || selectLocked) return;
              onToggleSelect?.(listing.id, event.shiftKey);
            }}
          >
            {checked ? <SelectCheck /> : null}
          </button>
        ) : null}
        <div className="nav-thumb" aria-hidden="true">
          {coverUrl ? (
            <img className="nav-thumb-img" src={coverUrl} alt="" loading="lazy" draggable={false} />
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="1.5" y="2.5" width="13" height="11" rx="2" stroke="currentColor" strokeWidth="1.2" />
              <path d="M2 11l3.2-3.2a1.2 1.2 0 011.7 0L10 10.9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              <circle cx="10.4" cy="6" r="1.1" fill="currentColor" />
            </svg>
          )}
        </div>
        <div className="nav-link-body">
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
              title={title}
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
            <span className={`nav-status nav-status-${statusClass}`} title={statusHint(status)}>
              {status.replace(/_/g, " ")}
            </span>
            {listing.unsent_edits ? (
              <span
                className="nav-status nav-status-unsent"
                title="Edited in Studio since Vendoo last had this listing. Press Update Vendoo to write it onto the Vendoo form."
              >
                unsent
              </span>
            ) : null}
            {relistMarketplaces.length ? (
              <span
                className="nav-status nav-status-relist"
                title={relistStageNow === "list"
                  ? "Delisted in Vendoo and not listed again yet, so it is live nowhere."
                    + ` List it again to finish: ${relistMarketplaces.map(marketplaceName).join(", ")}.`
                  : `Updated in Studio after ${relistMarketplaces.map(marketplaceName).join(", ")} went live.`
                    + " Delist and relist in Vendoo to publish the new version."}
              >
                relist
              </span>
            ) : null}
            {settledAt ? <span className="nav-time">{settledAt}</span> : null}
          </div>
          {listedMarketplaces.length ? (
            <div
              className="nav-listed-logos"
              aria-label={`Listed on ${listedMarketplaces.map((row) => row.label).join(", ")}`}
            >
              {listedMarketplaces.map((row) => (
                <span key={row.id} className={row.status === "SOLD" ? "nav-listed-logo is-sold" : "nav-listed-logo"}>
                  <MarketplaceLogo id={row.id} label={`${row.label} · ${row.status.toLowerCase()}`} size={14} />
                </span>
              ))}
            </div>
          ) : null}
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
      {hoverOpen && jobId && popupPos ? (
        <div
          className="nav-vendoo-status-popup"
          style={{ top: popupPos.top, left: popupPos.left }}
          role="tooltip"
        >
          <div className="nav-vendoo-status-title">Vendoo status</div>
          {loadingStatus ? (
            <div className="nav-vendoo-status-empty">Reading…</div>
          ) : popupStatuses.length ? (
            <ul className="nav-vendoo-status-list">
              {popupStatuses.map((row) => (
                <li key={row.id} className="nav-vendoo-status-row">
                  <MarketplaceLogo id={row.id} label={row.label} size={16} />
                  <span className="nav-vendoo-status-market">{row.label}</span>
                  <span className={`pr-live-status ${liveStatusClass(row.status)}`}>{row.status}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="nav-vendoo-status-empty">
              {missingStatus
                ? "Pull from Vendoo to load live status."
                : "No marketplace status yet."}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
