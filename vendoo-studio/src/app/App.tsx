import React, { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ExtensionStatus } from "../components/ExtensionStatus";
import { ProviderStatus } from "../components/ProviderStatus";
import { ListingEditor } from "../components/ListingEditor";
import { ChatPanel } from "../components/ChatPanel";
import { PhotoTray } from "../components/PhotoTray";
import { SettingsPage } from "../components/SettingsPage";
import { SetupChecklist } from "../components/SetupChecklist";
import { FirstRunGuide } from "../components/FirstRunGuide";
import { ItemDetails } from "../components/ItemDetails";
import { BrowserPreview } from "../components/BrowserPreview";
import { BackIcon, ComposeIcon, HamburgerIcon, ListingSidebar, SearchIcon } from "../components/ListingSidebar";
import {
  DEFAULT_SETTINGS_SECTION,
  SETTINGS_SECTION_LABELS,
  type SettingsSearchItem,
  type SettingsSectionId,
} from "../components/settingsNav";
import { ConfirmDialogHost } from "../components/ConfirmDialogHost";
import { ToastHost } from "../components/ToastHost";
import { isConfirmDialogOpen } from "../ui/confirmDialog";
import { dismissSetupGuide, isSetupGuideDismissed } from "../onboarding";

const PREVIEW_JOB_STATUSES = new Set(["queued", "awaiting_extension", "dispatched"]);
const MOBILE_LAYOUT_QUERY = "(max-width: 900px)";
let setupGuideAutoOpen: boolean | null = null;

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
  const [selectedConvId, setSelectedConvId] = useState<string | null>(() => {
    const listingId = new URLSearchParams(window.location.search).get("listing");
    return listingId || null;
  });
  const [activeView, setActiveView] = useState<"listings" | "settings">("listings");
  const [settingsSection, setSettingsSection] = useState<SettingsSectionId>(DEFAULT_SETTINGS_SECTION);
  const [settingsTargetId, setSettingsTargetId] = useState<string | null>(null);
  const [mobilePane, setMobilePane] = useState<"workspace" | "editor" | "browser">("workspace");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(() => window.matchMedia(MOBILE_LAYOUT_QUERY).matches);
  const [listingQuery, setListingQuery] = useState("");
  const [queuedChatMessage, setQueuedChatMessage] = useState<string | null>(null);
  const [setupGuideOpen, setSetupGuideOpen] = useState(setupGuideAutoOpen === true);
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
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 4000,
  });
  const providerConfigured = Boolean(status?.provider_configured);
  const needsSetup = !status || !status.provider_configured || !status.extension_connected;
  const createListingTitle = "New listing";
  const listingJob = jobs?.find((job: any) => job.conversation_id === selectedConvId && job.status !== "cancelled");
  const previewOpen = Boolean(listingJob && PREVIEW_JOB_STATUSES.has(String(listingJob.status)));

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (!params.get("listing")) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("listing");
    const next = url.pathname + url.search + url.hash;
    window.history.replaceState({}, "", next);
  }, []);

  useEffect(() => {
    if (setupGuideAutoOpen !== null) return;
    if (isSetupGuideDismissed()) {
      setupGuideAutoOpen = false;
      dismissSetupGuide();
      return;
    }
    if (!status) return;
    if (status.setup_guide_dismissed || status.provider_configured || (status.conversations ?? 0) > 0) {
      setupGuideAutoOpen = false;
      dismissSetupGuide();
      return;
    }
    setupGuideAutoOpen = true;
    setSetupGuideOpen(true);
    dismissSetupGuide();
  }, [status]);

  const selectedListing = conversations?.find((listing: { id: string }) => listing.id === selectedConvId);
  const workspaceTitle = activeView === "settings"
    ? SETTINGS_SECTION_LABELS[settingsSection]
    : String(selectedListing?.title || "Vendoo Studio");

  const closeMobileSidebar = () => setMobileSidebarOpen(false);

  const openSettings = () => {
    setSettingsSection(DEFAULT_SETTINGS_SECTION);
    setSettingsTargetId(null);
    setActiveView("settings");
    setMobilePane("workspace");
    closeMobileSidebar();
  };

  const closeSettings = () => {
    setActiveView("listings");
    setSettingsTargetId(null);
  };

  const handleSettingsSectionChange = (section: SettingsSectionId) => {
    setSettingsSection(section);
    setSettingsTargetId(null);
  };

  const handleSettingsSearchResult = (item: SettingsSearchItem) => {
    setSettingsSection(item.section);
    setSettingsTargetId(item.targetId || item.id);
  };

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
      closeSettings();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeView, isMobile, mobileSidebarOpen]);

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
  const createListing = () => {
    if (createConv.isPending) return false;
    createConv.mutate();
    return true;
  };

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
          settingsSection={settingsSection}
          creating={createConv.isPending}
          canCreate={true}
          mobileOpen={!isMobile || mobileSidebarOpen}
          listingQuery={listingQuery}
          onSearchQueryChange={handleListingSearch}
          onSelect={(id) => { setSelectedConvId(id); setActiveView("listings"); setMobilePane("workspace"); closeMobileSidebar(); }}
          onCreate={createListing}
          onDelete={(id) => deleteConv.mutate(id)}
          onOpenSettings={openSettings}
          onCloseSettings={closeSettings}
          onSettingsSectionChange={handleSettingsSectionChange}
          onSettingsSearchResult={handleSettingsSearchResult}
        />

        <div className="workspace-frame">
          <header className="mobile-workspace-bar">
            <button
              type="button"
              className="sidebar-icon-btn sidebar-toggle"
              aria-label="Back to listings"
              onClick={() => {
                if (activeView === "settings") {
                  closeSettings();
                  closeMobileSidebar();
                  return;
                }
                setMobileSidebarOpen(true);
              }}
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
              <SettingsPage
                section={settingsSection}
                targetId={settingsTargetId}
                onTargetHandled={() => setSettingsTargetId(null)}
                onOpenSetupGuide={() => setSetupGuideOpen(true)}
              />
            ) : selectedConvId ? (
              <div className="listing-workspace">
                <div className="listing-workspace-main">
                  <PhotoTray convId={selectedConvId} />
                  <ItemDetails convId={selectedConvId} />
                  <div className="chat-column">
                    <ChatPanel
                      convId={selectedConvId}
                      queuedMessage={queuedChatMessage}
                      onQueuedMessageConsumed={() => setQueuedChatMessage(null)}
                    />
                  </div>
                </div>
                {previewOpen && (
                  <BrowserPreview
                    jobId={listingJob?.id ?? null}
                    step={listingJob?.current_step}
                    status={listingJob?.status}
                    vendooItemId={listingJob?.vendoo_item_id}
                    vendooUrl={listingJob?.vendoo_url}
                    cancelling={cancelJob.isPending}
                    onCancel={listingJob?.id ? () => cancelJob.mutate(listingJob.id) : undefined}
                  />
                )}
              </div>
            ) : needsSetup ? (
              <SetupChecklist
                providerConfigured={providerConfigured}
                chromeAvailable={status?.chrome_available !== false}
                extensionConnected={Boolean(status?.extension_connected)}
                creating={createConv.isPending}
                onOpenSettings={openSettings}
                onStartGuide={() => setSetupGuideOpen(true)}
                onCreate={createListing}
              />
            ) : (
              <div className="empty-state">
                <div className="empty-state-headline">Turn product photos<br />into marketplace-ready drafts.</div>
                <div className="empty-state-rule" />
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  style={{ marginTop: 8 }}
                  disabled={createConv.isPending}
                  title={createListingTitle}
                  onClick={createListing}
                >
                  Create a listing
                </button>
              </div>
            )}
          </main>

          {activeView !== "settings" && (
            <aside className="panel detail-panel">
              {selectedConvId ? (
                <ListingEditor
                  convId={selectedConvId}
                  onJobStarted={() => setMobilePane("browser")}
                  onAskChat={(text) => {
                    setQueuedChatMessage(text);
                    setMobilePane("workspace");
                  }}
                />
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
            title={createListingTitle}
            aria-label={createListingTitle}
            disabled={createConv.isPending}
            onClick={createListing}
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
      {setupGuideOpen ? (
        <FirstRunGuide
          providerConfigured={providerConfigured}
          chromeAvailable={status?.chrome_available !== false}
          extensionConnected={Boolean(status?.extension_connected)}
          creating={createConv.isPending}
          onClose={() => setSetupGuideOpen(false)}
          onCreateListing={createListing}
        />
      ) : null}
    </div>
  );
}
