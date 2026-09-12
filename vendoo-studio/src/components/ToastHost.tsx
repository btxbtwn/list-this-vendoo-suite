import { useSyncExternalStore } from "react";
import { closeToast, readToasts, subscribeToasts } from "../ui/toast";

export function ToastHost() {
  const items = useSyncExternalStore(subscribeToasts, readToasts, readToasts);

  if (items.length === 0) return null;

  return (
    <div className="toast-viewport" aria-live="polite">
      {items.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.type}`} role={toast.type === "error" ? "alert" : "status"}>
          <div className="toast-copy">
            <div className="toast-title">{toast.title}</div>
            {toast.description ? <div className="toast-description">{toast.description}</div> : null}
          </div>
          <button type="button" className="toast-close" aria-label="Dismiss" onClick={() => closeToast(toast.id)}>
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}
