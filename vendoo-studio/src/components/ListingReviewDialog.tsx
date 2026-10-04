import { useEffect, useId, useRef, type ReactNode } from "react";

export function ListingReviewDialog({ title, onClose, children, actions, busy = false }: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  actions?: ReactNode;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog ref={ref} className="confirm-dialog-popup listing-review-dialog" aria-labelledby={titleId}
      onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
      <div className="confirm-dialog-header"><h2 id={titleId} className="confirm-dialog-title">{title}</h2></div>
      <div className="listing-review-content">{children}</div>
      <div className="confirm-dialog-footer">
        <button type="button" className="btn btn-outline" disabled={busy} onClick={onClose}>Close</button>
        {actions}
      </div>
    </dialog>
  );
}
