import { describe, expect, it } from "vitest";
import { checkedAgo } from "./VendooSyncStatus";

describe("checkedAgo", () => {
  const now = Date.parse("2026-09-19T12:00:00Z");

  it("says just now inside a minute", () => {
    expect(checkedAgo("2026-09-19T11:59:30Z", now)).toBe("just now");
  });

  it("counts minutes, then hours", () => {
    expect(checkedAgo("2026-09-19T11:55:00Z", now)).toBe("5m ago");
    expect(checkedAgo("2026-09-19T09:00:00Z", now)).toBe("3h ago");
  });

  it("returns nothing for an unreadable stamp", () => {
    expect(checkedAgo("soon", now)).toBe("");
  });
});
