import { describe, expect, it } from "vitest";
import { parseEvidence } from "./EvidenceCard";

const ANALYSIS = [
  "Photo analysis:",
  "- brand: Manco Arts",
  "- size: L (source: tag)",
  "- color: Black",
  "- category: Tops > T-Shirts",
  "- flaws: Minor lint, Small white speck near the hem",
  '- Pit to pit: 22"',
  '- tag text: brand label "Manco Arts"; size tag "L"',
  "- uncertainties: material, exact year",
].join("\n");

describe("parseEvidence", () => {
  it("splits field lines into label, value, and source", () => {
    const report = parseEvidence(ANALYSIS)!;
    expect(report.fields.map((f) => f.label)).toEqual(["Brand", "Size", "Color", "Category"]);
    expect(report.fields[1]).toEqual({ label: "Size", value: "L", source: "tag" });
    expect(report.fields[0].source).toBeUndefined();
  });

  it("orders the core fields the way the server writes them", () => {
    const report = parseEvidence("Photo analysis:\n- category: Tee\n- brand: Levi's")!;
    expect(report.fields.map((f) => f.label)).toEqual(["Brand", "Category"]);
  });

  it("pulls flaws, tag text, and uncertainties into their own lists", () => {
    const report = parseEvidence(ANALYSIS)!;
    expect(report.flaws).toEqual(["Minor lint", "Small white speck near the hem"]);
    expect(report.tagText).toEqual(['brand label "Manco Arts"', 'size tag "L"']);
    expect(report.uncertainties).toEqual(["material", "exact year"]);
  });

  it("treats unknown numeric lines as measurements", () => {
    const report = parseEvidence(ANALYSIS)!;
    expect(report.measurements).toEqual([{ label: "Pit to pit", value: '22"', source: undefined }]);
  });

  it("returns null when there is nothing to lay out", () => {
    expect(parseEvidence("Photo analysis:")).toBeNull();
    expect(parseEvidence("Photo analysis failed. Retry to analyze the photos again.")).toBeNull();
  });
});
