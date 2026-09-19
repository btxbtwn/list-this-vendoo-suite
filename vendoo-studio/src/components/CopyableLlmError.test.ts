import { describe, expect, it } from "vitest";
import { emptyFieldsButtonLabel } from "./CopyableLlmError";

describe("emptyFieldsButtonLabel", () => {
  it("pluralizes empty field counts", () => {
    expect(emptyFieldsButtonLabel(0)).toBe("Fill 0 empty fields");
    expect(emptyFieldsButtonLabel(1)).toBe("Fill 1 empty field");
    expect(emptyFieldsButtonLabel(3)).toBe("Fill 3 empty fields");
  });

  it("treats invalid counts as zero", () => {
    expect(emptyFieldsButtonLabel(Number.NaN)).toBe("Fill 0 empty fields");
    expect(emptyFieldsButtonLabel(-2)).toBe("Fill 0 empty fields");
  });
});
