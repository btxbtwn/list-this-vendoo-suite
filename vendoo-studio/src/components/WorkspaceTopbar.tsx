import type { MouseEvent } from "react";
import type { WorkspaceCrumbs } from "./workspaceCrumbs";

/** A titlebar click must not start a window drag on the desktop build. */
export function stopTitlebarDrag(event: MouseEvent<HTMLElement>) {
  event.stopPropagation();
}

function TitlebarSettingsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.75" />
    </svg>
  );
}

/* T3 Code's panel toggles are lucide's panel-left-close / panel-left and
   panel-right-close / panel-right: the open panel carries the chevron that
   shows which way it will go. */
const ICON_PROPS = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
} as const;

export function PanelLeftIcon({ open = false }: { open?: boolean }) {
  return (
    <svg {...ICON_PROPS}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18" />
      {open ? <path d="m16 15-3-3 3-3" /> : null}
    </svg>
  );
}

export function PanelRightIcon({ open = false }: { open?: boolean }) {
  return (
    <svg {...ICON_PROPS}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M15 3v18" />
      {open ? <path d="m8 9 3 3-3 3" /> : null}
    </svg>
  );
}

interface Props {
  crumbs: WorkspaceCrumbs;
  /** Listings sidebar is open. */
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  /** `null` when the view has no inspector to toggle. */
  detailOpen: boolean | null;
  onToggleDetail: () => void;
  settingsOpen: boolean;
  onOpenSettings: () => void;
  onCloseSettings: () => void;
}

/** One window-wide titlebar like T3 Code: crumbs left, actions and panel toggles right. */
export function WorkspaceTopbar({
  crumbs,
  sidebarOpen,
  onToggleSidebar,
  detailOpen,
  onToggleDetail,
  settingsOpen,
  onOpenSettings,
  onCloseSettings,
}: Props) {
  return (
    <header className="workspace-topbar">
      <div className="workspace-topbar-drag pywebview-drag-region" aria-hidden="true" />
      <button
        type="button"
        className="titlebar-control"
        aria-label={sidebarOpen ? "Hide listings" : "Show listings"}
        aria-expanded={sidebarOpen}
        aria-controls="listings-sidebar"
        title={sidebarOpen ? "Hide listings" : "Show listings"}
        onMouseDown={stopTitlebarDrag}
        onClick={onToggleSidebar}
      >
        <PanelLeftIcon open={sidebarOpen} />
      </button>
      <div className="workspace-crumbs">
        <span className="workspace-crumb-context">{crumbs.context}</span>
        {crumbs.title ? (
          <>
            <span className="workspace-crumb-sep" aria-hidden="true">/</span>
            <span className="workspace-crumb-title" title={crumbs.title}>{crumbs.title}</span>
          </>
        ) : null}
      </div>
      <div className="workspace-topbar-actions">
        <button
          type="button"
          className="titlebar-control"
          aria-label={settingsOpen ? "Back to listings" : "Settings"}
          aria-pressed={settingsOpen}
          title={settingsOpen ? "Back to listings" : "Settings"}
          onMouseDown={stopTitlebarDrag}
          onClick={settingsOpen ? onCloseSettings : onOpenSettings}
        >
          <TitlebarSettingsIcon />
        </button>
        {detailOpen === null ? null : (
          <button
            type="button"
            className="titlebar-control"
            aria-label={detailOpen ? "Hide the listing inspector" : "Show the listing inspector"}
            aria-expanded={detailOpen}
            aria-controls="listing-inspector"
            title={detailOpen ? "Hide the listing inspector" : "Show the listing inspector"}
            onMouseDown={stopTitlebarDrag}
            onClick={onToggleDetail}
          >
            <PanelRightIcon open={detailOpen} />
          </button>
        )}
      </div>
    </header>
  );
}
