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
  });
});
