import { describe, expect, it } from "vitest";
import { hasOpenJob } from "./polling";

describe("hasOpenJob", () => {
  it("is true only while a send is still moving", () => {
    expect(hasOpenJob(undefined)).toBe(false);
    expect(hasOpenJob([{ status: "completed" }, { status: "failed" }, { status: "cancelled" }])).toBe(false);
    expect(hasOpenJob([{ status: "completed" }, { status: "dispatched" }])).toBe(true);
    expect(hasOpenJob([{ status: "awaiting_extension" }])).toBe(true);
  });
});
