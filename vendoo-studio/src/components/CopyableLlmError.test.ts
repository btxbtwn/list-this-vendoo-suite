import { describe, expect, it } from "vitest";
import { emptyFieldsButtonLabel } from "./CopyableLlmError";

describe("emptyFieldsButtonLabel", () => {
  it("pluralizes empty field counts", () => {
    expect(emptyFieldsButtonLabel(0)).toBe("Ask chat for fields");
    expect(emptyFieldsButtonLabel(1)).toBe("Ask chat for 1 field");
    expect(emptyFieldsButtonLabel(3)).toBe("Ask chat for 3 fields");
  });

  it("treats invalid counts as zero", () => {
    expect(emptyFieldsButtonLabel(Number.NaN)).toBe("Ask chat for fields");
    expect(emptyFieldsButtonLabel(-2)).toBe("Ask chat for fields");
  });
});
