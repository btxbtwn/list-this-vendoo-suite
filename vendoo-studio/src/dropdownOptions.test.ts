import { describe, expect, it } from "vitest";
import { withDropdownOptions } from "./dropdownOptions";

type Field = { key: string; label: string; options?: string[] };

const FORMS = {
  vendoo: {
    condition: ["New With Tags/Box", "Pre-Owned - Good"],
    usSize: ["S", "M", "L"],
  },
  depop: {
    style: ["Streetwear", "Sportswear"],
  },
  mercari: {
    shippingLabel: ["USPS Ground Advantage / 1 - 7 days / $ 5.66 / 0.5 lb"],
  },
  ebay: {
    department: ["Men", "Teens"],
    Type: ["T-Shirt"],
  },
};

describe("withDropdownOptions", () => {
  it("attaches general condition and size options from the vendoo form", () => {
    const input: Field[] = [
      { key: "condition", label: "Condition" },
      { key: "size", label: "Size" },
      { key: "brand", label: "Brand" },
    ];
    const fields = withDropdownOptions(input, "general", FORMS);
    expect(fields[0].options).toEqual(["New With Tags/Box", "Pre-Owned - Good"]);
    expect(fields[1].options).toEqual(["S", "M", "L"]);
    expect(fields[2].options).toBeUndefined();
  });

  it("matches marketplace field leaves case-insensitively", () => {
    const depopInput: Field[] = [
      { key: "depop_specifics.style", label: "Style" },
      { key: "ebay_specifics.type", label: "Type" },
      { key: "mercari_specifics.shippingLabel", label: "Shipping Label" },
    ];
    const fields = withDropdownOptions(depopInput, "depop", FORMS);
    expect(fields[0].options).toEqual(["Streetwear", "Sportswear"]);

    const ebay = withDropdownOptions(
      [{ key: "ebay_specifics.type", label: "Type" }] as Field[],
      "ebay",
      FORMS,
    );
    expect(ebay[0].options).toEqual(["T-Shirt"]);

    const mercari = withDropdownOptions(
      [{ key: "mercari_specifics.shippingLabel", label: "Shipping Label" }] as Field[],
      "mercari",
      FORMS,
    );
    expect(mercari[0].options?.[0]).toContain("Ground Advantage");
  });

  it("keeps live schema options when already present", () => {
    const fields = withDropdownOptions(
      [{ key: "depop_specifics.style", label: "Style", options: ["Live Only"] }] as Field[],
      "depop",
      FORMS,
    );
    expect(fields[0].options).toEqual(["Live Only"]);
  });
});
