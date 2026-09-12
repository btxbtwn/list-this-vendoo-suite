import React, { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ExtensionStatus } from "../components/ExtensionStatus";
import { ProviderStatus } from "../components/ProviderStatus";
import { ListingEditor } from "../components/ListingEditor";
import { ChatPanel } from "../components/ChatPanel";
import { PhotoTray } from "../components/PhotoTray";
import { SettingsPage } from "../components/SettingsPage";
import { ItemDetails } from "../components/ItemDetails";
import { BrowserPreview } from "../components/BrowserPreview";
import { BackIcon, ComposeIcon, HamburgerIcon, ListingSidebar, SearchIcon } from "../components/ListingSidebar";
import { ConfirmDialogHost } from "../components/ConfirmDialogHost";
import { ToastHost } from "../components/ToastHost";
import { isConfirmDialogOpen } from "../ui/confirmDialog";

const PREVIEW_JOB_STATUSES = new Set(["queued", "awaiting_extension", "dispatched"]);
const MOBILE_LAYOUT_QUERY = "(max-width: 900px)";

function useMobileLayout() {
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(MOBILE_LAYOUT_QUERY).matches);
  useEffect(() => {
    const media = window.matchMedia(MOBILE_LAYOUT_QUERY);
    const onChange = () => setIsMobile(media.matches);
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return isMobile;
}

export function App() {
  const queryClient = useQueryClient();
  const isMobile = useMobileLayout();
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"listings" | "settings">("listings");
  const [mobilePane, setMobilePane] = useState<"workspace" | "editor" | "browser">("workspace");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(() => window.matchMedia(MOBILE_LAYOUT_QUERY).matches);
  const [listingQuery, setListingQuery] = useState("");
  const wasPreviewOpen = useRef(false);

  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.conversations.list,
    refetchInterval: 2000,
  });
  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs.list,
    refetchInterval: 2000,
  });
  const listingJob = jobs?.find((job: any) => job.conversation_id === selectedConvId && job.status !== "cancelled");
  const previewOpen = Boolean(listingJob && PREVIEW_JOB_STATUSES.has(String(listingJob.status)));

  const selectedListing = conversations?.find((listing: { id: string }) => listing.id === selectedConvId);
  const workspaceTitle = activeView === "settings"
    ? "Settings"
    : String(selectedListing?.title || "Vendoo Studio");

  useEffect(() => {
    if (wasPreviewOpen.current && !previewOpen && mobilePane === "browser") {
      setMobilePane("workspace");
    }
    wasPreviewOpen.current = previewOpen;
  }, [previewOpen, mobilePane]);

  useEffect(() => {
    if (!isMobile) setMobileSidebarOpen(false);
  }, [isMobile]);

  useEffect(() => {
    if (!isMobile || !mobileSidebarOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileSidebarOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isMobile, mobileSidebarOpen]);

  useEffect(() => {
    if (activeView !== "settings") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || isConfirmDialogOpen()) return;
      if (isMobile && mobileSidebarOpen) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)
      ) {
        return;
      }
      setActiveView("listings");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeView, isMobile, mobileSidebarOpen]);

  const closeMobileSidebar = () => setMobileSidebarOpen(false);
  const showMailToolbar = isMobile && activeView === "listings" && mobileSidebarOpen;

  const handleListingSearch = (value: string) => {
    setListingQuery(value);
    if (isMobile) setMobileSidebarOpen(true);
  };

  const createConv = useMutation({
    mutationFn: () => api.conversations.create({ title: "New Listing" }),
    onSuccess: (conv) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setSelectedConvId(conv.id);
      setActiveView("listings");
      setMobilePane("workspace");
      setMobileSidebarOpen(false);
    },
  });

  const cancelJob = useMutation({
    mutationFn: (jobId: string) => api.jobs.cancel(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const deleteConv = useMutation({
    mutationFn: (convId: string) => api.conversations.delete(convId),
    onSuccess: (_data, convId) => {
      if (selectedConvId === convId) {
        setSelectedConvId(null);
        setMobilePane("workspace");
        if (isMobile) setMobileSidebarOpen(true);
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <div className="app-shell">
      <div className={`app-content mobile-pane-${mobilePane}${mobileSidebarOpen ? " mobile-sidebar-open" : ""}`}>
        <ListingSidebar
          conversations={conversations}
          selectedConvId={selectedConvId}
          activeView={activeView}
          creating={createConv.isPending}
          mobileOpen={!isMobile || mobileSidebarOpen}
          listingQuery={listingQuery}
          onSearchQueryChange={handleListingSearch}
          onSelect={(id) => { setSelectedConvId(id); setActiveView("listings"); setMobilePane("workspace"); closeMobileSidebar(); }}
          onCreate={() => createConv.mutate()}
          onDelete={(id) => deleteConv.mutate(id)}
          onOpenSettings={() => { setActiveView("settings"); setMobilePane("workspace"); closeMobileSidebar(); }}
          onCloseSettings={() => setActiveView("listings")}
        />

        <div className="workspace-frame">
          <header className="mobile-workspace-bar">
            <button
              type="button"
              className="sidebar-icon-btn sidebar-toggle"
              aria-label="Back to listings"
              onClick={() => setMobileSidebarOpen(true)}
            >
              <BackIcon />
            </button>
            <div className="mobile-workspace-title">{workspaceTitle}</div>
            <div className="mobile-workspace-panes" role="tablist" aria-label="Workspace views">
              <button
                type="button"
                role="tab"
                aria-selected={mobilePane === "workspace"}
                className={mobilePane === "workspace" ? "selected" : ""}
                onClick={() => setMobilePane("workspace")}
              >
                Workspace
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mobilePane === "editor"}
                className={mobilePane === "editor" ? "selected" : ""}
                disabled={activeView !== "listings" || !selectedConvId}
                onClick={() => setMobilePane("editor")}
              >
                Listing
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mobilePane === "browser"}
                className={mobilePane === "browser" ? "selected" : ""}
                disabled={activeView !== "listings" || !selectedConvId || !previewOpen}
                onClick={() => setMobilePane("browser")}
              >
                Browser
              </button>
            </div>
          </header>
          <main className="panel main-panel">
            <div className="workspace-drag-region pywebview-drag-region" aria-hidden="true" />
            {activeView === "settings" ? (
              <SettingsPage />
            ) : selectedConvId ? (
              <div className="listing-workspace">
                <div className="listing-workspace-main">
                  <PhotoTray convId={selectedConvId} />
                  <ItemDetails convId={selectedConvId} />
                  <div className="chat-column">
                    <ChatPanel convId={selectedConvId} />
                  </div>
                </div>
                {previewOpen && (
                  <BrowserPreview
                    jobId={listingJob?.id ?? null}
                    step={listingJob?.current_step}
                    status={listingJob?.status}
                    cancelling={cancelJob.isPending}
                    onCancel={listingJob?.id ? () => cancelJob.mutate(listingJob.id) : undefined}
                  />
                )}
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-state-headline">Turn product photos<br />into marketplace-ready drafts.</div>
                <div className="empty-state-rule" />
                <button className="btn btn-primary btn-sm" style={{ marginTop: 8 }} onClick={() => createConv.mutate()}>
                  Create a listing
                </button>
              </div>
            )}
          </main>

          {activeView !== "settings" && (
            <aside className="panel detail-panel">
              {selectedConvId ? (
                <ListingEditor convId={selectedConvId} onJobStarted={() => setMobilePane("browser")} />
              ) : (
                <div className="empty-state">
                  <p className="text-xs text-muted font-mono">Select a listing to inspect</p>
                </div>
              )}
            </aside>
          )}
        </div>
      </div>

      {showMailToolbar && (
        <nav className="mobile-mail-toolbar" aria-label="Search and create listings">
          <button
            type="button"
            className="mobile-mail-btn"
            aria-label={mobileSidebarOpen ? "Close listings" : "Open listings"}
            aria-expanded={mobileSidebarOpen}
            aria-controls="listings-sidebar"
            onClick={() => setMobileSidebarOpen((open) => !open)}
          >
            <HamburgerIcon />
          </button>
          <label className="mobile-mail-search">
            <SearchIcon />
            <input
              type="search"
              value={listingQuery}
              onChange={(e) => handleListingSearch(e.target.value)}
              placeholder="Search"
              aria-label="Search listings"
            />
          </label>
          <button
            type="button"
            className="mobile-mail-btn"
            title="New listing"
            aria-label="New listing"
            disabled={createConv.isPending}
            onClick={() => createConv.mutate()}
          >
            <ComposeIcon />
          </button>
        </nav>
      )}
      <footer className="status-bar">
        <div className="status-left">
          <ExtensionStatus />
          <ProviderStatus />
        </div>
        <div>V 0.1.0</div>
      </footer>
      <ToastHost />
      <ConfirmDialogHost />
    </div>
  );
}
