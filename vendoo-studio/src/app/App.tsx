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
import { ListingSidebar } from "../components/ListingSidebar";
import { ConfirmDialogHost } from "../components/ConfirmDialogHost";
import { ToastHost } from "../components/ToastHost";
import { isConfirmDialogOpen } from "../ui/confirmDialog";

const PREVIEW_JOB_STATUSES = new Set(["queued", "awaiting_extension", "dispatched"]);

export function App() {
  const queryClient = useQueryClient();
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"listings" | "settings">("listings");
  const [mobilePane, setMobilePane] = useState<"listings" | "workspace" | "editor" | "browser">("listings");
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

  useEffect(() => {
    if (wasPreviewOpen.current && !previewOpen && mobilePane === "browser") {
      setMobilePane("workspace");
    }
    wasPreviewOpen.current = previewOpen;
  }, [previewOpen, mobilePane]);

  useEffect(() => {
    if (activeView !== "settings") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || isConfirmDialogOpen()) return;
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
  }, [activeView]);

  const createConv = useMutation({
    mutationFn: () => api.conversations.create({ title: "New Listing" }),
    onSuccess: (conv) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setSelectedConvId(conv.id);
      setActiveView("listings");
      setMobilePane("workspace");
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
        setMobilePane("listings");
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <div className="app-shell">
      <div className={`app-content mobile-pane-${mobilePane}`}>
        <ListingSidebar
          conversations={conversations}
          selectedConvId={selectedConvId}
          activeView={activeView}
          creating={createConv.isPending}
          onSelect={(id) => { setSelectedConvId(id); setActiveView("listings"); setMobilePane("workspace"); }}
          onCreate={() => createConv.mutate()}
          onDelete={(id) => deleteConv.mutate(id)}
          onOpenSettings={() => { setActiveView("settings"); setMobilePane("workspace"); }}
          onCloseSettings={() => setActiveView("listings")}
        />

        <div className="workspace-frame">
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

      <nav className="mobile-nav" aria-label="Dashboard views">
        <button className={mobilePane === "listings" ? "selected" : ""} onClick={() => setMobilePane("listings")}>Listings</button>
        <button className={mobilePane === "workspace" ? "selected" : ""} onClick={() => setMobilePane("workspace")}>Workspace</button>
        <button
          className={mobilePane === "editor" ? "selected" : ""}
          onClick={() => setMobilePane("editor")}
          disabled={activeView !== "listings" || !selectedConvId}
        >
          Editor
        </button>
        <button
          className={mobilePane === "browser" ? "selected" : ""}
          onClick={() => setMobilePane("browser")}
          disabled={activeView !== "listings" || !selectedConvId || !previewOpen}
        >
          Browser
        </button>
      </nav>
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
