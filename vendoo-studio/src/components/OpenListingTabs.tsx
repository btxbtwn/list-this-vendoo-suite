import { useEffect, useRef } from "react";

interface Props {
  tabs: { id: string; title: string }[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onCreate: () => void;
  creating: boolean;
}

export function OpenListingTabs({ tabs, selectedId, onSelect, onClose, onCreate, creating }: Props) {
  const createButton = useRef<HTMLButtonElement>(null);
  const focusTab = (id: string) => {
    const button = document.getElementById(`listing-tab-${id}`);
    button?.focus();
  };
  useEffect(() => {
    const button = selectedId ? document.getElementById(`listing-tab-${selectedId}`) : null;
    button?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selectedId]);

  const closeTab = (id: string) => {
    const index = tabs.findIndex((tab) => tab.id === id);
    const remaining = tabs.filter((tab) => tab.id !== id);
    onClose(id);
    const nextId = selectedId === id
      ? remaining[Math.min(index, remaining.length - 1)]?.id
      : selectedId;
    if (nextId) focusTab(nextId);
    else createButton.current?.focus();
  };

  return (
    <div className="open-listing-tabs">
      <div className="open-listing-tablist" role={tabs.length ? "tablist" : undefined} aria-label="Open listings">
        {tabs.map((tab, index) => (
          <div className={`open-listing-tab${selectedId === tab.id ? " selected" : ""}`} key={tab.id} role="presentation">
            <button
              id={`listing-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={selectedId === tab.id}
              aria-controls="listing-workspace-panel"
              tabIndex={selectedId === tab.id ? 0 : -1}
              className="open-listing-tab-title"
              title={tab.title}
              onClick={() => onSelect(tab.id)}
              onKeyDown={(event) => {
                let nextIndex: number;
                if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
                else if (event.key === "ArrowLeft") nextIndex = (index + tabs.length - 1) % tabs.length;
                else if (event.key === "Home") nextIndex = 0;
                else if (event.key === "End") nextIndex = tabs.length - 1;
                else if (event.key === "Delete") {
                  event.preventDefault();
                  closeTab(tab.id);
                  return;
                } else return;
                event.preventDefault();
                onSelect(tabs[nextIndex].id);
                focusTab(tabs[nextIndex].id);
              }}
            >
              {tab.title}
            </button>
            <button type="button" className="open-listing-tab-close" aria-label={`Close tab: ${tab.title}`} title="Close tab" tabIndex={selectedId === tab.id ? 0 : -1} onClick={() => closeTab(tab.id)}>×</button>
          </div>
        ))}
      </div>
      <button ref={createButton} type="button" className="open-listing-tab-new" aria-label="New listing" title="New listing" disabled={creating} onClick={onCreate}>+</button>
    </div>
  );
}
