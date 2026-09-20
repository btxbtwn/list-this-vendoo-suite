import { describe, expect, it } from "vitest";
import { SUGGESTION_KIND_LABELS, suggestionKindLabel } from "./SuggestionsPanel";

describe("suggestionKindLabel", () => {
  it("names the next step for every ranked kind", () => {
    expect(suggestionKindLabel("failed")).toBe("Fix failed listing");
    expect(suggestionKindLabel("ready_to_generate")).toBe("Generate listing");
    expect(suggestionKindLabel("fix_validation")).toBe("Fix listing fields");
    expect(suggestionKindLabel("stale_active")).toBe("Refresh or consider price drop");
    expect(suggestionKindLabel("ready_to_review")).toBe("Review and send");
  });

  it("covers every kind the API can return", () => {
    expect(Object.keys(SUGGESTION_KIND_LABELS).sort()).toEqual([
      "failed",
      "fix_validation",
      "ready_to_generate",
      "ready_to_review",
      "stale_active",
    ]);
  });
});
