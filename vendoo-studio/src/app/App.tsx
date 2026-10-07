import { lazy, Suspense, useEffect, useRef, useState, useReducer, type CSSProperties } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { BUSY_POLL_MS, IDLE_POLL_MS, hasOpenJob, jobsPollMs, pollMs } from "../api/polling";
import type { BrowserField } from "../api/client";
import { BuildVersion } from "../components/BuildVersion";
import { ExtensionStatus } from "../components/ExtensionStatus";
import { ProviderStatus } from "../components/ProviderStatus";
import { ChatPanel } from "../components/ChatPanel";
import { SetupChecklist } from "../components/SetupChecklist";
import { BrowserPreview } from "../components/BrowserPreview";
import { AnalyticsIcon, BackIcon, SourcingIcon, ComposeIcon, HamburgerIcon, ListingSidebar, SearchIcon, SettingsIcon } from "../components/ListingSidebar";
import {
  DEFAULT_SETTINGS_SECTION,
  SETTINGS_SECTION_LABELS,
  type SettingsSearchItem,
  type SettingsSectionId,
} from "../components/settingsNav";
import { ConfirmDialogHost } from "../components/ConfirmDialogHost";
import { PhotoDropOverlay } from "../components/PhotoDropOverlay";
import { BulkUploadDialog } from "../components/BulkUploadDialog";
import { BulkMeasurementsDialog, type BulkMeasureListing } from "../components/BulkMeasurementsDialog";
import { useBulkRegenerate } from "../components/useBulkRegenerate";
import { bulkRegenerateToast } from "../bulkRegenerate";
import { ToastHost } from "../components/ToastHost";
import { PanelResizeHandle, usePanelCollapsed, usePanelWidth, type PanelWidthLimits } from "../components/PanelResizeHandle";
import { WorkspaceTopbar, stopTitlebarDrag } from "../components/WorkspaceTopbar";
import { workspaceCrumbs, type WorkspaceView } from "../components/workspaceCrumbs";
import { SuggestionsPanel } from "../components/SuggestionsPanel";
import { ListingBrowserButton, ListingReviewActions } from "../components/ListingReviewActions";
import type { ListingReviewTab } from "../components/ListingReviewTabs";
import { isConfirmDialogOpen } from "../ui/confirmDialog";
import { dismissSetupGuide, isSetupGuideDismissed } from "../onboarding";
import { addToast } from "../ui/toast";
import {
  groupImageFilesByFolder,
  listingTitleForFolder,
  type PhotoFolderGroup,
} from "../photoDrop";
import {
  createBulkPhotoListings,
  type BulkListingUploadResult,
  type BulkUploadDefaults,
} from "../bulkPhotoUpload";
import { ThemeSync } from "../components/ThemeSync";
import { QueuePage } from "../components/QueuePage";

import { OpenListingTabs } from "../components/OpenListingTabs";
import { initialListingTabs, listingTabsReducer } from "./listingTabs";

const ListingEditor = lazy(() =>
  import("../components/ListingEditor").then((module) => ({ default: module.ListingEditor })),
);
const SettingsPage = lazy(() =>
  import("../components/SettingsPage").then((module) => ({ default: module.SettingsPage })),
);
const AnalyticsPage = lazy(() =>
  import("../components/AnalyticsPage").then((module) => ({ default: module.AnalyticsPage })),
);
const SourcingPage = lazy(() =>
  import("../components/SourcingPage").then((module) => ({ default: module.SourcingPage })),
);
const FirstRunGuide = lazy(() =>
  import("../components/FirstRunGuide").then((module) => ({ default: module.FirstRunGuide })),
);

