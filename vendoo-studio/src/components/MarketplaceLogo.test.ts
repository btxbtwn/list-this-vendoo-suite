import { describe, expect, it } from "vitest";
import { hasMarketplaceLogo, marketplaceLogoColor } from "./MarketplaceLogo";
import { OFFICIAL_LOGOS } from "./marketplaceLogos";

describe("MarketplaceLogo", () => {
  it("ships official Vendoo logos for core marketplaces", () => {
    for (const id of ["general", "ebay", "etsy", "poshmark", "mercari", "depop", "facebook"]) {
      expect(hasMarketplaceLogo(id)).toBe(true);
      expect(OFFICIAL_LOGOS[id].paths.length).toBeGreaterThan(0);
      expect(OFFICIAL_LOGOS[id].viewBox).toMatch(/^\d/);
    }
  });

  it("keeps brand fills on official path logos", () => {
    expect(marketplaceLogoColor("ebay")).toBe("#0064D2");
    expect(marketplaceLogoColor("poshmark")).toBe("#822533");
    expect(marketplaceLogoColor("depop")).toBe("#FF2300");
  });

  it("falls back for unknown marketplaces", () => {
    expect(hasMarketplaceLogo("unknown-market")).toBe(false);
    expect(marketplaceLogoColor("unknown-market")).toBe("#5C6578");
  });
});
