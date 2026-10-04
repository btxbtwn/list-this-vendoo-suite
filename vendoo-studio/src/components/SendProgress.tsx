import { WorkingDuration } from "./WorkingDuration";

export function sendProgressLabel(step: string, photos?: { completed: number; total: number } | null): string {
  if (step === "vendoo_api_photos" && photos && photos.total > 0) {
    return `${photos.completed} of ${photos.total} photos uploaded`;
  }
  const labels: Record<string, string> = {
    vendoo_api_queued: "Waiting in the send queue…",
    vendoo_api_reviewed: "Preparing the reviewed draft…",
    vendoo_api_categories: "Resolving marketplace categories…",
    vendoo_api_specifics: "Reading category fields from Vendoo…",
    vendoo_api_fields: "Filling marketplace fields…",
    vendoo_api_photos: "Uploading photos to Vendoo…",
    vendoo_api_create: "Creating the Vendoo draft…",
    vendoo_api_patch: "Saving marketplace fields…",
    vendoo_api_verify: "Checking the saved Vendoo draft…",
  };
  return labels[step] || "Working with Vendoo…";
}

export function SendProgress({
  label,
  startedAt,
  photos,
}: {
  label: string;
  startedAt?: string | null;
  photos?: { completed: number; total: number } | null;
}) {
  const startedAtMs = startedAt ? Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(startedAt) ? startedAt : `${startedAt}Z`) : NaN;
  return (
    <div className="send-progress">
      <div className="send-progress-row" role="status">
        <span className="send-spinner" aria-hidden="true" />
        <span className="send-progress-label">{label}</span>
        {Number.isFinite(startedAtMs) && <WorkingDuration startedAtMs={startedAtMs} className="send-progress-percent" />}
      </div>
      {photos && photos.total > 0 && <progress className="send-photo-progress" aria-label="Photos uploaded" max={photos.total} value={photos.completed} />}
    </div>
  );
}
