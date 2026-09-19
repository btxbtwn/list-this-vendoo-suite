import { describe, expect, it } from "vitest";
import { installConfirmationMessage } from "./UpdateButton";

describe("installConfirmationMessage", () => {
  it("puts the PR title in the packaged update dialog title", () => {
    const message = installConfirmationMessage({
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
      packaged: true,
      short_sha: "deadbeef",
    });
    expect(message.split("\n")[0]).toBe("Install update deadbeef and restart List This Studio?");
  });
});
