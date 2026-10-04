import { describe, expect, it } from "vitest";
import { initialListingTabs, listingTabsReducer, type ListingTabsState } from "./listingTabs";

function open(...ids: string[]): ListingTabsState {
  return ids.reduce((state, id) => listingTabsReducer(state, { type: "open", id }), initialListingTabs(null));
}

describe("open listing tabs", () => {
  it("opens a deep-linked listing immediately", () => {
    expect(initialListingTabs("linked")).toEqual(open("linked"));
  });
  it("switches back without duplicating or resetting a tab", () => {
    let state = open("a", "b");
    state = listingTabsReducer(state, { type: "review", id: "a", value: "forms" });
    state = listingTabsReducer(state, { type: "message", id: "a", value: "Fix price" });
    state = listingTabsReducer(state, { type: "open", id: "a" });
    expect(state.tabs.map((tab) => tab.id)).toEqual(["a", "b"]);
    expect(state.selectedId).toBe("a");
    expect(state.tabs[0]).toMatchObject({ reviewTab: "forms", queuedMessage: "Fix price" });
    expect(state.tabs[1]).toMatchObject({ reviewTab: "input", queuedMessage: null });
  });
  it("selects the next tab when closing the active middle tab", () => {
    const state = listingTabsReducer(open("a", "b", "c", "b"), { type: "close", id: "b" });
    expect(state.selectedId).toBe("c");
    expect(state.tabs.map((tab) => tab.id)).toEqual(["a", "c"]);
  });
  it("selects the previous tab when closing the last active tab", () => {
    expect(listingTabsReducer(open("a", "b"), { type: "close", id: "b" }).selectedId).toBe("a");
  });
  it("keeps the active selection when closing a background tab", () => {
    expect(listingTabsReducer(open("a", "b"), { type: "close", id: "a" }).selectedId).toBe("b");
  });
  it("returns to an empty workspace when the final tab closes", () => {
    expect(listingTabsReducer(open("a"), { type: "close", id: "a" })).toEqual(initialListingTabs(null));
  });
  it("ignores closing a tab that is already gone", () => {
    const state = open("a");
    expect(listingTabsReducer(state, { type: "close", id: "b" })).toBe(state);
  });
  it("clears only the intended listing after switching tabs", () => {
    let state = open("a");
    state = listingTabsReducer(state, { type: "message", id: "a", value: "Queued" });
    state = listingTabsReducer(state, { type: "review", id: "a", value: "fields" });
    state = listingTabsReducer(state, { type: "open", id: "b" });
    const other = state.tabs[1];
    state = listingTabsReducer(state, { type: "clear", id: "a" });
    expect(state.selectedId).toBe("b");
    expect(state.tabs[0]).toMatchObject({ nonce: 1, queuedMessage: null, reviewTab: "input" });
    expect(state.tabs[1]).toBe(other);
  });
});
