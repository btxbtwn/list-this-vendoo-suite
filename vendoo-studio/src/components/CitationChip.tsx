import { useEffect, useRef, useState } from "react";
import {
  CITATION_MAX_COMMENT_LENGTH,
  citationPreview,
  withChatCitationComment,
  type ChatCitation,
} from "./chatCitations";

export function QuoteIcon({ size = 11 }: { size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 11H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v8a4 4 0 0 1-4 4" />
      <path d="M20 11h-4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v8a4 4 0 0 1-4 4" />
    </svg>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />
      <path d="m15 5 4 4" />
    </svg>
  );
}

/** The note editor that opens from a chip's pencil, following T3 Code's popover. */
function CitationCommentEditor({
  citation,
  onSave,
  onSaveAndSend,
  onCancel,
}: {
  citation: ChatCitation;
  onSave: (comment: string) => void;
  onSaveAndSend: (comment: string) => void;
  onCancel: () => void;
}) {
  const [comment, setComment] = useState(citation.comment ?? "");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const tooLong = comment.length > CITATION_MAX_COMMENT_LENGTH;

  useEffect(() => {
    inputRef.current?.focus({ preventScroll: true });
  }, []);

  return (
    <div
      className="citation-comment-editor"
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.nativeEvent.isComposing) return;
        if (event.key === "Escape") {
          event.preventDefault();
          onCancel();
        }
      }}
    >
      <textarea
        ref={inputRef}
        aria-label="Comment on quoted text"
        aria-description="Enter to save the comment; Command/Ctrl+Enter to save and send; Shift+Enter for a new line."
        aria-invalid={tooLong || undefined}
        placeholder="Add an optional comment..."
        rows={2}
        value={comment}
        onChange={(event) => setComment(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
          event.preventDefault();
          if (tooLong) return;
          if (event.metaKey || event.ctrlKey) {
            onSaveAndSend(comment);
          } else {
            onSave(comment);
          }
        }}
      />
      {tooLong ? (
        <p role="status" className="citation-comment-error">
          Comments can contain up to {CITATION_MAX_COMMENT_LENGTH.toLocaleString()} characters.
        </p>
      ) : null}
      <div className="citation-comment-actions">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onPointerDown={(event) => event.preventDefault()}
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={tooLong}
          onPointerDown={(event) => event.preventDefault()}
          onClick={() => onSave(comment)}
        >
          {tooLong ? "Shorten comment" : "Save"}
        </button>
      </div>
    </div>
  );
}

/**
 * One quote, shown the same way in the composer and inside a sent message —
 * T3 Code's citation chip: a quote mark, the note or the quote, and (in the
 * composer) the note editor and a way to drop it.
 */
export function CitationChip({
  citation,
  composer = false,
  onReveal,
  onRemove,
  onComment,
  onCommentAndSend,
}: {
  citation: ChatCitation;
  composer?: boolean;
  onReveal: (citation: ChatCitation) => void;
  onRemove?: (citation: ChatCitation) => void;
  onComment?: (citation: ChatCitation) => void;
  onCommentAndSend?: (citation: ChatCitation) => void;
}) {
  const [editing, setEditing] = useState(false);
  const label = citationPreview(citation);
  const title = citation.comment ? `${citation.text}\n\nComment: ${citation.comment}` : citation.text;

  return (
    <span className={`citation-chip${composer ? "" : " is-inline"}`} data-citation-chip="true">
      <button
        type="button"
        className="citation-chip-label"
        title={title}
        aria-label={`View cited text: ${label}`}
        onClick={() => onReveal(citation)}
      >
        <QuoteIcon />
        <span>{label}</span>
      </button>
      {onComment ? (
        <span className="citation-chip-comment">
          <button
            type="button"
            className="citation-chip-action"
            aria-label={citation.comment ? "Edit citation comment" : "Add comment to citation"}
            aria-expanded={editing}
            onClick={() => setEditing((open) => !open)}
          >
            <PencilIcon />
          </button>
          {editing ? (
            <CitationCommentEditor
              citation={citation}
              onSave={(comment) => {
                onComment(withChatCitationComment(citation, comment));
                setEditing(false);
              }}
              onSaveAndSend={(comment) => {
                const next = withChatCitationComment(citation, comment);
                onComment(next);
                setEditing(false);
                onCommentAndSend?.(next);
              }}
              onCancel={() => setEditing(false)}
            />
          ) : null}
        </span>
      ) : null}
      {onRemove ? (
        <button
          type="button"
          className="citation-chip-action"
          aria-label="Remove quote"
          onClick={() => onRemove(citation)}
        >
          ×
        </button>
      ) : null}
    </span>
  );
}
