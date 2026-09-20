import { describe, expect, it } from "vitest";
import {
  SUGGESTION_KIND_LABELS,
  staleAgeLabel,
  suggestionCaption,
  suggestionKindLabel,
} from "./SuggestionsPanel";

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

describe("suggestionCaption", () => {
  it("puts listed age first on compact stale rows", () => {
    expect(staleAgeLabel(1)).toBe("1 day");
    expect(staleAgeLabel(47)).toBe("47 days");
    expect(suggestionCaption({ kind: "stale_active", age_days: 47 }, true)).toBe(
      "47 days · Refresh or consider price drop",
    );
    expect(suggestionCaption({ kind: "stale_active", age_days: 47 }, false)).toBe(
      "Refresh or consider price drop",
    );
  });

  it("leaves other compact kinds unchanged", () => {
    expect(suggestionCaption({ kind: "fix_validation", age_days: null }, true)).toBe(
      "Fix listing fields",
    );
  });
});
