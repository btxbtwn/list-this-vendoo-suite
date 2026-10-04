import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ListingData } from "../api/types";
import { addToast } from "../ui/toast";
import { ListingChangeList } from "./ListingChangeList";
import { listingChanges } from "./listingChanges";
import { ListingReviewDialog } from "./ListingReviewDialog";

export function ListingHistory({ convId, listing, revisionId, busy, onClose }: {
  convId: string;
  listing: ListingData;
  revisionId: string;
  busy: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<{ selectedId: string; revisionId: string } | null>(null);
  const revisions = useQuery({
    queryKey: ["revisions", convId, revisionId], queryFn: () => api.listings.revisions(convId),
  });
  const earlier = revisions.data?.filter((revision) => revision.id !== revisionId) || [];
  const selectedId = selected || earlier[0]?.id;
  const confirming = confirmation?.selectedId === selectedId && confirmation?.revisionId === revisionId;
  const revision = useQuery({
    queryKey: ["revision", convId, selectedId],
    queryFn: () => api.listings.revision(convId, selectedId!), enabled: Boolean(selectedId),
  });
  const changes = revision.data ? listingChanges(revision.data.listing, listing) : [];
  const restore = useMutation({
    mutationFn: () => api.listings.restore(convId, selectedId!, revisionId),
    onSuccess: () => {
      for (const key of ["listing", "conversation", "conversations", "listing-fields", "revisions"]) {
        void queryClient.invalidateQueries({ queryKey: key === "conversations" ? [key] : [key, convId] });
      }
      addToast({ type: "success", title: "Earlier listing restored", description: "Your previous version is still in history. Review the restored listing before sending." });
      onClose();
    },
  });
  return (
    <ListingReviewDialog title="Listing history" onClose={onClose} busy={restore.isPending} actions={
      <button type="button" className="btn btn-primary" disabled={busy || !revision.data || !changes.length || restore.isPending}
        onClick={() => { if (confirming) restore.mutate(); else setConfirmation({ selectedId: selectedId!, revisionId }); }}>
        {restore.isPending ? "Restoring…" : confirming ? "Confirm restore" : "Restore this version"}
      </button>
    }>
      <p className="text-muted">Compare an earlier version with the current listing. Restoring changes Studio only; it does not send anything to Vendoo or restore photos.</p>
      {revisions.isPending ? <p role="status">Loading history…</p> : revisions.isError ? <p role="alert">{revisions.error.message}</p> : !earlier.length ? <p>No earlier versions yet.</p> : (
        <>
          <label className="label" htmlFor="listing-history-version">Earlier version</label>
          <select id="listing-history-version" className="input" value={selectedId} disabled={restore.isPending}
            onChange={(event) => { setSelected(event.target.value); setConfirmation(null); restore.reset(); }}>
            {earlier.map((entry) => <option key={entry.id} value={entry.id}>{new Date(entry.created_at.endsWith("Z") ? entry.created_at : `${entry.created_at}Z`).toLocaleString()} · {entry.source.replace(/_/g, " ")} · {entry.title}</option>)}
          </select>
          {revision.isPending ? <p role="status">Loading comparison…</p> : revision.isError ? <p role="alert">{revision.error.message}</p> : <ListingChangeList changes={changes} beforeLabel="Earlier version" afterLabel="Current listing" />}
        </>
      )}
      {busy && <p role="status">Wait for generation or sending to finish before restoring.</p>}
      {confirming && <p role="status">Replace the current listing with this earlier version? Your current version stays in history.</p>}
      {restore.isError && <p role="alert" className="text-error">{restore.error.message}</p>}
    </ListingReviewDialog>
  );
}
