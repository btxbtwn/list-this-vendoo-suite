import { describe, expect, it } from "vitest";
import { sendProgressLabel } from "./SendProgress";

describe("sendProgressLabel", () => {
  it("reports queue waiting without invented completion", () => {
    expect(sendProgressLabel("vendoo_api_queued")).toBe("Waiting in the send queue…");
  });

  it("names the draft read that opens Update Vendoo", () => {
    expect(sendProgressLabel("vendoo_api_read")).toBe("Reading the Vendoo draft…");
  });

  it("reports measured successful photo uploads", () => {
    expect(sendProgressLabel("vendoo_api_photos", { completed: 3, total: 8 })).toBe("3 of 8 photos uploaded");
    expect(sendProgressLabel("vendoo_api_photos")).toBe("Uploading photos to Vendoo…");
  });

  it("does not display old photo counts while verifying the draft", () => {
    expect(sendProgressLabel("vendoo_api_verify", { completed: 8, total: 8 })).toBe("Checking the saved Vendoo draft…");
  });
});
