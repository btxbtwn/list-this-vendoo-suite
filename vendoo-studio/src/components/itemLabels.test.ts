import { describe, expect, it } from "vitest";
import { addLabel, joinLabels, removeLabel, splitLabels } from "./itemLabels";

describe("splitLabels / joinLabels", () => {
  it("splits and trims comma-separated labels", () => {
    expect(splitLabels(" vintage , thrift, ,NWT ")).toEqual(["vintage", "thrift", "NWT"]);
  });

  it("round-trips joined labels", () => {
    expect(joinLabels(["vintage", "NWT"])).toBe("vintage, NWT");
    expect(splitLabels(joinLabels(["a", "b"]))).toEqual(["a", "b"]);
  });
});

describe("addLabel", () => {
  it("appends a new label", () => {
    expect(addLabel("vintage", "NWT")).toBe("vintage, NWT");
  });

  it("ignores duplicates case-insensitively", () => {
    expect(addLabel("Vintage, NWT", "vintage")).toBe("Vintage, NWT");
  });

  it("ignores blank additions", () => {
    expect(addLabel("vintage", "  ")).toBe("vintage");
  });
});

describe("removeLabel", () => {
  it("removes a matching label case-insensitively", () => {
    expect(removeLabel("vintage, NWT, thrift", "nwt")).toBe("vintage, thrift");
  });

  it("leaves the string unchanged when the label is missing", () => {
    expect(removeLabel("vintage, NWT", "thrift")).toBe("vintage, NWT");
  });

  it("clears the last remaining label", () => {
    expect(removeLabel("vintage", "Vintage")).toBe("");
  });
});
