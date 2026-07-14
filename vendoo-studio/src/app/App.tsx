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

  const { data: status } = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 10000 });
  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: api.conversations.list,
  });

  const createConv = useMutation({
    mutationFn: () => api.conversations.create({ title: "New Listing" }),
    onSuccess: (conv) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setSelectedConvId(conv.id);
      setActiveView("listings");
    },
  });

  const deleteConv = useMutation({
    mutationFn: (convId: string) => api.conversations.delete(convId),
    onSuccess: (_data, convId) => {
      if (selectedConvId === convId) {
        setSelectedConvId(null);
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <div className="app-shell">
      <div className="app-content">
        <aside className="panel sidebar">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h2 style={{ fontSize: 16, fontWeight: 600 }}>Listings</h2>
            <button className="btn btn-primary btn-sm" onClick={() => createConv.mutate()}>
              + New
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {conversations?.map((c: any) => (
              <div
                key={c.id}
                style={{ display: "flex", gap: 4, alignItems: "center" }}
              >
                <button
                  className={`btn btn-secondary btn-sm`}
                  style={{
                    flex: 1,
                    justifyContent: "flex-start",
                    background: selectedConvId === c.id && activeView === "listings" ? "var(--color-surface-hover)" : undefined,
                  }}
                  onClick={() => { setSelectedConvId(c.id); setActiveView("listings"); }}
                >
                  {c.title || "Untitled"}
                  <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--color-text-muted)" }}>
                    {c.status}
                  </span>
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  title="Delete listing"
                  style={{ padding: "2px 6px", fontSize: 12, lineHeight: 1, flexShrink: 0 }}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm(`Delete "${c.title || "Untitled"}"?\nThis cannot be undone.`)) {
                      deleteConv.mutate(c.id);
                    }
                  }}
                >
                  {"\u2715"}
                </button>
              </div>
            ))}
            {(!conversations || conversations.length === 0) && (
              <div className="empty-state">
                <p>No listings yet</p>
                <button className="btn btn-primary btn-sm" onClick={() => createConv.mutate()}>
                  Create Listing
                </button>
              </div>
            )}
          </div>
          <div style={{ marginTop: 24, paddingTop: 12, borderTop: "1px solid var(--color-border)" }}>
            <button
              className={`btn btn-secondary btn-sm`}
              style={{
                justifyContent: "flex-start", width: "100%",
                background: activeView === "settings" ? "var(--color-surface-hover)" : undefined,
              }}
              onClick={() => setActiveView("settings")}
            >
              Settings
            </button>
          </div>
        </aside>

        <main className="panel main-panel">
          {activeView === "settings" ? (
            <SettingsPage />
          ) : selectedConvId ? (
            <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
              <PhotoTray convId={selectedConvId} />
              <ItemDetails convId={selectedConvId} />
              <div style={{ flex: 1, overflow: "hidden" }}>
                <ChatPanel convId={selectedConvId} />
              </div>
            </div>
          ) : (
            <div className="empty-state">
              <h3>Vendoo Listing Studio</h3>
              <p>Create a new listing or select one from the sidebar</p>
            </div>
          )}
        </main>

        <aside className="panel detail-panel">
          {activeView === "listings" && selectedConvId ? (
            <ListingEditor convId={selectedConvId} />
          ) : (
            <div className="empty-state">
              <p>Select a listing to edit</p>
            </div>
          )}
        </aside>
      </div>

      <footer className="status-bar">
        <div className="status-left">
          <ExtensionStatus />
          <span>
            {status?.provider_configured ? "MiMo configured" : "MiMo not configured"}
          </span>
        </div>
        <div>v0.1.0</div>
      </footer>
    </div>
  );
}
