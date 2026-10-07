import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ListingBlockers } from "./ListingBlockers";
import { SendProgress } from "./SendProgress";

describe("review screens", () => {
  it("groups blockers and exposes individual fix buttons", () => {
    const html = renderToStaticMarkup(<ListingBlockers issues={[{ field: "price", message: "Price is required" }, { field: "ebay_specifics.size", message: "eBay size is required" }]} onSelect={vi.fn()} />);
    expect(html).toContain("General · 1 issue");
    expect(html).toContain("eBay · 1 issue");
    expect(html).toContain("Fix price");
  });
  it("uses measured progress and never renders a synthetic percentage", () => {
    const html = renderToStaticMarkup(<SendProgress label="3 of 8 photos uploaded" photos={{ completed: 3, total: 8 }} />);
    expect(html).toContain('max="8" value="3"');
    expect(html).not.toContain("%");
  });
});
