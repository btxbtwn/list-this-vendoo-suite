import { describe, expect, it } from "vitest";
import { DEFAULT_THEME, normalizeTheme, resolveTheme } from "./theme";

describe("normalizeTheme", () => {
  it("accepts dark, light, and system", () => {
    expect(normalizeTheme("dark")).toBe("dark");
    expect(normalizeTheme("light")).toBe("light");
    expect(normalizeTheme("system")).toBe("system");
  });

  it("falls back to dark for unknown values", () => {
    expect(normalizeTheme(undefined)).toBe(DEFAULT_THEME);
    expect(normalizeTheme("solarized")).toBe(DEFAULT_THEME);
    expect(normalizeTheme(1)).toBe(DEFAULT_THEME);
  });
});

describe("resolveTheme", () => {
  it("returns an explicit preference unchanged", () => {
    expect(resolveTheme("light", false)).toBe("light");
    expect(resolveTheme("dark", true)).toBe("dark");
  });

  it("follows the system preference when set to system", () => {
    expect(resolveTheme("system", true)).toBe("light");
    expect(resolveTheme("system", false)).toBe("dark");
  });
});
