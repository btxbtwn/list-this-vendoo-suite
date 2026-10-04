import type { ListingReviewTab } from "../components/ListingReviewTabs";

export interface OpenListingTab {
  id: string;
  reviewTab: ListingReviewTab;
  nonce: number;
  queuedMessage: string | null;
}

export interface ListingTabsState {
  tabs: OpenListingTab[];
  selectedId: string | null;
}

export type ListingTabsAction =
  | { type: "open"; id: string }
  | { type: "close"; id: string }
  | { type: "review"; id: string; value: ListingReviewTab }
  | { type: "message"; id: string; value: string | null }
  | { type: "clear"; id: string };

export function initialListingTabs(id: string | null): ListingTabsState {
  return id ? listingTabsReducer({ tabs: [], selectedId: null }, { type: "open", id }) : { tabs: [], selectedId: null };
}

export function listingTabsReducer(state: ListingTabsState, action: ListingTabsAction): ListingTabsState {
  if (action.type === "open") {
    const tabs = state.tabs.some((tab) => tab.id === action.id)
      ? state.tabs
      : [...state.tabs, { id: action.id, reviewTab: "input" as const, nonce: 0, queuedMessage: null }];
    return { tabs, selectedId: action.id };
  }
  if (action.type === "close") {
    const index = state.tabs.findIndex((tab) => tab.id === action.id);
    if (index < 0) return state;
    const tabs = state.tabs.filter((tab) => tab.id !== action.id);
    return {
      tabs,
      selectedId: state.selectedId === action.id
        ? (tabs[Math.min(index, tabs.length - 1)]?.id ?? null)
        : state.selectedId,
    };
  }
  return {
    ...state,
    tabs: state.tabs.map((tab) => {
      if (tab.id !== action.id) return tab;
      if (action.type === "review") return { ...tab, reviewTab: action.value };
      if (action.type === "message") return { ...tab, queuedMessage: action.value };
      return { ...tab, nonce: tab.nonce + 1, reviewTab: "input", queuedMessage: null };
    }),
  };
}
