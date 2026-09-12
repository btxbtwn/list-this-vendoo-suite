import { useEffect, useSyncExternalStore } from "react";
import {
  readConfirmDialogState,
  registerConfirmDialogHost,
  resolveConfirmDialogCopy,
  respondToConfirmDialog,
  subscribeConfirmDialog,
} from "../ui/confirmDialog";

export function ConfirmDialogHost() {
  const state = useSyncExternalStore(subscribeConfirmDialog, readConfirmDialogState, readConfirmDialogState);

  useEffect(() => registerConfirmDialogHost(), []);

  useEffect(() => {
    if (state.status !== "confirming") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      respondToConfirmDialog(false);
    };
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [state.status]);

  if (state.status !== "confirming") return null;

  const copy = resolveConfirmDialogCopy(state.message);
  const confirmClass = state.variant === "destructive" ? "btn btn-danger" : "btn btn-primary";

  return (
    <div className="confirm-dialog" role="presentation">
      <button type="button" className="confirm-dialog-backdrop" aria-label="Cancel" onClick={() => respondToConfirmDialog(false)} />
      <div
        className="confirm-dialog-popup"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby={copy.description ? "confirm-dialog-description" : undefined}
      >
        <div className="confirm-dialog-header">
          <h2 id="confirm-dialog-title" className="confirm-dialog-title">{copy.title}</h2>
          {copy.description ? (
            <p id="confirm-dialog-description" className="confirm-dialog-description">{copy.description}</p>
          ) : null}
        </div>
        <div className="confirm-dialog-footer">
          <button type="button" className="btn btn-outline" onClick={() => respondToConfirmDialog(false)}>
            Cancel
          </button>
          <button type="button" className={confirmClass} onClick={() => respondToConfirmDialog(true)}>
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
