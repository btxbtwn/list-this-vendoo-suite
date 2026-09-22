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
    id: "appearance",
    title: "Theme",
    section: "general",
    targetId: "appearance",
    searchTerms: ["appearance", "light mode", "dark mode", "system", "color scheme"],
  },
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
    id: "listing-formulas",
    title: "Title and description formulas",
    section: "general",
    targetId: "listing-formulas",
    searchTerms: ["formula", "title", "description", "template", "flaws", "measurements"],
  },
  {
    id: "setup-guide",
    title: "Setup guide",
    section: "general",
    targetId: "setup-guide",
    searchTerms: ["tutorial", "onboarding", "first run", "chatgpt", "mimo", "cursor", "brave"],
  },
  {
    id: "backups",
    title: "Backups",
    section: "general",
    targetId: "backups",
    searchTerms: ["backup", "snapshot", "restore", "lose data", "external drive", "copy", "sqlite"],
  },
  {
    id: "data-folder",
    title: "Data folder",
    section: "general",
    targetId: "data-folder",
    searchTerms: ["backup", "reinstall", "photos", "sqlite", "application support", "preserve"],
  },
  {
    id: "about-version",
    title: "Version",
    section: "general",
    targetId: "about",
    searchTerms: ["about", "update", "check for updates"],
  },
  {
    id: "whats-new",
    title: "What's new",
    section: "general",
    targetId: "about",
    searchTerms: ["changelog", "release notes", "history", "changes", "what changed"],
  },
  {
    id: "listing-ai",
    title: "Listing AI",
    section: "providers",
    targetId: "listing-ai",
    searchTerms: ["chatgpt", "mimo", "cursor", "provider", "choose", "prefer", "primary", "fallback"],
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
    id: "cursor",
    title: "Cursor",
    section: "providers",
    targetId: "cursor",
    searchTerms: ["cursor", "composer", "api key", "sdk"],
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
  {
    id: "tailscale-https",
    title: "Tailscale HTTPS",
    section: "connections",
    targetId: "tailscale-https",
    searchTerms: ["mobile", "phone", "remote", "tailnet", "serve", "network"],
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
