import { describe, expect, it } from "vitest";
import { isSettingsSectionId, searchSettings, SETTINGS_NAV_ITEMS, SETTINGS_SEARCH_ITEMS } from "./settingsNav";

describe("searchSettings", () => {
  it("returns nothing for a blank query", () => {
    expect(searchSettings("   ")).toEqual([]);
  });

  it("matches titles and search terms case-insensitively", () => {
    expect(searchSettings("TAILNET").map((item) => item.id)).toEqual(["tailscale-https"]);
    expect(searchSettings("brave search").map((item) => item.id)).toEqual(["brave"]);
    expect(searchSettings("description formula").map((item) => item.id)).toContain("listing-formulas");
  });

  it("matches when every word appears somewhere in the item", () => {
    expect(searchSettings("sign  chatgpt").map((item) => item.id)).toContain("chatgpt");
  });

  it("finds appearance by light/dark synonyms", () => {
    expect(searchSettings("light mode").map((item) => item.id)).toEqual(["appearance"]);
    expect(searchSettings("color scheme").map((item) => item.id)).toEqual(["appearance"]);
  });

  it("only points at real sections", () => {
    for (const item of SETTINGS_SEARCH_ITEMS) expect(isSettingsSectionId(item.section)).toBe(true);
    expect(SETTINGS_NAV_ITEMS.map((item) => item.id)).toEqual(["general", "providers", "integrations", "connections"]);
    expect(isSettingsSectionId("billing")).toBe(false);
  });
});
