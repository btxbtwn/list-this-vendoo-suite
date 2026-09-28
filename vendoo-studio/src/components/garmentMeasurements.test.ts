import { describe, expect, it } from "vitest";
import { guessGarment, notesWithMeasurements, typedMeasurements } from "./garmentMeasurements";

describe("guessGarment", () => {
  it("reads pants from the folder name and defaults to a top", () => {
    expect(guessGarment("Levi's 505 Jeans")).toBe("pants");
    expect(guessGarment("nike shorts 2")).toBe("pants");
    expect(guessGarment("Harley tee")).toBe("top");
    expect(guessGarment("Jeanswear logo hoodie")).toBe("top");
  });
});

describe("typedMeasurements", () => {
  it("keeps the garment's own filled fields only", () => {
    expect(typedMeasurements("top", { pitToPit: " 22.5 ", length: "", waist: "16" })).toEqual({ pitToPit: "22.5" });
  });
});

describe("notesWithMeasurements", () => {
  it("adds the garment and measurements without losing bulk details", () => {
    const notes = notesWithMeasurements(
      JSON.stringify({ cog: "4", vendooLabels: "Bin 4" }),
      "pants",
      { waist: "16", inseam: "30", pitToPit: "22" },
    );
    expect(JSON.parse(notes)).toEqual({
      cog: "4",
      vendooLabels: "Bin 4",
      garment: "pants",
      measurements: { pants: { waist: "16", inseam: "30" } },
    });
  });

  it("starts from empty notes and keeps the other garment's saved set", () => {
    expect(JSON.parse(notesWithMeasurements(null, "top", { length: "27" }))).toEqual({
      garment: "top",
      measurements: { top: { length: "27" } },
    });
    const saved = JSON.stringify({ garment: "pants", measurements: { pants: { waist: "15" } } });
    expect(JSON.parse(notesWithMeasurements(saved, "top", { length: "27" })).measurements).toEqual({
      pants: { waist: "15" },
      top: { length: "27" },
    });
  });
});
