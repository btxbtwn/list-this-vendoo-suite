import { describe, expect, it } from "vitest";
import {
  emptyFieldsButtonLabel,
  jobErrorPrompt,
  validationErrorsPrompt,
} from "./CopyableLlmError";

const FORMS = {
  depop: {
    material: ["Cotton", "Denim", "Faux leather", "Wool"],
    style: ["Streetwear", "Y2K"],
  },
  etsy: { whatIsIt: ["A finished product", "A supply or tool to make things"] },
  vendoo: { condition: ["New With Tags/Box", "Pre-Owned - Good"] },
};

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

describe("fix-errors prompts", () => {
  it("lists the Depop dropdown options for a rejected value", () => {
    const prompt = validationErrorsPrompt(
      [{
        field: "depop_specifics.material",
        message: "Depop material 'Other' is not a current dropdown value",
      }],
      "Vintage tee",
      FORMS,
    );
    expect(prompt).toContain("depop / material");
    expect(prompt).toContain("Cotton | Denim | Faux leather | Wool");
    expect(prompt).toContain("verbatim");
  });

  it("resolves snake_case validation fields onto camelCase dropdown keys", () => {
    const prompt = validationErrorsPrompt(
      [{ field: "etsy_specifics.what_is", message: "Etsy what-is is not a current dropdown value" }],
      "Vintage tee",
      FORMS,
    );
    expect(prompt).toContain("A finished product | A supply or tool to make things");
  });

  it("maps general fields onto the Vendoo list", () => {
    const prompt = validationErrorsPrompt(
      [{ field: "condition", message: "Condition is required" }],
      "Vintage tee",
      FORMS,
    );
    expect(prompt).toContain("New With Tags/Box | Pre-Owned - Good");
  });

  it("attaches options to fields parsed out of a job error", () => {
    const prompt = jobErrorPrompt(
      "Vendoo rejected depop / material, depop / style.",
      "Vintage tee",
      null,
      FORMS,
    );
    expect(prompt).toContain("Cotton | Denim | Faux leather | Wool");
    expect(prompt).toContain("Streetwear | Y2K");
  });

  it("stays quiet when no dropdown list is known", () => {
    const prompt = validationErrorsPrompt(
      [{ field: "ebay_specifics.brand", message: "Brand is required" }],
      "Vintage tee",
      FORMS,
    );
    expect(prompt).not.toContain("options (use only these");
  });

  it("leaves prompts unchanged when the option lists have not loaded", () => {
    const prompt = validationErrorsPrompt(
      [{ field: "depop_specifics.material", message: "Depop material is required" }],
      "Vintage tee",
    );
    expect(prompt).toContain("depop / material");
    expect(prompt).not.toContain("options (use only these");
  });
});
