/** What the titlebar breadcrumb reads, T3 Code style: where you are, then what is open. */
export type WorkspaceCrumbs = {
  context: string;
  /** `null` when nothing is open — the breadcrumb then stops at the context. */
  title: string | null;
};

export const LISTINGS_CRUMB = "Inventory";
export const SETTINGS_CRUMB = "Settings";
export const ANALYTICS_CRUMB = "Analytics";
export const UNTITLED_LISTING = "Untitled listing";

export type WorkspaceView = "listings" | "settings" | "analytics";

export function workspaceCrumbs(
  view: WorkspaceView,
  settingsLabel: string,
  listing: { title?: string | null } | null | undefined,
): WorkspaceCrumbs {
  if (view === "settings") {
    return { context: SETTINGS_CRUMB, title: settingsLabel.trim() || null };
  }
  if (view === "analytics") {
    return { context: ANALYTICS_CRUMB, title: null };
  }
  if (!listing) return { context: LISTINGS_CRUMB, title: null };
  return { context: LISTINGS_CRUMB, title: String(listing.title || "").trim() || UNTITLED_LISTING };
}
