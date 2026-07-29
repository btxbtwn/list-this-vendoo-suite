import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ExtensionStatus } from "../components/ExtensionStatus";
import { ListingEditor } from "../components/ListingEditor";
import { ChatPanel } from "../components/ChatPanel";
import { PhotoTray } from "../components/PhotoTray";
import { SettingsPage } from "../components/SettingsPage";
import { ItemDetails } from "../components/ItemDetails";

export function App() {
  const queryClient = useQueryClient();
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"listings" | "settings">("listings");
  const [mobilePane, setMobilePane] = useState<"listings" | "workspace" | "editor">("listings");

  const { data: status } = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 10000 });
  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.conversations.list,
    refetchInterval: 2000,
  });

  const createConv = useMutation({
    mutationFn: () => api.conversations.create({ title: "New Listing" }),
    onSuccess: (conv) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setSelectedConvId(conv.id);
      setActiveView("listings");
      setMobilePane("workspace");
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
        </nav>
        <aside className="panel sidebar">
          <div className="sidebar-masthead">
            <div className="sidebar-brand">Vendoo Studio</div>
            <div className="sidebar-subtitle">Listing Workbench</div>
          </div>

          <div className="sidebar-actions">
            <button className="btn btn-primary btn-sm" style={{ width: "100%" }} onClick={() => createConv.mutate()}>
              + New Listing
            </button>
          </div>

          <div className="sidebar-list">
            {conversations?.map((c: any) => {
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
                    onClick={(e) => {
                      e.stopPropagation();
                      if (confirm(`Delete "${c.title || "Untitled"}"?`)) deleteConv.mutate(c.id);
                    }}
                  >
                    {"\u2715"}
                  </button>
                </div>
              );
            })}
            {(!conversations || conversations.length === 0) && (
              <div style={{ padding: "16px 10px", textAlign: "center" }}>
                <p className="text-xs" style={{ color: "var(--color-ink-muted)" }}>No listings yet</p>
              </div>
            )}
          </div>

          <div className="sidebar-footer">
            <button
              className={`sidebar-settings-btn${activeView === "settings" ? " selected" : ""}`}
              onClick={() => { setActiveView("settings"); setMobilePane("workspace"); }}
            >
              Settings
            </button>
          </div>
        </aside>

        <div className="workspace-frame">
          <main className="panel main-panel">
            {activeView === "settings" ? (
              <SettingsPage />
            ) : selectedConvId ? (
              <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, overflow: "auto" }}>
                <PhotoTray convId={selectedConvId} />
                <ItemDetails convId={selectedConvId} />
                <div style={{ flex: 1, overflow: "hidden", minHeight: 200 }}>
                  <ChatPanel convId={selectedConvId} />
                </div>
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
              <ListingEditor convId={selectedConvId} />
            ) : (
              <div className="empty-state">
                <p className="text-xs text-muted font-mono">Select a listing to inspect</p>
              </div>
            )}
          </aside>
        </div>
      </div>

      <footer className="status-bar">
        <div className="status-left">
          <ExtensionStatus />
          <span>{status?.provider_configured ? "MIMO CONFIGURED" : "MIMO NOT CONFIGURED"}</span>
        </div>
        <div>V 0.1.0</div>
      </footer>
    </div>
  );
}
