import type { SendPreview } from "../api/types";
import { ListingChangeList } from "./ListingChangeList";
import { ListingReviewDialog } from "./ListingReviewDialog";

export function SendReview({ preview, loading, error, busy, onClose, onRetry, onApprove }: {
  preview?: SendPreview;
  loading: boolean;
  error?: string | null;
  busy: boolean;
  onClose: () => void;
  onRetry: () => void;
  onApprove: (reviewId: string) => void;
}) {
  return (
    <ListingReviewDialog title={preview?.mode === "create" ? "Review new Vendoo draft" : "Review Vendoo changes"} onClose={onClose} busy={busy} actions={
      <>
        {error && <button type="button" className="btn btn-secondary" disabled={busy || loading} onClick={onRetry}>Refresh preview</button>}
        <button type="button" className="btn btn-primary" disabled={!preview || loading || busy || Boolean(error)} onClick={() => preview && onApprove(preview.review_id)}>
          {busy ? "Adding to queue…" : preview?.mode === "create" ? "Approve and send draft" : "Approve and update draft"}
        </button>
      </>
    }>
      <p className="text-muted">Review the fields that will be saved to the Vendoo form. Nothing is published. Live marketplace listings keep their current version.</p>
      {loading && <p role="status">Reading the current draft and preparing your preview…</p>}
      {error && <p role="alert" className="text-error">{error}</p>}
      {preview && !loading && <>
        <p>{preview.photo_action === "keep" ? `Keep the ${preview.photo_count} photos already in Vendoo. Local photo edits are not included in this update.` : `Upload ${preview.photo_count} photos in their current order.`}</p>
        <p>{preview.changes.length} field {preview.changes.length === 1 ? "change" : "changes"}</p>
        {preview.warnings.length > 0 && <details className="listing-review-warnings"><summary>Fields to check ({preview.warnings.length})</summary><ul>{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>}
        <ListingChangeList changes={preview.changes} beforeLabel="In Vendoo" afterLabel="After saving" />
      </>}
    </ListingReviewDialog>
  );
}
