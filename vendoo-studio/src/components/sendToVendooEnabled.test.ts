import { describe, expect, it } from "vitest";
import { preferredSendJob, sendToVendooEnabled, suppressOwnSendConflict } from "./ListingEditor";

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

describe("preferredSendJob", () => {
  it("shows a still-running send ahead of a newer finished job", () => {
    const jobs = [
      { id: "new", status: "completed" },
      { id: "live", status: "dispatched" },
    ];
    expect(preferredSendJob(jobs)?.id).toBe("live");
  });
});

describe("suppressOwnSendConflict", () => {
  it("hides the busy error while this listing's send is already on screen", () => {
    expect(suppressOwnSendConflict(
      "Chrome is busy with another Vendoo job. Try again when it finishes.",
      true,
    )).toBe("");
    expect(suppressOwnSendConflict(
      "This listing is already queued or sending to Vendoo.",
      true,
    )).toBe("");
  });

  it("keeps a real other-listing conflict when nothing is sending here", () => {
    const message = 'Chrome is busy with "Other tee". Try again when it finishes, or cancel that send.';
    expect(suppressOwnSendConflict(message, false)).toBe(message);
  });
});
