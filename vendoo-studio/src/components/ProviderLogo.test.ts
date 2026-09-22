import { describe, expect, it } from "vitest";
import { hasProviderLogo, providerLogoColor, resolveProviderLogoId } from "./ProviderLogo";
import { PROVIDER_LOGOS } from "./providerLogos";
import { providerStatusModelLabel } from "./ProviderStatus";

describe("ProviderLogo", () => {
  it("ships brand marks for ChatGPT, MiMo, and Cursor", () => {
    for (const id of ["chatgpt", "mimo", "cursor"] as const) {
      expect(hasProviderLogo(id)).toBe(true);
      expect(PROVIDER_LOGOS[id].paths.length).toBeGreaterThan(0);
      expect(PROVIDER_LOGOS[id].viewBox).toMatch(/^\d/);
    }
  });

  it("keeps brand fills on provider logos", () => {
    expect(providerLogoColor("chatgpt")).toBe("#10A37F");
    expect(providerLogoColor("mimo")).toBe("#FF6900");
    expect(providerLogoColor("cursor")).toBe("#000000");
  });

  it("maps API provider names to logo ids", () => {
    expect(resolveProviderLogoId("chatgpt")).toBe("chatgpt");
    expect(resolveProviderLogoId("xiaomi-mimo")).toBe("mimo");
    expect(resolveProviderLogoId("mimo")).toBe("mimo");
    expect(resolveProviderLogoId("cursor")).toBe("cursor");
    expect(resolveProviderLogoId("unknown")).toBeNull();
  });

  it("falls back for unknown providers", () => {
    expect(hasProviderLogo("unknown-provider")).toBe(false);
    expect(providerLogoColor("unknown-provider")).toBe("#5C6578");
  });
});

describe("providerStatusModelLabel", () => {
  it("shows the listing model when configured", () => {
    expect(providerStatusModelLabel(true, "gpt-5.5")).toBe("gpt-5.5");
    expect(providerStatusModelLabel(true, "  composer-2.5  ")).toBe("composer-2.5");
  });

  it("falls back when the model is missing", () => {
    expect(providerStatusModelLabel(true, "")).toBe("listing model");
    expect(providerStatusModelLabel(true, null)).toBe("listing model");
  });

  it("reports not configured when the provider is offline", () => {
    expect(providerStatusModelLabel(false, "gpt-5.5")).toBe("Not configured");
  });
});
