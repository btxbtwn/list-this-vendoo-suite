import React, { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  convId: string;
}

export function PhotoTray({ convId }: Props) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const { data: photos } = useQuery({
    queryKey: ["photos", convId],
    queryFn: () => api.conversations.photos(convId),
  });

  const deleteMutation = useMutation({
    mutationFn: (photoId: string) => api.conversations.deletePhoto(convId, photoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["photos", convId] });
    },
  });

  const doUpload = async (fileList: FileList) => {
    if (!fileList || fileList.length === 0) return;
    setUploading(true);
    setUploadError(null);
    try {
      await api.conversations.uploadPhotos(convId, Array.from(fileList));
      await queryClient.invalidateQueries({ queryKey: ["photos", convId] });
    } catch (err: any) {
      setUploadError(err.message || "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) await doUpload(e.target.files);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files.length) await doUpload(e.dataTransfer.files);
  };

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
      style={{
        padding: "8px 16px",
        borderBottom: "1px solid var(--color-border)",
        background: "var(--color-bg)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: photos?.length ? 8 : 0 }}>
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? "Uploading..." : "Add Photos"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*"
          style={{ display: "none" }}
          onChange={handleFileSelect}
        />
        <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
          {photos?.length || 0} photos · drag to add more
        </span>
      </div>
      {uploadError && (
        <div style={{ fontSize: 11, color: "var(--color-error)", marginBottom: 8 }}>{uploadError}</div>
      )}
      {photos && photos.length > 0 && (
        <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 4 }}>
          {photos.map((p: any, idx: number) => (
            <div
              key={p.id}
              style={{
                position: "relative",
                width: 56,
                height: 56,
                borderRadius: 4,
                overflow: "hidden",
                flexShrink: 0,
                border: "2px solid var(--color-border)",
              }}
            >
              <img
                src={p.url}
                alt={`Photo ${idx + 1}`}
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
              <button
                className="btn"
                style={{
                  position: "absolute",
                  top: 0,
                  right: 0,
                  width: 18,
                  height: 18,
                  padding: 0,
                  fontSize: 10,
                  background: "rgba(0,0,0,0.6)",
                  color: "white",
                  borderRadius: "0 0 0 4px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
                onClick={() => deleteMutation.mutate(p.id)}
              >
                x
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