const ACTIVE_JOB_STATUSES = new Set(["queued", "awaiting_extension", "dispatched"]);
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
  const [listingTabs, dispatchListingTab] = useReducer(
    listingTabsReducer,
    new URLSearchParams(window.location.search).get("listing") || null,
    initialListingTabs,
  );
  const selectedConvId = listingTabs.selectedId;
  const selectedTab = listingTabs.tabs.find((tab) => tab.id === selectedConvId);
  const reviewTab = selectedTab?.reviewTab ?? "input";
  const setSelectedConvId = (id: string) => dispatchListingTab({ type: "open", id });
  const setReviewTab = (value: ListingReviewTab) => {
    if (selectedConvId) dispatchListingTab({ type: "review", id: selectedConvId, value });
  };
  const clearListingWorkspace = (id: string) => dispatchListingTab({ type: "clear", id });
  const [activeView, setActiveView] = useState<WorkspaceView>("listings");
  const [settingsSection, setSettingsSection] = useState<SettingsSectionId>(DEFAULT_SETTINGS_SECTION);
  const [settingsTargetId, setSettingsTargetId] = useState<string | null>(null);
  const [mobilePane, setMobilePane] = useState<"workspace" | "editor" | "browser">("workspace");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(() => window.matchMedia(MOBILE_LAYOUT_QUERY).matches);
  const [listingQuery, setListingQuery] = useState("");
  const [setupGuideOpen, setSetupGuideOpen] = useState(setupGuideAutoOpen === true);
  const [browserJobId, setBrowserJobId] = useState<string | null>(null);
  const [browserFields, setBrowserFields] = useState<BrowserField[]>([]);
  const [browserExpanded, setBrowserExpanded] = useState(false);
  const [pendingBulkGroups, setPendingBulkGroups] = useState<PhotoFolderGroup[] | null>(null);
  const [measureListings, setMeasureListings] = useState<BulkMeasureListing[] | null>(null);
  const wasBrowserOpen = useRef(false);
  const mainPanelRef = useRef<HTMLElement>(null);
  const [sidebarWidth, setSidebarWidth] = usePanelWidth("sidebar");
  const [detailWidth, setDetailWidth] = usePanelWidth("detail");
  const [sidebarCollapsed, setSidebarCollapsed] = usePanelCollapsed("sidebar");
  const [detailCollapsed, setDetailCollapsed] = usePanelCollapsed("detail");
  const panelWidthStyle = {
    ...(sidebarWidth ? { "--sidebar-width": `${sidebarWidth}px` } : {}),
    ...(detailWidth ? { "--detail-width": `${detailWidth}px` } : {}),
  } as CSSProperties;

  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: (query) => pollMs(query.state.data?.active_job_id ? BUSY_POLL_MS : IDLE_POLL_MS),
  });
  // Re-reading the whole inventory is the heaviest request Studio makes, so it
  // only runs fast while a Vendoo send is moving rows. Studio's own edits
  // invalidate it; the slow pass picks up Vendoo's background syncs.
  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.conversations.list,
    refetchInterval: (query) =>
      pollMs(
        status?.active_job_id || query.state.data?.some((c) => c.status === "listing")
          ? BUSY_POLL_MS
          : IDLE_POLL_MS,
      ),
  });
  const { data: jobs } = useQuery({
    queryKey: selectedConvId ? ["jobs", selectedConvId] : ["jobs"],
    queryFn: () => api.jobs.list(selectedConvId || undefined),
    refetchInterval: (query) => jobsPollMs(query.state.data),
  });
  const queue = useQuery({
    queryKey: ["queue"],
    queryFn: api.jobs.queue,
    refetchInterval: (query) =>
      pollMs(hasOpenJob(query.state.data?.jobs) || query.state.data?.work.length ? BUSY_POLL_MS : IDLE_POLL_MS),
  });
  const previousQueueJobs = useRef<Map<string, string> | null>(null);
  useEffect(() => {
    if (!queue.data) return;
    const previous = previousQueueJobs.current;
    previousQueueJobs.current = new Map(queue.data.jobs.map((job) => [job.id, job.status]));
    if (!previous) return;
    for (const job of queue.data.jobs) {
      if (!ACTIVE_JOB_STATUSES.has(previous.get(job.id) || "") || ACTIVE_JOB_STATUSES.has(job.status)) continue;
      for (const key of ["jobs", "conversations", "conversation", "listing", "listing-fields", "fill-log", "vendoo-item"]) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
      if (job.status === "completed" || job.status === "failed") {
        addToast({
          type: job.status === "failed" ? "error" : "success",
          title: job.status === "failed" ? "Vendoo send failed" : "Vendoo draft saved",
          description: job.last_error || job.listing_title,
        });
      }
    }
  }, [queue.data, queryClient]);

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
  const automationRunning = ACTIVE_JOB_STATUSES.has(String(listingJob?.status));
  // Sends run in the background; the seller opens the browser explicitly.
  const browserOpen = Boolean(browserJobId && listingJob?.id === browserJobId);

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
    : activeView === "analytics"
      ? "Analytics"
      : activeView === "queue"
        ? "Queue"
      : activeView === "sourcing"
        ? "Sourcing"
        : String(selectedListing?.title || "Vendoo Studio");
  const crumbs = workspaceCrumbs(
    activeView,
    SETTINGS_SECTION_LABELS[settingsSection],
    activeView === "listings" ? selectedListing : null,
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

  // Analytics and Sourcing are toggles: pressing the open one goes back to listings.
  const togglePage = (view: "analytics" | "sourcing" | "queue") => {
    setMobilePane("workspace");
    if (activeView === view) {
      setActiveView("listings");
      return;
    }
    setActiveView(view);
    closeMobileSidebar();
  };
  const openAnalytics = () => togglePage("analytics");
  const openProviders = () => {
    setSettingsSection("providers");
    setSettingsTargetId(null);
    setActiveView("settings");
    setMobilePane("workspace");
    closeMobileSidebar();
  };
  const openSourcing = () => togglePage("sourcing");

  const openListing = (id: string) => {
    setSelectedConvId(id);
    setActiveView("listings");
    setMobilePane("workspace");
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
    if (wasBrowserOpen.current && !browserOpen && mobilePane === "browser") {
      setMobilePane("workspace");
    }
    wasBrowserOpen.current = browserOpen;
  }, [browserOpen, mobilePane]);

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
    if (activeView === "listings") return;
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
      if (activeView === "settings") closeSettings();
      else setActiveView("listings");
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

  const bulk = useBulkRegenerate((id) => activeView === "listings" && selectedConvId === id);

  // A bulk upload asks for measurements next, then generates every draft.
  const askForMeasurements = (listings: BulkListingUploadResult[]) => {
    const withPhotos = listings
      .filter((listing) => listing.count > 0)
      .map((listing) => ({ convId: listing.convId, title: listingTitleForFolder(listing.folder) }));
    if (withPhotos.length) setMeasureListings(withPhotos);
  };

  const generateBatch = async (listings: BulkMeasureListing[]) => {
    setMeasureListings(null);
    if (bulk.running) {
      addToast({
        type: "warning",
        title: "Studio is already working through a batch",
        description: "Generate these from the sidebar's Regenerate button when it finishes.",
      });
      return;
    }
    const ids = listings.map((listing) => listing.convId);
    const titles = new Map(listings.map((listing) => [listing.convId, listing.title]));
    const result = await bulk.start(ids, titles, "generate");
    if (result) addToast(bulkRegenerateToast(result, "generate"));
  };

  // Photos dropped anywhere in the window land on the open listing; with no
  // listing open the drop starts one, the same as "New listing" then Add Photos.
  // Multiple folders (Finder multi-select or a parent of item folders) each
  // become their own draft — a bulk upload — instead of one mixed listing.
  const dropPhotos = useMutation({
    mutationFn: async (
      upload:
        | { files: File[] }
        | { groups: PhotoFolderGroup[]; bulkDefaults: BulkUploadDefaults },
    ) => {
      if ("groups" in upload) {
        const listings = await createBulkPhotoListings(upload.groups, upload.bulkDefaults, api.conversations);
        return { mode: "bulk" as const, listings };
      }

      const { files } = upload;
      const groups = groupImageFilesByFolder(files);
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
        askForMeasurements(result.listings);
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
      if (created || activeView !== "listings") {
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
      dispatchListingTab({ type: "close", id: convId });
      if (selectedConvId === convId && listingTabs.tabs.length === 1) {
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
        detailOpen={activeView === "listings" ? !detailHidden : null}
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
                clearListingWorkspace(selectedConvId);
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
            mobileOpen={!isMobile || mobileSidebarOpen}
            listingQuery={listingQuery}
            onSearchQueryChange={handleListingSearch}
            onSelect={openListing}
            onDelete={(id) => deleteConv.mutate(id)}
            onOpenSettings={openSettings}
            onOpenAnalytics={openAnalytics}
            onOpenSourcing={openSourcing}
            onOpenQueue={() => togglePage("queue")}
            queueCount={(queue.data?.jobs.filter((j) => ACTIVE_JOB_STATUSES.has(j.status)).length ?? 0)
              + (queue.data?.work.filter((w) => !bulk.pendingIds.includes(w.conversation_id)).length ?? 0)
              + bulk.pendingIds.length}
            onCloseSettings={closeSettings}
            onSettingsSectionChange={handleSettingsSectionChange}
            onSettingsSearchResult={handleSettingsSearchResult}
            bulk={bulk}
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
                if (activeView === "analytics" || activeView === "sourcing") {
                  setActiveView("listings");
                  setMobileSidebarOpen(true);
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
                <button type="button" className="sidebar-icon-btn" aria-label="Queue" onClick={() => togglePage("queue")}>Queue</button>
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
                    disabled={!selectedConvId || !browserOpen}
                    onClick={() => setMobilePane("browser")}
                  >
                    Browser
                  </button>
                </div>
                <button
                  type="button"
                  className="sidebar-icon-btn mobile-workspace-settings"
                  title="Sourcing"
                  aria-label="Sourcing"
                  onClick={openSourcing}
                >
                  <SourcingIcon />
                </button>
                <button
                  type="button"
                  className="sidebar-icon-btn mobile-workspace-settings"
                  title="Analytics"
                  aria-label="Analytics"
                  onClick={openAnalytics}
                >
                  <AnalyticsIcon />
                </button>
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
          {activeView === "listings" ? (
            <OpenListingTabs
              tabs={listingTabs.tabs.map((tab) => ({
                id: tab.id,
                title: conversations?.find((listing) => listing.id === tab.id)?.title || "Untitled listing",
              }))}
              selectedId={selectedConvId}
              onSelect={openListing}
              onClose={(id) => dispatchListingTab({ type: "close", id })}
              onCreate={createListing}
              creating={createConv.isPending}
            />
          ) : null}
          <div className="workspace-body" id="listing-workspace-panel"
            role={activeView === "listings" && selectedConvId ? "tabpanel" : undefined}
            aria-labelledby={activeView === "listings" && selectedConvId ? `listing-tab-${selectedConvId}` : undefined}
          >
            <main className="panel main-panel" ref={mainPanelRef}>
              {activeView === "settings" ? (
                <Suspense fallback={null}>
                  <SettingsPage
                    onOpenListing={openListing}
                    section={settingsSection}
                    targetId={settingsTargetId}
                    onTargetHandled={() => setSettingsTargetId(null)}
                    onOpenSetupGuide={() => setSetupGuideOpen(true)}
                  />
                </Suspense>
              ) : activeView === "queue" ? (
                <QueuePage data={queue.data} loading={queue.isPending} error={queue.error}
                  bulk={bulk} titles={new Map((conversations ?? []).map((c) => [c.id, c.title || "Untitled listing"]))}
                  onOpenListing={openListing} />
              ) : activeView === "analytics" ? (
                <Suspense fallback={null}>
                  <AnalyticsPage onOpenListing={openListing} />
                </Suspense>
              ) : activeView === "sourcing" ? (
                <Suspense fallback={null}>
                  <SourcingPage onOpenProviders={openProviders} onOpenListing={openListing} />
                </Suspense>
              ) : selectedConvId ? null : needsSetup ? (
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
                    onSelect={openListing}
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
              {selectedConvId && (
                <div hidden={activeView !== "listings"} className={`listing-workspace${browserOpen && browserExpanded ? " is-browser-expanded" : ""}`}>
                  {browserOpen && (
                    <BrowserPreview
                      jobId={listingJob?.id ?? null}
                      step={listingJob?.current_step}
                      status={listingJob?.status}
                      vendooItemId={listingJob?.vendoo_item_id}
                      vendooUrl={listingJob?.vendoo_url}
                      cancelling={cancelJob.isPending}
                      onCancel={listingJob?.id ? () => cancelJob.mutate(listingJob.id) : undefined}
                      interactive={browserOpen}
                      automationRunning={automationRunning}
                      onClose={closeBrowser}
                      expanded={browserExpanded}
                      onToggleExpanded={isMobile ? undefined : () => setBrowserExpanded((value) => !value)}
                      selected={browserFields}
                      onSelectedChange={setBrowserFields}
                      onGoToChat={isMobile ? () => setMobilePane("workspace") : undefined}
                    />
                  )}
                  {listingTabs.tabs.map((tab) => (
                    <div className="listing-workspace-main listing-session" key={`${tab.id}:${tab.nonce}`} hidden={tab.id !== selectedConvId}>
                      <div className="chat-column">
                        <ChatPanel
                          convId={tab.id}
                          queuedMessage={tab.queuedMessage}
                          onQueuedMessageConsumed={() => dispatchListingTab({ type: "message", id: tab.id, value: null })}
                          browser={tab.id === selectedConvId && browserOpen && browserJobId ? { jobId: browserJobId, fields: browserFields } : null}
                          onBrowserFieldsChange={setBrowserFields}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </main>

            {activeView === "listings" && !detailHidden && (
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
            {(listingTabs.tabs.length > 0 || (activeView === "listings" && !detailHidden)) && (
              <aside id="listing-inspector" className="panel detail-panel" hidden={activeView !== "listings" || detailHidden}>
                {selectedConvId ? (
                  listingTabs.tabs.map((tab) => (
                    <div className="listing-session" key={`${tab.id}:${tab.nonce}`} hidden={tab.id !== selectedConvId}>
                      <Suspense fallback={null}>
                        <ListingEditor
                          convId={tab.id}
                          reviewTab={tab.reviewTab}
                          onReviewTabChange={(value) => dispatchListingTab({ type: "review", id: tab.id, value })}
                          onOpenBrowser={(jobId) => openBrowser.mutate(jobId)}
                          browserOpen={tab.id === selectedConvId && browserOpen}
                          onAskChat={(text) => {
                            dispatchListingTab({ type: "message", id: tab.id, value: text });
                            setMobilePane("workspace");
                          }}
                          onCleared={() => {
                            clearListingWorkspace(tab.id);
                          }}
                          onBulkListingsCreated={(listings) => {
                            askForMeasurements(listings);
                            const first = listings[0]?.convId;
                            if (!first) return;
                            setSelectedConvId(first);
                            setActiveView("listings");
                            setMobilePane("workspace");
                            setMobileSidebarOpen(false);
                          }}
                        />
                      </Suspense>
                    </div>
                  ))
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
          const groups = groupImageFilesByFolder(files);
          if (groups.length > 1) {
            setPendingBulkGroups(groups);
            return;
          }
          dropPhotos.mutate({ files });
        }}
      />
      {pendingBulkGroups ? (
        <BulkUploadDialog
          groups={pendingBulkGroups}
          onCancel={() => setPendingBulkGroups(null)}
          onConfirm={(bulkDefaults, groups) => {
            setPendingBulkGroups(null);
            dropPhotos.mutate({ groups, bulkDefaults });
          }}
        />
      ) : null}
      {measureListings ? (
        <BulkMeasurementsDialog
          listings={measureListings}
          onClose={() => setMeasureListings(null)}
          onGenerate={(listings) => { void generateBatch(listings); }}
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
