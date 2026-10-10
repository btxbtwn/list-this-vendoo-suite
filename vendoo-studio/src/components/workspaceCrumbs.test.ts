import { describe, expect, it } from "vitest";
import { workspaceCrumbs } from "./workspaceCrumbs";

describe("workspaceCrumbs", () => {
  it("stops at the context when no listing is open", () => {
    expect(workspaceCrumbs("listings", "Providers", null)).toEqual({ context: "Inventory", title: null });
  });

  it("names the open listing", () => {
    expect(workspaceCrumbs("listings", "Providers", { title: "REI XL Outdoor Fleece" })).toEqual({
      context: "Inventory",
      title: "REI XL Outdoor Fleece",
    });
  });

  it("falls back for a listing with no title yet", () => {
    expect(workspaceCrumbs("listings", "Providers", { title: "   " }).title).toBe("Untitled listing");
    expect(workspaceCrumbs("listings", "Providers", {}).title).toBe("Untitled listing");
  });

  it("reads the settings section in the settings view", () => {
    expect(workspaceCrumbs("settings", "Providers", { title: "REI XL" })).toEqual({
      context: "Settings",
      title: "Providers",
    });
  });

  it("stops at Settings when the section has no label", () => {
    expect(workspaceCrumbs("settings", "", null)).toEqual({ context: "Settings", title: null });
  });

  it("reads Sourcing with nothing open under it", () => {
    expect(workspaceCrumbs("sourcing", "Providers", { title: "REI XL" })).toEqual({
      context: "Sourcing",
      title: null,
    });
  });

  it("reads Analytics with nothing open under it", () => {
    expect(workspaceCrumbs("analytics", "Providers", { title: "REI XL" })).toEqual({
      context: "Analytics",
      title: null,
    });
  });

  it("reads Marketing with nothing open under it", () => {
    expect(workspaceCrumbs("marketing", "Providers", { title: "REI XL" })).toEqual({
      context: "Marketing",
      title: null,
    });
  });

  it("reads Assistant with nothing open under it", () => {
    expect(workspaceCrumbs("assistant", "Providers", { title: "REI XL" })).toEqual({
      context: "Assistant",
      title: null,
    });
  });
});
