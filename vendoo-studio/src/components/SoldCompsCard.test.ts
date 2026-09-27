import { describe, expect, it } from "vitest";
import { parseSoldComps } from "./SoldCompsCard";

const TEXT = [
  "Sold comps:",
  "Query: Forever 21 tube top sold comps",
  "Source: ChatGPT + Cursor + Brave",
  "Market: $8",
  "",
  "- $8 · Mercari · Good · Black corset tube top",
  "  https://www.mercari.com/us/item/m88731586257/",
  "",
  "Only 1 sold listing found — too thin to price from. Treat it as a weak signal, lean on an estimated baseline, and note pricing uncertainty in the description.",
  "",
  "Live listings (for sale now — asking prices, not sales; do not price from these):",
  "- $4 · eBay · Womens Forever 21 red crop top sz S",
  "  https://www.ebay.com/itm/404418932403",
].join("\n");

describe("parseSoldComps", () => {
  it("keeps live listings apart from sold comps", () => {
    const report = parseSoldComps(TEXT)!;
    expect(report.source).toBe("ChatGPT + Cursor + Brave");
    expect(report.comps.map((comp) => comp.price)).toEqual(["$8"]);
    expect(report.live).toEqual([
      {
        price: "$4",
        marketplace: "eBay",
        condition: "",
        title: "Womens Forever 21 red crop top sz S",
        url: "https://www.ebay.com/itm/404418932403",
      },
    ]);
    expect(report.note).toBe("");
    expect(report.liveCeiling).toBe("");
  });

  it("reads the live asking median", () => {
    const text = [
      "Sold comps:",
      "Query: Paper Crane crop top sold comps",
      "Source: Cursor",
      "No sold listings found. Use an estimated baseline and note pricing uncertainty in the description.",
      "",
      "Live listings (for sale now — asking prices, not sales):",
      "- $12 · Poshmark · Paper Crane crop top",
      "- $23 · Poshmark · Paper Crane bustier",
      "- $3 · Depop · Paper Crane crop",
      "",
      "Live asking median $12 — list at or below it; go higher only when this item is clearly better than those listings (new with tags, better condition, rarer size).",
    ].join("\n");
    const report = parseSoldComps(text)!;
    expect(report.live.map((comp) => comp.price)).toEqual(["$12", "$23", "$3"]);
    expect(report.liveCeiling).toBe("$12");
    expect(report.note).not.toContain("Live asking median");
  });
});
