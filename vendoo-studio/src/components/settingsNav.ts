/** T3 Code-style settings categories for Vendoo Studio. */

export type SettingsSectionId = "general" | "providers" | "integrations" | "connections";

export type SettingsNavItem = {
  id: SettingsSectionId;
  label: string;
};

export type SettingsSearchItem = {
  id: string;
  title: string;
  section: SettingsSectionId;
  /** Optional row/section id to scroll to after navigation. */
  targetId?: string;
  searchTerms?: string[];
};

/** Sidebar order matches T3 Code: General first, then providers/integrations/connections. */
export const SETTINGS_NAV_ITEMS: readonly SettingsNavItem[] = [
  { id: "general", label: "General" },
  { id: "providers", label: "Providers" },
  { id: "integrations", label: "Integrations" },
  { id: "connections", label: "Connections" },
];

export const SETTINGS_SECTION_LABELS: Readonly<Record<SettingsSectionId, string>> = {
  general: "General",
  providers: "Providers",
  integrations: "Integrations",
  connections: "Connections",
};

export const DEFAULT_SETTINGS_SECTION: SettingsSectionId = "general";

export const SETTINGS_SEARCH_ITEMS: readonly SettingsSearchItem[] = [
  {
    id: "marketplaces",
    title: "Marketplaces",
    section: "general",
    targetId: "marketplaces",
    searchTerms: ["list to", "ebay", "poshmark", "mercari", "depop", "etsy"],
  },
  {
    id: "hidden-fields",
    title: "Always hidden fields",
    section: "general",
    targetId: "hidden-fields",
    searchTerms: ["exclude", "hide fields", "fields tab"],
  },
  {
    id: "setup-guide",
    title: "Setup guide",
    section: "general",
    targetId: "setup-guide",
    searchTerms: ["tutorial", "onboarding", "first run", "chatgpt", "mimo", "brave"],
  },
  {
    id: "about-version",
    title: "Version",
    section: "general",
    targetId: "about",
    searchTerms: ["about", "update", "check for updates"],
  },
  {
    id: "chatgpt",
    title: "Sign in with ChatGPT",
    section: "providers",
    targetId: "chatgpt",
    searchTerms: ["openai", "codex", "subscription", "sign out"],
  },
  {
    id: "vision-model",
    title: "Vision model",
    section: "providers",
    targetId: "models",
    searchTerms: ["photo", "image", "multimodal"],
  },
  {
    id: "listing-model",
    title: "Listing model",
    section: "providers",
    targetId: "models",
    searchTerms: ["copy", "write", "pro"],
  },
  {
    id: "reasoning",
    title: "Reasoning",
    section: "providers",
    targetId: "models",
    searchTerms: ["effort", "quota", "thinking"],
  },
  {
    id: "mimo",
    title: "Xiaomi MiMo",
    section: "providers",
    targetId: "provider",
    searchTerms: ["api key", "fallback", "xiaomi"],
  },
  {
    id: "brave",
    title: "Brave Search",
    section: "integrations",
    targetId: "brave",
    searchTerms: ["comps", "sold", "api key", "fallback search"],
  },
  {
    id: "chrome",
    title: "Vendoo in Chrome",
    section: "connections",
    targetId: "connections",
    searchTerms: ["extension", "connect chrome", "browser"],
  },
];

function normalize(text: string): string {
  return text.trim().toLowerCase().replace(/\s+/g, " ");
}

export function searchSettings(query: string, items: readonly SettingsSearchItem[] = SETTINGS_SEARCH_ITEMS): SettingsSearchItem[] {
  const needle = normalize(query);
  if (!needle) return [];
  return items.filter((item) => {
    const haystack = [item.title, ...(item.searchTerms || [])].map(normalize).join(" ");
    return haystack.includes(needle) || needle.split(" ").every((part) => haystack.includes(part));
  });
}

export function isSettingsSectionId(value: string): value is SettingsSectionId {
  return SETTINGS_NAV_ITEMS.some((item) => item.id === value);
}
