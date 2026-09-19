import { describe, expect, it } from "vitest";
import { clampPanelWidth } from "./PanelResizeHandle";

describe("clampPanelWidth", () => {
  it("keeps the width inside the limits", () => {
    expect(clampPanelWidth(120, 200, 420)).toBe(200);
    expect(clampPanelWidth(900, 200, 420)).toBe(420);
    expect(clampPanelWidth(310.6, 200, 420)).toBe(311);
  });

  it("falls back to the minimum when there is no room to grow", () => {
    expect(clampPanelWidth(500, 300, 250)).toBe(300);
  });
});
