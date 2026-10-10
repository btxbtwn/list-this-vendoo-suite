import { describe, expect, it } from "vitest";
import { frontendBuildState, reloadForBackend } from "./buildStamp";

const build = { version: "0.1.46", short_sha: "1a4b581" };

describe("frontendBuildState", () => {
  it("reports the version the bundle was built from", () => {
    expect(frontendBuildState(build, "0.1.46")).toMatchObject({
      version: "0.1.46",
      outdated: false,
      label: "V 0.1.46",
      title: undefined,
    });
  });

  it("flags a bundle the backend has moved past", () => {
    // The reported bug: status bar read 0.1.45 while the UI was two builds old.
    const state = frontendBuildState({ version: "0.1.44", short_sha: "c007163" }, "0.1.45");
    expect(state.outdated).toBe(true);
    expect(state.label).toBe("V 0.1.44 (stale)");
    expect(state.title).toContain("0.1.44");
    expect(state.title).toContain("0.1.45");
  });

  it("reloads once per backend version, never in a loop", () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    expect(reloadForBackend("", storage)).toBe(false);
    expect(reloadForBackend("0.1.222", storage)).toBe(true);
    expect(reloadForBackend("0.1.222", storage)).toBe(false);
    expect(reloadForBackend("0.1.223", storage)).toBe(true);
  });

  it("stays quiet until the backend has answered", () => {
    for (const backend of [null, undefined, ""]) {
      expect(frontendBuildState(build, backend).outdated).toBe(false);
    }
    expect(frontendBuildState(build, null).label).toBe("V 0.1.46");
  });
});
