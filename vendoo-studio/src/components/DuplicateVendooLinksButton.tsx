import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function DuplicateVendooLinksButton({ onSelect }: { onSelect: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const { data, isFetching, error } = useQuery({
    queryKey: ["duplicate-vendoo-links"],
    queryFn: api.conversations.duplicateVendooLinks,
    enabled: open,
    staleTime: 0,
  });

  useEffect(() => {
    if (!open) return;
    const triggerButton = trigger.current;
    closeButton.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      }
      if (event.key === "Tab") {
        const controls = popup.current?.querySelectorAll<HTMLElement>("button, a[href]");
        if (!controls?.length) return;
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", handleKey, true);
    return () => {
      window.removeEventListener("keydown", handleKey, true);
      triggerButton?.focus();
    };
  }, [open]);

  return (
    <>
      <button ref={trigger} type="button" className="btn btn-sm btn-outline"
        title="Check duplicate Vendoo links" aria-label="Check duplicate Vendoo links"
        onClick={() => setOpen(true)}>
        Check duplicates
      </button>
      {open && createPortal(
        <div className="confirm-dialog" role="presentation">
          <button type="button" className="confirm-dialog-backdrop" aria-label="Close" onClick={() => setOpen(false)} />
          <div ref={popup} className="confirm-dialog-popup changelog-popup" role="dialog"
            aria-modal="true" aria-labelledby="duplicate-vendoo-title">
            <div className="confirm-dialog-header">
              <h2 id="duplicate-vendoo-title" className="confirm-dialog-title">Duplicate Vendoo links</h2>
              <p className="confirm-dialog-description">Studio listings that share the same Vendoo item. Open a listing to review its link.</p>
            </div>
            <div className="changelog-body" aria-live="polite">
              {isFetching ? <p>Checking saved links…</p> : error ? (
                <p role="alert">{error.message}</p>
              ) : !data?.length ? <p>No duplicate Vendoo links found.</p> : data.map((group) => (
                <section key={group.vendoo_item_id} className="changelog-entry">
                  <a href={group.vendoo_url} target="_blank" rel="noopener noreferrer">Vendoo item {group.vendoo_item_id}</a>
                  <ul>
                    {group.listings.map((listing) => (
                      <li key={listing.id}>
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => {
                          setOpen(false);
                          onSelect(listing.id);
                        }}>{listing.title}</button>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
            <div className="confirm-dialog-footer">
              <button ref={closeButton} type="button" className="btn btn-primary" onClick={() => setOpen(false)}>Done</button>
            </div>
          </div>
        </div>, document.body,
      )}
    </>
  );
}
