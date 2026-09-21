import { describe, expect, it } from "vitest";
import { sendToVendooEnabled } from "./ListingEditor";

describe("sendToVendooEnabled", () => {
  it("allows send when the listing is valid and idle", () => {
    expect(sendToVendooEnabled(true, false)).toBe(true);
  });

  it("blocks send while generation or a refine is still writing fields", () => {
    expect(sendToVendooEnabled(true, true)).toBe(false);
  });

  it("blocks send when validation fails even if idle", () => {
    expect(sendToVendooEnabled(false, false)).toBe(false);
  });

  it("blocks send while the request is in flight", () => {
    expect(sendToVendooEnabled(true, false, true)).toBe(false);
  });
});
