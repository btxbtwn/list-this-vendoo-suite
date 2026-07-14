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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["photos", convId] }),
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
              <img src={p.url} alt="" />
              <div className="photo-thumb-num">{String(i + 1).padStart(2, "0")}</div>
              <button className="photo-thumb-delete" onClick={() => deleteMutation.mutate(p.id)}>x</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
