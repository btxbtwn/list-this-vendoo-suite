import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { dragHasFiles, groupImageFilesByFolder, listingTitleForFolder } from "../photoDrop";
import type { Photo } from "../api/types";
import { addToast } from "../ui/toast";

const PHOTO_DRAG_TYPE = "application/x-vendoo-photo-id";

interface Props {
  convId: string;
  /** When a folder pick expands into several item folders, App can focus the first draft. */
  onBulkListingsCreated?: (convIds: string[]) => void;
}

function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) {
    return items;
  }
  const next = items.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

export function PhotoTray({ convId, onBulkListingsCreated }: Props) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const lightboxRef = useRef<HTMLDivElement>(null);
  const suppressClickRef = useRef(false);
  const dragIdRef = useRef<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropId, setDropId] = useState<string | null>(null);

  const { data: photos } = useQuery({
    queryKey: ["photos", convId],
    queryFn: () => api.conversations.photos(convId),
  });

  const deleteMutation = useMutation({
    mutationFn: (photoId: string) => api.conversations.deletePhoto(convId, photoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["photos", convId] });
      // The sidebar thumbnail comes from the conversation list's cover photo.
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const reorderMutation = useMutation({
    mutationFn: (orderedIds: string[]) => api.conversations.reorderPhotos(convId, orderedIds),
    onMutate: async (orderedIds) => {
      await queryClient.cancelQueries({ queryKey: ["photos", convId] });
      const previous = queryClient.getQueryData<Photo[]>(["photos", convId]);
      if (previous) {
        const byId = new Map(previous.map((photo) => [photo.id, photo]));
        queryClient.setQueryData(
          ["photos", convId],
          orderedIds.map((id) => byId.get(id)).filter((photo): photo is Photo => Boolean(photo)),
        );
      }
      return { previous };
    },
    onError: (err: Error, _orderedIds, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["photos", convId], context.previous);
      }
      setUploadError(err.message || "Reorder failed");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["photos", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const previewIndex = photos?.findIndex((p) => p.id === previewId) ?? -1;
  const previewPhoto = photos && previewIndex >= 0 ? photos[previewIndex] : null;

  useEffect(() => {
    setPreviewId(null);
    setDragId(null);
    setDropId(null);
  }, [convId]);

  useEffect(() => {
    if (previewId && photos && !photos.some((p) => p.id === previewId)) {
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

  const canReorder = (photos?.length || 0) > 1;

  const resetDrag = () => {
    dragIdRef.current = null;
    setDragId(null);
    setDropId(null);
    window.setTimeout(() => {
      suppressClickRef.current = false;
    }, 150);
  };

  const onThumbDragStart = (event: React.DragEvent<HTMLDivElement>, photoId: string) => {
    if (!canReorder) {
      event.preventDefault();
      return;
    }
    suppressClickRef.current = true;
    dragIdRef.current = photoId;
    setDragId(photoId);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(PHOTO_DRAG_TYPE, photoId);
    event.dataTransfer.setData("text/plain", photoId);
  };

  const onThumbDragOver = (event: React.DragEvent<HTMLDivElement>, photoId: string) => {
    const sourceId = dragIdRef.current;
    if (!sourceId || sourceId === photoId) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    if (dropId !== photoId) setDropId(photoId);
  };

  const onThumbDrop = (event: React.DragEvent<HTMLDivElement>, photoId: string) => {
    // Files dropped on a thumbnail are an upload, not a reorder — let the
    // window-level drop handler take them.
    if (dragHasFiles(event.dataTransfer)) return;
    event.preventDefault();
    event.stopPropagation();
    const sourceId = dragIdRef.current || event.dataTransfer.getData(PHOTO_DRAG_TYPE) || event.dataTransfer.getData("text/plain");
    resetDrag();
    if (!photos || !sourceId || sourceId === photoId) return;
    const from = photos.findIndex((photo) => photo.id === sourceId);
    const to = photos.findIndex((photo) => photo.id === photoId);
    const next = moveItem(photos, from, to);
    if (next === photos) return;
    setUploadError(null);
    reorderMutation.mutate(next.map((photo) => photo.id));
  };

  const openPreview = (photoId: string) => {
    if (suppressClickRef.current) return;
    setPreviewId(photoId);
  };

  const doUpload = async (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (!files.length) return;
    setUploading(true);
    setUploadError(null);
    try {
      const groups = groupImageFilesByFolder(files);
      if (groups.length > 1) {
        const createdIds: string[] = [];
        const errors: string[] = [];
        let totalPhotos = 0;
        for (const group of groups) {
          const conv = await api.conversations.create({
            title: listingTitleForFolder(group.folder),
          });
          const result = await api.conversations.uploadPhotos(conv.id, group.files);
          createdIds.push(conv.id);
          totalPhotos += result.count;
          errors.push(...(result.errors || []));
          await queryClient.invalidateQueries({ queryKey: ["photos", conv.id] });
        }
        queryClient.invalidateQueries({ queryKey: ["conversations"] });
        onBulkListingsCreated?.(createdIds);
        const title = `Started ${createdIds.length} listings`;
        const description = `Added ${totalPhotos} photo${totalPhotos === 1 ? "" : "s"} from separate folders.`;
        if (errors.length) {
          setUploadError(errors.join("; "));
          addToast({ type: "error", title, description: errors.join("; ") });
        } else {
          addToast({ type: "success", title, description });
        }
        return;
      }

      const only = groups[0]?.files || files;
      const result = await api.conversations.uploadPhotos(convId, only);
      await queryClient.invalidateQueries({ queryKey: ["photos", convId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      const errors = result.errors || [];
      if (errors.length) {
        setUploadError(errors.join("; "));
      }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";
    }
  };

  return (
    <div className="photo-tray">
      {/* Same caps heading as the Notes / Pricing / Measurements sections below. */}
      <div className="item-section-header">
        <h3 className="item-section-title">Photos</h3>
        <span className="photo-tray-meta">
          {photos?.length || 0} photos{canReorder ? " · drag to reorder" : " · or drop them anywhere"}
        </span>
        <button className="btn btn-secondary btn-sm" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
          {uploading ? "Uploading..." : "Add Photos"}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => folderInputRef.current?.click()}
          disabled={uploading}
          title="Choose a folder of photos, or a parent folder of item folders for bulk drafts"
        >
          Add Folder
        </button>
        <input ref={fileInputRef} type="file" multiple accept="image/*" style={{ display: "none" }} onChange={(e) => { if (e.target.files) void doUpload(e.target.files); }} />
        <input
          ref={folderInputRef}
          type="file"
          multiple
          accept="image/*"
          style={{ display: "none" }}
          // Chromium/WebKit folder pick; React has no typed prop for these.
          {...({ webkitdirectory: "", directory: "" } as React.InputHTMLAttributes<HTMLInputElement>)}
          onChange={(e) => { if (e.target.files) void doUpload(e.target.files); }}
        />
      </div>
      {uploadError && <div className="photo-tray-error text-2xs text-error">{uploadError}</div>}
      {photos && photos.length > 0 && (
        <div className="photo-strip">
          {photos.map((p, i) => (
            <div
              key={p.id}
              className={[
                "photo-thumb",
                canReorder ? "photo-thumb-reorderable" : "",
                dragId === p.id ? "is-dragging" : "",
                dropId === p.id ? "is-drop-target" : "",
              ].filter(Boolean).join(" ")}
              draggable={canReorder}
              onDragStart={(event) => onThumbDragStart(event, p.id)}
              onDragOver={(event) => onThumbDragOver(event, p.id)}
              onDrop={(event) => onThumbDrop(event, p.id)}
              onDragEnd={resetDrag}
              title={canReorder ? "Drag to set upload order" : undefined}
            >
              <div
                className="photo-thumb-open"
                role="button"
                tabIndex={0}
                onClick={() => openPreview(p.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    openPreview(p.id);
                  }
                }}
                aria-label={`View photo ${i + 1} enlarged`}
              >
                <img src={p.url} alt="" draggable={false} />
              </div>
              <div className="photo-thumb-num">{String(i + 1).padStart(2, "0")}</div>
              <button
                type="button"
                className="photo-thumb-delete"
                aria-label={`Delete photo ${i + 1}`}
                onClick={(event) => {
                  event.stopPropagation();
                  deleteMutation.mutate(p.id);
                }}
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
          <img
            className="photo-lightbox-image"
            src={previewPhoto.url}
            alt={`Photo ${previewIndex + 1}`}
            onClick={() => setPreviewId(null)}
          />
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
