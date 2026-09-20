import type { MouseEvent } from "react";
import type { WorkspaceCrumbs } from "./workspaceCrumbs";

/** A titlebar click must not start a window drag on the desktop build. */
export function stopTitlebarDrag(event: MouseEvent<HTMLElement>) {
  event.stopPropagation();
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
  /** The listings sidebar is hidden, so the topbar carries the button that brings it back. */
  sidebarCollapsed: boolean;
  onShowSidebar: () => void;
  /** `null` when the view has no inspector to toggle. */
  detailOpen: boolean | null;
  onToggleDetail: () => void;
}

/** The window's top band: breadcrumb on the left, panel toggles on the right. */
export function WorkspaceTopbar({ crumbs, sidebarCollapsed, onShowSidebar, detailOpen, onToggleDetail }: Props) {
  return (
    <header className="workspace-topbar">
      <div className="workspace-topbar-drag pywebview-drag-region" aria-hidden="true" />
      {sidebarCollapsed ? (
        <button
          type="button"
          className="titlebar-control workspace-topbar-sidebar"
          aria-label="Show listings"
          aria-expanded={false}
          aria-controls="listings-sidebar"
          title="Show listings"
          onMouseDown={stopTitlebarDrag}
          onClick={onShowSidebar}
        >
          <PanelLeftIcon />
        </button>
      ) : null}
      <div className="workspace-crumbs">
        <span className="workspace-crumb-context">{crumbs.context}</span>
        {crumbs.title ? (
          <>
            <span className="workspace-crumb-sep" aria-hidden="true">/</span>
            <span className="workspace-crumb-title" title={crumbs.title}>{crumbs.title}</span>
          </>
        ) : null}
      </div>
      {detailOpen === null ? null : (
        <div className="workspace-topbar-actions">
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
        </div>
      )}
    </header>
  );
}
