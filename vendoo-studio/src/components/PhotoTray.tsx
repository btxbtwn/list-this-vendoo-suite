import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

interface Props {
  convId: string;
}

export function PhotoTray({ convId }: Props) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lightboxRef = useRef<HTMLDivElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);

  const { data: photos } = useQuery({
    queryKey: ["photos", convId],
    queryFn: () => api.conversations.photos(convId),
  });

  const deleteMutation = useMutation({
    mutationFn: (photoId: string) => api.conversations.deletePhoto(convId, photoId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["photos", convId] }),
  });

  const previewIndex = photos?.findIndex((p: any) => p.id === previewId) ?? -1;
  const previewPhoto = photos && previewIndex >= 0 ? photos[previewIndex] : null;

  useEffect(() => {
    setPreviewId(null);
  }, [convId]);

  useEffect(() => {
    if (previewId && photos && !photos.some((p: any) => p.id === previewId)) {
      setPreviewId(null);
    }
  }, [photos, previewId]);

  useEffect(() => {
    if (!previewPhoto) return;
    lightboxRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPreviewId(null);
    };
    document.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [previewPhoto]);

  const stepPreview = (delta: number) => {
    if (!photos || photos.length < 2 || previewIndex < 0) return;
    const next = (previewIndex + delta + photos.length) % photos.length;
    setPreviewId(photos[next].id);
  };

  const onLightboxKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      stepPreview(-1);
    }
    if (e.key === "ArrowRight") {
      e.preventDefault();
      stepPreview(1);
    }
  };

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

  return (
    <div className="photo-tray" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length) doUpload(e.dataTransfer.files); }}>
      <div className="photo-tray-controls">
        <button className="btn btn-secondary btn-sm" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          {uploading ? "Uploading..." : "Add Photos"}
        </button>
        <input ref={fileInputRef} type="file" multiple accept="image/*" style={{ display: "none" }} onChange={(e) => { if (e.target.files) doUpload(e.target.files); }} />
        <span className="photo-tray-meta">{photos?.length || 0} photos</span>
        {uploadError && <span className="text-2xs text-error font-mono">{uploadError}</span>}
      </div>
      {photos && photos.length > 0 && (
        <div className="photo-strip">
          {photos.map((p: any, i: number) => (
            <div key={p.id} className="photo-thumb">
              <button
                type="button"
                className="photo-thumb-open"
                onClick={() => setPreviewId(p.id)}
                aria-label={`View photo ${i + 1} enlarged`}
              >
                <img src={p.url} alt="" />
              </button>
              <div className="photo-thumb-num">{String(i + 1).padStart(2, "0")}</div>
              <button
                type="button"
                className="photo-thumb-delete"
                aria-label={`Delete photo ${i + 1}`}
                onClick={() => deleteMutation.mutate(p.id)}
              >
                x
              </button>
            </div>
          ))}
        </div>
      )}
      {previewPhoto && photos && createPortal(
        <div
          ref={lightboxRef}
          className="photo-lightbox"
          role="dialog"
          aria-modal="true"
          tabIndex={-1}
          aria-label={`Photo ${previewIndex + 1} of ${photos.length}`}
          onKeyDown={onLightboxKeyDown}
          onClick={(e) => { if (e.target === e.currentTarget) setPreviewId(null); }}
        >
          <button type="button" className="photo-lightbox-close" onClick={() => setPreviewId(null)} aria-label="Close">
            x
          </button>
          {photos.length > 1 && (
            <button type="button" className="photo-lightbox-nav photo-lightbox-prev" onClick={() => stepPreview(-1)} aria-label="Previous photo">
              ‹
            </button>
          )}
          <img className="photo-lightbox-image" src={previewPhoto.url} alt={`Photo ${previewIndex + 1}`} />
          {photos.length > 1 && (
            <button type="button" className="photo-lightbox-nav photo-lightbox-next" onClick={() => stepPreview(1)} aria-label="Next photo">
              ›
            </button>
          )}
          <div className="photo-lightbox-meta">{String(previewIndex + 1).padStart(2, "0")} / {String(photos.length).padStart(2, "0")}</div>
        </div>,
        document.body
      )}
    </div>
  );
}
