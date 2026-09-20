import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Suggestion, SuggestionKind } from "../api/types";

export const SUGGESTION_KIND_LABELS: Record<SuggestionKind, string> = {
  failed: "Fix failed listing",
  ready_to_generate: "Generate listing",
  fix_validation: "Fix listing fields",
  stale_active: "Refresh or consider price drop",
  ready_to_review: "Review and send",
};

const SIDEBAR_PAGE = 5;

export function suggestionKindLabel(kind: string): string {
  return SUGGESTION_KIND_LABELS[kind as SuggestionKind] || kind.replace(/_/g, " ");
}

export function staleAgeLabel(days: number): string {
  return days === 1 ? "1 day" : `${days} days`;
}

export function suggestionCaption(
  suggestion: Pick<Suggestion, "kind" | "age_days">,
  compact: boolean,
): string {
  const label = suggestionKindLabel(suggestion.kind);
  if (!compact || suggestion.kind !== "stale_active" || suggestion.age_days == null) {
    return label;
  }
  return `${staleAgeLabel(suggestion.age_days)} · ${label}`;
}

export function SuggestionsPanel({
  variant,
  selectedConvId,
  onSelect,
}: {
  variant: "workspace" | "sidebar";
  selectedConvId?: string | null;
  onSelect: (conversationId: string) => void;
}) {
  const { data, isFetched } = useQuery({
    queryKey: ["suggestions"],
    queryFn: api.suggestions.list,
    refetchInterval: 2000,
  });
  const suggestions = data?.suggestions || [];
  const [expanded, setExpanded] = useState(true);
  const [visibleCount, setVisibleCount] = useState(SIDEBAR_PAGE);
  const visible = variant === "workspace"
    ? suggestions
    : expanded
      ? suggestions.slice(0, visibleCount)
      : [];

  if (variant === "sidebar") {
    if (!suggestions.length) return null;
    const hidden = Math.max(0, suggestions.length - visible.length);
    return (
      <section className="suggestions-shelf" aria-label="Suggestions">
        <button
          type="button"
          className="sidebar-shelf-header"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          <span className="sidebar-shelf-label">
            {expanded ? "Suggestions" : `Suggestions (${suggestions.length})`}
          </span>
          <span className="sidebar-shelf-rule" aria-hidden="true" />
          <svg className="sidebar-shelf-chevron" width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {visible.map((item) => (
          <SuggestionRow
            key={item.conversation_id}
            suggestion={item}
            selected={selectedConvId === item.conversation_id}
            compact
            onSelect={onSelect}
          />
        ))}
        {expanded && hidden > 0 && (
          <button
            type="button"
            className="sidebar-show-more"
            onClick={() => setVisibleCount((count) => count + SIDEBAR_PAGE)}
          >
            Show {Math.min(hidden, SIDEBAR_PAGE)} more
          </button>
        )}
      </section>
    );
  }

  return (
    <section className="empty-suggestions" aria-label="Suggestions">
      {isFetched && suggestions.length === 0 ? (
        <p className="empty-suggestions-empty">No suggestions right now</p>
      ) : (
        visible.map((item) => (
          <SuggestionRow
            key={item.conversation_id}
            suggestion={item}
            selected={selectedConvId === item.conversation_id}
            compact={false}
            onSelect={onSelect}
          />
        ))
      )}
    </section>
  );
}

function SuggestionRow({
  suggestion,
  selected,
  compact,
  onSelect,
}: {
  suggestion: Suggestion;
  selected: boolean;
  compact: boolean;
  onSelect: (conversationId: string) => void;
}) {
  const label = suggestionCaption(suggestion, compact);
  return (
    <button
      type="button"
      className={`suggestion-row${compact ? " is-compact" : ""}${selected ? " selected" : ""}`}
      title={`${suggestionKindLabel(suggestion.kind)}. ${suggestion.reason}`}
      onClick={() => onSelect(suggestion.conversation_id)}
    >
      <div className="nav-thumb" aria-hidden="true">
        {suggestion.cover_photo_url ? (
          <img className="nav-thumb-img" src={suggestion.cover_photo_url} alt="" loading="lazy" draggable={false} />
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="1.5" y="2.5" width="13" height="11" rx="2" stroke="currentColor" strokeWidth="1.2" />
            <path d="M2 11l3.2-3.2a1.2 1.2 0 011.7 0L10 10.9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            <circle cx="10.4" cy="6" r="1.1" fill="currentColor" />
          </svg>
        )}
      </div>
      <div className="nav-link-body">
        <div className="nav-link-title">{suggestion.title}</div>
        {compact ? (
          <div className="suggestion-row-reason">{label}</div>
        ) : (
          <>
            <div className="suggestion-row-action">{label}</div>
            <div className="suggestion-row-reason">{suggestion.reason}</div>
          </>
        )}
      </div>
    </button>
  );
}
