import { describe, expect, it } from "vitest";
import { DEFAULT_SCOUT_FILTERS, SCOUT_PRESETS, activePreset, normalizeTrend, scoutQuery } from "./boxScout";

describe("scoutQuery", () => {
  it("sends the default filters without a trend or price cap", () => {
    expect(scoutQuery(DEFAULT_SCOUT_FILTERS)).toBe("min_pcs=20&target_cog=2&max_cog=4&include_vip=true");
  });

  it("adds trend words, a price cap and a refresh when set", () => {
    const query = new URLSearchParams(
      scoutQuery({ ...DEFAULT_SCOUT_FILTERS, trend: " Carhartt,,y2k ", maxPrice: 80, includeVip: false }, true),
    );
    expect(query.get("trend")).toBe("carhartt, y2k");
    expect(query.get("max_price")).toBe("80");
    expect(query.get("include_vip")).toBe("false");
    expect(query.get("refresh")).toBe("true");
  });
});

describe("normalizeTrend", () => {
  it("lowercases, trims and drops empty terms", () => {
    expect(normalizeTrend("Carhartt,  y2k ,,Band")).toBe("carhartt, y2k, band");
    expect(normalizeTrend(" , ")).toBe("");
  });
});

describe("activePreset", () => {
  it("names the preset the filters match, and none once they are edited", () => {
    expect(activePreset(DEFAULT_SCOUT_FILTERS)).toBe("everyday");
    expect(activePreset({ ...DEFAULT_SCOUT_FILTERS, ...SCOUT_PRESETS[1].filters })).toBe("higher-value");
    expect(activePreset({ ...DEFAULT_SCOUT_FILTERS, maxCog: 5 })).toBeNull();
  });
});
