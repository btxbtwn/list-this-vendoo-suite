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
import { UpdateButton } from "../components/UpdateButton";
import { BrowserPreview } from "../components/BrowserPreview";

const PREVIEW_JOB_STATUSES = new Set(["queued", "awaiting_extension", "dispatched"]);

export function App() {
  const queryClient = useQueryClient();
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"listings" | "settings">("listings");
  const [mobilePane, setMobilePane] = useState<"listings" | "workspace" | "editor" | "browser">("listings");
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
  const listingNeedle = listingQuery.trim().toLowerCase();
  const visibleConversations = conversations?.filter((c: any) => {
    if (!listingNeedle) return true;
    const title = String(c.title || "Untitled").toLowerCase();
    const status = String(c.status || "draft").replace(/_/g, " ").toLowerCase();
    return title.includes(listingNeedle) || status.includes(listingNeedle);
  });

  useEffect(() => {
    if (wasPreviewOpen.current && !previewOpen && mobilePane === "browser") {
      setMobilePane("workspace");
    }
    wasPreviewOpen.current = previewOpen;
  }, [previewOpen, mobilePane]);

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
        <aside className="panel sidebar">
          <div className="sidebar-header pywebview-drag-region">
            <div className="sidebar-brand">
              <span className="sidebar-wordmark">Vendoo</span>
              <span className="sidebar-product">Studio</span>
            </div>
          </div>

          <div className="sidebar-toolbar">
            <label className="sidebar-search">
              <svg className="sidebar-search-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
                <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <input
                type="search"
                value={listingQuery}
                onChange={(e) => setListingQuery(e.target.value)}
                placeholder="Search listings"
                aria-label="Search listings"
              />
            </label>
            <button
              className="sidebar-icon-btn"
              title="New listing"
              aria-label="New listing"
              onClick={() => createConv.mutate()}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M8 3.5v9M3.5 8h9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          <div className="sidebar-list">
            {visibleConversations?.map((c: any) => {
              const isSelected = selectedConvId === c.id && activeView === "listings";
              const status = String(c.status || "draft");
              const statusClass = status.replace(/_/g, "-");
              const statusLabel = status.replace(/_/g, " ");
              return (
                <div key={c.id} className="nav-item">
                  <button
                    className={`nav-link${isSelected ? " selected" : ""}`}
                    onClick={() => { setSelectedConvId(c.id); setActiveView("listings"); setMobilePane("workspace"); }}
                  >
                    <div className="nav-link-title">{c.title || "Untitled"}</div>
                    <div className="nav-link-meta">
                      <span className={`nav-status nav-status-${statusClass}`}>{statusLabel}</span>
                    </div>
                  </button>
                  <button
                    className="nav-delete"
                    title="Delete"
                    aria-label={`Delete ${c.title || "Untitled"}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Delete "${c.title || "Untitled"}"?`)) deleteConv.mutate(c.id);
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                      <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    </svg>
                  </button>
                </div>
              );
            })}
            {(!conversations || conversations.length === 0) && (
              <div className="sidebar-empty">No listings yet</div>
            )}
            {conversations && conversations.length > 0 && visibleConversations?.length === 0 && (
              <div className="sidebar-empty">No matching listings</div>
            )}
          </div>

          <div className="sidebar-footer">
            <button
              className={`sidebar-icon-btn${activeView === "settings" ? " selected" : ""}`}
              title="Settings"
              aria-label="Settings"
              onClick={() => { setActiveView("settings"); setMobilePane("workspace"); }}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.5" />
                <path d="M8 2.4v1.5M8 12.1v1.5M2.4 8h1.5M12.1 8h1.5M4 4l1.1 1.1M10.9 10.9l1.1 1.1M12 4l-1.1 1.1M5.1 10.9L4 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
            <UpdateButton />
          </div>
        </aside>

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

          <aside className="panel detail-panel">
            {activeView === "listings" && selectedConvId ? (
              <ListingEditor convId={selectedConvId} onJobStarted={() => setMobilePane("browser")} />
            ) : (
              <div className="empty-state">
                <p className="text-xs text-muted font-mono">Select a listing to inspect</p>
              </div>
            )}
          </aside>
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
    </div>
  );
}
