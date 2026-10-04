import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ListingBlockers } from "./ListingBlockers";
import { SendProgress } from "./SendProgress";
import { SendReview } from "./SendReview";

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
  it("withholds approval when the preview fails", () => {
    const html = renderToStaticMarkup(<SendReview loading={false} error="Chrome disconnected" busy={false} onClose={vi.fn()} onRetry={vi.fn()} onApprove={vi.fn()} />);
    expect(html).toContain("Chrome disconnected");
    expect(html).toContain("Refresh preview");
    expect(html).toContain('disabled=""');
  });
  it("explains photo retention and shows old and new field values", () => {
    const html = renderToStaticMarkup(<SendReview preview={{ review_id: "review", revision_id: "rev", mode: "update", changes: [{ field: "generalDetails.price", before: 30, after: 20 }], photo_count: 8, photo_action: "keep", warnings: [] }} loading={false} busy={false} onClose={vi.fn()} onRetry={vi.fn()} onApprove={vi.fn()} />);
    expect(html).toContain("Keep the 8 photos already in Vendoo");
    expect(html).toContain("Nothing is published");
    expect(html).toContain("In Vendoo");
    expect(html).toContain("After saving");
    expect(html).toContain("Approve and update draft");
  });
});
