import { describe, expect, it } from "vitest";
import { installConfirmationMessage, normalizeDownloadPercent } from "./UpdateButton";

describe("installConfirmationMessage", () => {
  it("puts the PR title in the packaged update dialog title", () => {
    const message = installConfirmationMessage({
      available: true,
      packaged: true,
      summary: "Prompt to pull when Vendoo is saved",
      short_sha: "abc1234",
    });
    expect(message.split("\n")[0]).toBe(
      "Install “Prompt to pull when Vendoo is saved” and restart List This Studio?",
    );
    expect(message).toContain("Build abc1234");
    expect(message).not.toContain("List This Studio (macOS)");
  });

  it("falls back to the sha when there is no summary", () => {
    const message = installConfirmationMessage({
      available: true,
      packaged: true,
      short_sha: "deadbeef",
    });
    expect(message.split("\n")[0]).toBe("Install update deadbeef and restart List This Studio?");
  });

  it("shows every PR included in a packaged update", () => {
    const message = installConfirmationMessage({
      available: true,
      packaged: true,
      summary: "#405 — Keep Connect Chrome paired",
      short_sha: "abc1234",
      commits: [
        "#405 — Keep Connect Chrome paired",
        "#404 — File unisex listings under men",
        "#403 — Match men's bottoms titles to their sizes",
      ],
    });
    expect(message).toContain("#405 — Keep Connect Chrome paired");
    expect(message).toContain("#404 — File unisex listings under men");
    expect(message).toContain("#403 — Match men's bottoms titles to their sizes");
  });
});

describe("normalizeDownloadPercent", () => {
  it("keeps a real percent inside 0–100", () => {
    expect(normalizeDownloadPercent(42.7)).toBe(42.7);
  });

  it("treats missing or invalid values as 0 so the ring can spin", () => {
    expect(normalizeDownloadPercent(null)).toBe(0);
    expect(normalizeDownloadPercent(undefined)).toBe(0);
    expect(normalizeDownloadPercent(Number.NaN)).toBe(0);
  });

  it("clamps out-of-range values", () => {
    expect(normalizeDownloadPercent(-5)).toBe(0);
    expect(normalizeDownloadPercent(150)).toBe(100);
  });
});
