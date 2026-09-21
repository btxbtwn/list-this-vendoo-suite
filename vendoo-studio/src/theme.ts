/** Studio appearance: dark shell by default, optional light, or follow the OS. */

export type ThemePreference = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

export const THEME_STORAGE_KEY = "vendoo-studio:theme";
export const DEFAULT_THEME: ThemePreference = "dark";

const LIGHT_THEME_COLOR = "#f4f4f5";
const DARK_THEME_COLOR = "#0a0a0a";

export function normalizeTheme(value: unknown): ThemePreference {
  if (value === "light" || value === "dark" || value === "system") return value;
  return DEFAULT_THEME;
}

export function resolveTheme(
  preference: ThemePreference,
  prefersLight = typeof window !== "undefined"
    ? window.matchMedia("(prefers-color-scheme: light)").matches
    : false,
): ResolvedTheme {
  if (preference === "light" || preference === "dark") return preference;
  return prefersLight ? "light" : "dark";
}

export function readCachedTheme(): ThemePreference {
  try {
    return normalizeTheme(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_THEME;
  }
}

export function cacheTheme(preference: ThemePreference): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    /* private mode / quota — live apply still works */
  }
}

function setMeta(name: string, content: string): void {
  const meta = document.querySelector(`meta[name="${name}"]`);
  if (meta) meta.setAttribute("content", content);
}

/** Paint `data-theme` and related chrome from a preference (or its cache). */
export function applyTheme(preference: ThemePreference = readCachedTheme()): ResolvedTheme {
  const resolved = resolveTheme(preference);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  setMeta("theme-color", resolved === "light" ? LIGHT_THEME_COLOR : DARK_THEME_COLOR);
  setMeta("color-scheme", resolved);
  cacheTheme(preference);
  return resolved;
}
