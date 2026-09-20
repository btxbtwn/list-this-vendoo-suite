import { describe, expect, it } from "vitest";
import { statusHint } from "./ListingSidebar";

describe("statusHint", () => {
  it("says where each Vendoo label comes from", () => {
    expect(statusHint("draft")).toBe("Draft in Vendoo");
    expect(statusHint("active")).toBe("Listed on a marketplace, per Vendoo");
    expect(statusHint("sold")).toBe("Sold, per Vendoo");
  });

  it("explains the states Studio itself causes", () => {
    expect(statusHint("failed")).toBe("The last send to Vendoo failed");
    expect(statusHint("listing")).toBe("Studio is sending this listing to Vendoo");
    expect(statusHint("in_progress")).toBe("Studio is working on this listing");
  });

  it("still names Vendoo for a status it does not know", () => {
    expect(statusHint("some_new_state")).toBe("some new state · follows Vendoo");
  });
});
