import { lazy, Suspense, useEffect, useRef, useState, type CSSProperties } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { BrowserField } from "../api/client";
import { BuildVersion } from "../components/BuildVersion";
import { ExtensionStatus } from "../components/ExtensionStatus";
import { ProviderStatus } from "../components/ProviderStatus";
import { ChatPanel } from "../components/ChatPanel";
import { SetupChecklist } from "../components/SetupChecklist";
import { BrowserPreview } from "../components/BrowserPreview";
import { BackIcon, ComposeIcon, HamburgerIcon, ListingSidebar, SearchIcon, SettingsIcon } from "../components/ListingSidebar";
import {
  DEFAULT_SETTINGS_SECTION,
  SETTINGS_SECTION_LABELS,
  type SettingsSearchItem,
  type SettingsSectionId,
} from "../components/settingsNav";
import { ConfirmDialogHost } from "../components/ConfirmDialogHost";
import { PhotoDropOverlay } from "../components/PhotoDropOverlay";
import { BulkUploadDialog } from "../components/BulkUploadDialog";
import { ToastHost } from "../components/ToastHost";
import { PanelResizeHandle, usePanelCollapsed, usePanelWidth, type PanelWidthLimits } from "../components/PanelResizeHandle";
import { WorkspaceTopbar, stopTitlebarDrag } from "../components/WorkspaceTopbar";
import { workspaceCrumbs } from "../components/workspaceCrumbs";
import { SuggestionsPanel } from "../components/SuggestionsPanel";
import { ListingBrowserButton, ListingReviewActions } from "../components/ListingReviewActions";
import type { ListingReviewTab } from "../components/ListingReviewTabs";
import { isConfirmDialogOpen } from "../ui/confirmDialog";
import { dismissSetupGuide, isSetupGuideDismissed } from "../onboarding";
import { addToast } from "../ui/toast";
import {
  groupImageFilesByFolder,
  listingTitleForFolder,
} from "../photoDrop";
import {
  createBulkPhotoListings,
  type BulkUploadDefaults,
} from "../bulkPhotoUpload";
import { ThemeSync } from "../components/ThemeSync";

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
const SIDEBAR_WIDTH: PanelWidthLimits = { min: 200, max: 420, maxVw: 30 };
/* Min 420 so the inspector can't shrink under the titlebar listing chrome. */
const DETAIL_WIDTH: PanelWidthLimits = { min: 420, max: 640, maxVw: 45 };
const MAIN_PANEL_MIN_WIDTH = 360;
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
  const [reviewTab, setReviewTab] = useState<ListingReviewTab>("input");
  const [browserJobId, setBrowserJobId] = useState<string | null>(null);
  const [browserFields, setBrowserFields] = useState<BrowserField[]>([]);
  const [browserExpanded, setBrowserExpanded] = useState(false);
  const [pendingBulkFiles, setPendingBulkFiles] = useState<File[] | null>(null);
  const wasPreviewOpen = useRef(false);
  const mainPanelRef = useRef<HTMLElement>(null);
  const [sidebarWidth, setSidebarWidth] = usePanelWidth("sidebar");
  const [detailWidth, setDetailWidth] = usePanelWidth("detail");
  const [sidebarCollapsed, setSidebarCollapsed] = usePanelCollapsed("sidebar");
  const [detailCollapsed, setDetailCollapsed] = usePanelCollapsed("detail");
  const panelWidthStyle = {
    ...(sidebarWidth ? { "--sidebar-width": `${sidebarWidth}px` } : {}),
    ...(detailWidth ? { "--detail-width": `${detailWidth}px` } : {}),
  } as CSSProperties;

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

  // Bound listings can change tab in Vendoo while the sidebar is open. A quiet
  // inventory pass refreshes draft/active/sold without importing photos — on
  // focus and whenever Chrome reconnects. Server debounce stops focus spam.
  const extensionConnected = Boolean(status?.extension_connected);
  useEffect(() => {
    if (!extensionConnected) return undefined;
    const kick = () => {
      void api.imports.syncLabels().catch(() => {
        /* Chrome may still be pairing; next focus retries. */
      });
    };
    kick();
    const onFocus = () => kick();
    const onVisible = () => {
      if (document.visibilityState === "visible") kick();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [extensionConnected]);

  const providerConfigured = Boolean(status?.provider_configured);
  const needsSetup = !status || !status.provider_configured || !status.extension_connected;
  const createListingTitle = "New listing";
  const listingJob = jobs?.find((job) => job.conversation_id === selectedConvId && job.status !== "cancelled");
  const apiCreateStep = String(listingJob?.current_step || "");
  const apiCreateRunning = Boolean(
    listingJob?.status === "dispatched"
    && (apiCreateStep === "vendoo_api_create" || apiCreateStep.startsWith("vendoo_api_")),
  );
  // API create has no draft tab yet — keep the browser pane closed so we do not
  // show a forever "Connecting to the Vendoo tab" while Chrome talks to the API.
  const previewOpen = Boolean(
    listingJob
    && PREVIEW_JOB_STATUSES.has(String(listingJob.status))
    && !apiCreateRunning,
  );
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
  const crumbs = workspaceCrumbs(
    activeView,
    SETTINGS_SECTION_LABELS[settingsSection],
    activeView === "settings" ? null : selectedListing,
  );
  // The sidebar overlays the workspace on mobile and the editor is its own pane
  // there, so the desktop collapse states only apply to the desktop layout.
  const sidebarHidden = !isMobile && sidebarCollapsed;
  const detailHidden = !isMobile && detailCollapsed;

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
    setReviewTab("input");
  }, [selectedConvId, workspaceNonce]);

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

  // Photos dropped anywhere in the window land on the open listing; with no
  // listing open the drop starts one, the same as "New listing" then Add Photos.
  // Multiple folders (Finder multi-select or a parent of item folders) each
  // become their own draft — a bulk upload — instead of one mixed listing.
  const dropPhotos = useMutation({
    mutationFn: async ({
      files,
      bulkDefaults = { cog: "", labels: "" },
    }: {
      files: File[];
      bulkDefaults?: BulkUploadDefaults;
    }) => {
      const groups = groupImageFilesByFolder(files);
      if (groups.length > 1) {
        const listings = await createBulkPhotoListings(groups, bulkDefaults, api.conversations);
        return { mode: "bulk" as const, listings };
      }

      const only = groups[0]?.files || files;
      const openConvId = selectedConvId;
      const title =
        !openConvId && groups[0]?.folder
          ? listingTitleForFolder(groups[0].folder)
          : "New Listing";
      const convId = openConvId || (await api.conversations.create({ title })).id;
      const result = await api.conversations.uploadPhotos(convId, only);
      return {
        mode: "single" as const,
        convId,
        created: !openConvId,
        count: result.count,
        errors: result.errors || [],
      };
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (result.mode === "bulk") {
        for (const listing of result.listings) {
          queryClient.invalidateQueries({ queryKey: ["photos", listing.convId] });
        }
        const first = result.listings[0];
        if (first) {
          setSelectedConvId(first.convId);
          setMobileSidebarOpen(false);
          setActiveView("listings");
          setMobilePane("workspace");
        }
        const totalPhotos = result.listings.reduce((sum, row) => sum + row.count, 0);
        const errors = result.listings.flatMap((row) => row.errors);
        const title = `Started ${result.listings.length} listings`;
        const description = `Added ${totalPhotos} photo${totalPhotos === 1 ? "" : "s"} from separate folders.`;
        if (errors.length) {
          addToast({ type: "error", title, description: errors.join("; ") });
          return;
        }
        addToast({ type: "success", title, description });
        return;
      }

      const { convId, created, count, errors } = result;
      queryClient.invalidateQueries({ queryKey: ["photos", convId] });
      if (created) {
        setSelectedConvId(convId);
        setMobileSidebarOpen(false);
      }
      if (created || activeView === "settings") {
        setActiveView("listings");
        setMobilePane("workspace");
      }
      const title = `Added ${count} photo${count === 1 ? "" : "s"}`;
      if (errors.length) {
        addToast({ type: "error", title, description: errors.join("; ") });
        return;
      }
      addToast({ type: "success", title, description: created ? "Started a new listing for them." : undefined });
    },
    onError: (err: Error) => {
      addToast({ type: "error", title: "Could not add photos", description: err.message });
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
    <div className="app-shell" style={panelWidthStyle}>
      <WorkspaceTopbar
        crumbs={crumbs}
        sidebarOpen={!sidebarHidden}
        onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
        detailOpen={activeView === "settings" ? null : !detailHidden}
        onToggleDetail={() => setDetailCollapsed(!detailCollapsed)}
        reviewTab={
          activeView === "listings" && selectedConvId && !detailHidden
            ? reviewTab
            : null
        }
        onReviewTabChange={setReviewTab}
        listingActions={
          activeView === "listings" && selectedConvId && !detailHidden ? (
            <ListingReviewActions
              convId={selectedConvId}
              onCleared={() => {
                setQueuedChatMessage(null);
                setWorkspaceNonce((value) => value + 1);
              }}
              onMouseDown={stopTitlebarDrag}
            />
          ) : null
        }
        browserAction={
          activeView === "listings" && selectedConvId ? (
            <ListingBrowserButton
              convId={selectedConvId}
              browserOpen={browserOpen}
              onOpenBrowser={(jobId) => openBrowser.mutate(jobId)}
              onMouseDown={stopTitlebarDrag}
            />
          ) : null
        }
      />
      <div
        className={`app-content mobile-pane-${mobilePane}${mobileSidebarOpen ? " mobile-sidebar-open" : ""}${sidebarHidden ? " sidebar-collapsed" : ""}`}
      >
        {sidebarHidden ? null : (
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
        )}
        {sidebarHidden ? null : (
          <PanelResizeHandle
            label="Resize listings sidebar"
            panel="before"
            width={sidebarWidth}
            onResize={setSidebarWidth}
            absorberRef={mainPanelRef}
            absorberMin={MAIN_PANEL_MIN_WIDTH}
            {...SIDEBAR_WIDTH}
          />
        )}

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
          <div className="workspace-body">
            <main className="panel main-panel" ref={mainPanelRef}>
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
                      onGoToChat={isMobile ? () => setMobilePane("workspace") : undefined}
                    />
                  )}
                  <div className="listing-workspace-main" key={`${selectedConvId}:${workspaceNonce}`}>
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
                  <SuggestionsPanel
                    variant="workspace"
                    selectedConvId={selectedConvId}
                    onSelect={(id) => { setSelectedConvId(id); setActiveView("listings"); setMobilePane("workspace"); closeMobileSidebar(); }}
                  />
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

            {activeView !== "settings" && !detailHidden && (
              <PanelResizeHandle
                label="Resize listing editor"
                panel="after"
                width={detailWidth}
                onResize={setDetailWidth}
                absorberRef={mainPanelRef}
                absorberMin={MAIN_PANEL_MIN_WIDTH}
                {...DETAIL_WIDTH}
              />
            )}
            {activeView !== "settings" && !detailHidden && (
              <aside id="listing-inspector" className="panel detail-panel">
                {selectedConvId ? (
                  <Suspense fallback={null}>
                    <ListingEditor
                      key={`${selectedConvId}:${workspaceNonce}`}
                      convId={selectedConvId}
                      reviewTab={reviewTab}
                      onReviewTabChange={setReviewTab}
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
                      onBulkListingsCreated={(convIds) => {
                        const first = convIds[0];
                        if (!first) return;
                        setSelectedConvId(first);
                        setActiveView("listings");
                        setMobilePane("workspace");
                        setMobileSidebarOpen(false);
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
          <BuildVersion backendVersion={status?.version} />
        </div>
      </footer>
      <PhotoDropOverlay
        title={
          selectedConvId
            ? `Drop photos into ${String(selectedListing?.title || "this listing")}`
            : "Drop photos to start a new listing"
        }
        hint="Drop several folders for one draft each · JPG, PNG, WEBP or HEIC · up to 20 per listing"
        busy={dropPhotos.isPending}
        busyLabel="Adding photos…"
        onFiles={(files) => {
          if (groupImageFilesByFolder(files).length > 1) {
            setPendingBulkFiles(files);
            return;
          }
          dropPhotos.mutate({ files });
        }}
      />
      {pendingBulkFiles ? (
        <BulkUploadDialog
          count={groupImageFilesByFolder(pendingBulkFiles).length}
          onCancel={() => setPendingBulkFiles(null)}
          onConfirm={(bulkDefaults) => {
            const files = pendingBulkFiles;
            setPendingBulkFiles(null);
            dropPhotos.mutate({ files, bulkDefaults });
          }}
        />
      ) : null}
      <ThemeSync />
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
