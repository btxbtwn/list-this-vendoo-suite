import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BrowserField } from "../api/client";
import { ExtensionStatus } from "../components/ExtensionStatus";
import { ProviderStatus } from "../components/ProviderStatus";
import { ChatPanel } from "../components/ChatPanel";
import { PhotoTray } from "../components/PhotoTray";
import { SetupChecklist } from "../components/SetupChecklist";
import { ItemDetails } from "../components/ItemDetails";
import { BrowserPreview } from "../components/BrowserPreview";
import { BackIcon, ComposeIcon, HamburgerIcon, ListingSidebar, SearchIcon, SettingsIcon } from "../components/ListingSidebar";
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
import { addToast } from "../ui/toast";

const ListingEditor = lazy(() =>
  import("../components/ListingEditor").then((module) => ({ default: module.ListingEditor })),
);
const SettingsPage = lazy(() =>
  import("../components/SettingsPage").then((module) => ({ default: module.SettingsPage })),
);
const FirstRunGuide = lazy(() =>
  import("../components/FirstRunGuide").then((module) => ({ default: module.FirstRunGuide })),
);

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
  const [workspaceNonce, setWorkspaceNonce] = useState(0);
  const [browserJobId, setBrowserJobId] = useState<string | null>(null);
  const [browserFields, setBrowserFields] = useState<BrowserField[]>([]);
  const [browserExpanded, setBrowserExpanded] = useState(false);
  const wasPreviewOpen = useRef(false);

  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.conversations.list,
    refetchInterval: 2000,
  });
  const { data: jobs } = useQuery({
    queryKey: selectedConvId ? ["jobs", selectedConvId] : ["jobs"],
    queryFn: () => api.jobs.list(selectedConvId || undefined),
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
  const listingJob = jobs?.find((job) => job.conversation_id === selectedConvId && job.status !== "cancelled");
  const previewOpen = Boolean(listingJob && PREVIEW_JOB_STATUSES.has(String(listingJob.status)));
  const browserOpen = Boolean(browserJobId && listingJob?.id === browserJobId);
  const browserPaneOpen = previewOpen || browserOpen;

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
    // On mobile, land on the settings section list first so Providers etc. are reachable.
    setMobileSidebarOpen(isMobile);
  };

  const closeSettings = () => {
    setActiveView("listings");
    setSettingsTargetId(null);
    closeMobileSidebar();
  };

  const handleSettingsSectionChange = (section: SettingsSectionId) => {
    setSettingsSection(section);
    setSettingsTargetId(null);
    closeMobileSidebar();
  };

  const handleSettingsSearchResult = (item: SettingsSearchItem) => {
    setSettingsSection(item.section);
    setSettingsTargetId(item.targetId || item.id);
    closeMobileSidebar();
  };

  useEffect(() => {
    if (wasPreviewOpen.current && !browserPaneOpen && mobilePane === "browser") {
      setMobilePane("workspace");
    }
    wasPreviewOpen.current = browserPaneOpen;
  }, [browserPaneOpen, mobilePane]);

  const openBrowser = useMutation({
    mutationFn: (jobId: string) => api.jobs.browser.open(jobId),
    onMutate: (jobId: string) => {
      setBrowserJobId(jobId);
      setMobilePane("browser");
    },
    onSuccess: (result) => {
      if (result.warning) {
        addToast({ type: "error", title: "Browser is view-only", description: result.warning });
      }
    },
    onError: (err: Error, jobId: string) => {
      setBrowserJobId((current) => (current === jobId ? null : current));
      addToast({ type: "error", title: "Could not open the Vendoo draft", description: err.message });
    },
  });

  const closeBrowser = () => {
    const jobId = browserJobId;
    setBrowserJobId(null);
    setBrowserFields([]);
    setBrowserExpanded(false);
    if (jobId) void api.jobs.browser.close(jobId).catch(() => {});
  };

  // Every listing run happens in the same interactive draft browser the
  // "Browser" button opens. Attach as soon as the run has a draft; when
  // the fill finishes the seller keeps the live tab instead of losing the pane.
  const autoBrowserJobRef = useRef<string | null>(null);
  const openBrowserMutate = openBrowser.mutate;
  const listingJobId = listingJob?.id ?? null;
  const listingJobHasDraft = Boolean(listingJob?.vendoo_item_id || listingJob?.vendoo_url);
  const listingJobIsProbe = listingJob?.mode === "schema_probe";
  useEffect(() => {
    if (!listingJobId || !previewOpen || !listingJobHasDraft || listingJobIsProbe) return;
    if (!status?.extension_connected) return;
    if (browserJobId === listingJobId || autoBrowserJobRef.current === listingJobId) return;
    autoBrowserJobRef.current = listingJobId;
    openBrowserMutate(listingJobId);
  }, [listingJobId, previewOpen, listingJobHasDraft, listingJobIsProbe, status?.extension_connected, browserJobId, openBrowserMutate]);

  useEffect(() => {
    // A new Send replaces the listing job. Release the old draft tab.
    if (browserJobId && listingJob?.id && listingJob.id !== browserJobId) {
      setBrowserJobId(null);
      setBrowserFields([]);
      void api.jobs.browser.close(browserJobId).catch(() => {});
    }
  }, [browserJobId, listingJob?.id]);

  const browserJobRef = useRef<string | null>(null);
  browserJobRef.current = browserJobId;
  useEffect(() => () => {
    // Leaving a listing hands its Chrome tab back to the background window.
    const jobId = browserJobRef.current;
    if (jobId) {
      setBrowserJobId(null);
      setBrowserFields([]);
      void api.jobs.browser.close(jobId).catch(() => {});
    }
    setBrowserExpanded(false);
  }, [selectedConvId]);

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
              aria-label={
                activeView === "settings"
                  ? mobileSidebarOpen
                    ? "Back to listings"
                    : "Settings menu"
                  : "Back to listings"
              }
              onClick={() => {
                if (activeView === "settings") {
                  if (!mobileSidebarOpen) {
                    setMobileSidebarOpen(true);
                    return;
                  }
                  closeSettings();
                  return;
                }
                setMobileSidebarOpen(true);
              }}
            >
              <BackIcon />
            </button>
            <div className="mobile-workspace-title">{workspaceTitle}</div>
            {activeView === "listings" ? (
              <>
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
                    disabled={!selectedConvId}
                    onClick={() => setMobilePane("editor")}
                  >
                    Listing
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={mobilePane === "browser"}
                    className={mobilePane === "browser" ? "selected" : ""}
                    disabled={!selectedConvId || !browserPaneOpen}
                    onClick={() => setMobilePane("browser")}
                  >
                    Browser
                  </button>
                </div>
                <button
                  type="button"
                  className="sidebar-icon-btn mobile-workspace-settings"
                  title="Settings"
                  aria-label="Settings"
                  onClick={openSettings}
                >
                  <SettingsIcon />
                </button>
              </>
            ) : null}
          </header>
          <main className="panel main-panel">
            <div className="workspace-drag-region pywebview-drag-region" aria-hidden="true" />
            {activeView === "settings" ? (
              <Suspense fallback={null}>
                <SettingsPage
                  section={settingsSection}
                  targetId={settingsTargetId}
                  onTargetHandled={() => setSettingsTargetId(null)}
                  onOpenSetupGuide={() => setSetupGuideOpen(true)}
                />
              </Suspense>
            ) : selectedConvId ? (
              <div className={`listing-workspace${browserPaneOpen && browserExpanded ? " is-browser-expanded" : ""}`}>
                <div className="listing-workspace-main" key={`${selectedConvId}:${workspaceNonce}`}>
                  <PhotoTray
                    convId={selectedConvId}
                    onCleared={() => {
                      setQueuedChatMessage(null);
                      setWorkspaceNonce((value) => value + 1);
                    }}
                  />
                  <ItemDetails convId={selectedConvId} />
                  <div className="chat-column">
                    <ChatPanel
                      convId={selectedConvId}
                      queuedMessage={queuedChatMessage}
                      onQueuedMessageConsumed={() => setQueuedChatMessage(null)}
                      browser={browserOpen && browserJobId ? { jobId: browserJobId, fields: browserFields } : null}
                      onBrowserFieldsChange={setBrowserFields}
                    />
                  </div>
                </div>
                {browserPaneOpen && (
                  <BrowserPreview
                    jobId={listingJob?.id ?? null}
                    step={listingJob?.current_step}
                    status={listingJob?.status}
                    vendooItemId={listingJob?.vendoo_item_id}
                    vendooUrl={listingJob?.vendoo_url}
                    cancelling={cancelJob.isPending}
                    onCancel={listingJob?.id ? () => cancelJob.mutate(listingJob.id) : undefined}
                    interactive={browserOpen}
                    automationRunning={previewOpen}
                    onClose={closeBrowser}
                    expanded={browserExpanded}
                    onToggleExpanded={isMobile ? undefined : () => setBrowserExpanded((value) => !value)}
                    selected={browserFields}
                    onSelectedChange={setBrowserFields}
                    onGoToChat={() => setMobilePane("workspace")}
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
                <Suspense fallback={null}>
                  <ListingEditor
                    key={`${selectedConvId}:${workspaceNonce}`}
                    convId={selectedConvId}
                    onJobStarted={() => setMobilePane("browser")}
                    onOpenBrowser={(jobId) => openBrowser.mutate(jobId)}
                    browserOpen={browserOpen}
                    onAskChat={(text) => {
                      setQueuedChatMessage(text);
                      setMobilePane("workspace");
                    }}
                    onCleared={() => {
                      setQueuedChatMessage(null);
                      setWorkspaceNonce((value) => value + 1);
                    }}
                  />
                </Suspense>
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
        <div className="status-right">
          <div>V 0.1.0</div>
        </div>
      </footer>
      <ToastHost />
      <ConfirmDialogHost />
      {setupGuideOpen ? (
        <Suspense fallback={null}>
          <FirstRunGuide
            providerConfigured={providerConfigured}
            chromeAvailable={status?.chrome_available !== false}
            extensionConnected={Boolean(status?.extension_connected)}
            creating={createConv.isPending}
            onClose={() => setSetupGuideOpen(false)}
            onCreateListing={createListing}
          />
        </Suspense>
      ) : null}
    </div>
  );
}
