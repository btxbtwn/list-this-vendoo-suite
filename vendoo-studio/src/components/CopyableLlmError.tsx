import React from "react";

type Blocker = { field?: string; message?: string };

function fieldPathToTarget(field?: string): { marketplace: string; field: string } | null {
  const raw = String(field || "").trim();
  if (!raw) return null;
  const specifics = raw.match(/^([a-z]+)_specifics\.(.+)$/i);
  if (specifics) {
    return { marketplace: specifics[1].toLowerCase(), field: specifics[2] };
  }
  if (raw.includes(".")) {
    const [head, ...rest] = raw.split(".");
    return { marketplace: head.toLowerCase() === "general" ? "general" : head.toLowerCase(), field: rest.join(".") };
  }
  return { marketplace: "general", field: raw };
}

export function validationErrorsPrompt(blockers: Blocker[], listingTitle?: string): string {
  const title = String(listingTitle || "").trim() || "this listing";
  const lines = blockers
    .filter((item) => item.message)
    .map((item) => {
      const target = fieldPathToTarget(item.field);
      const where = target
        ? `${target.marketplace} / ${target.field}`
        : (item.field || "listing");
      return `- ${where}: ${item.message}`;
    });
  const examples = blockers
    .map((item) => fieldPathToTarget(item.field))
    .filter(Boolean)
    .slice(0, 3)
    .map((target) => `{"marketplace":"${target!.marketplace}","field":"${target!.field}","value":"..."}`);

  return `Fix these Studio validation errors so Send to Vendoo can proceed for "${title}".

Update ONLY the fields needed to clear the errors below. Use photo analysis and seller notes. Do not invent unsupported facts.
For eBay Season intelligently choose exactly one of Spring, Summer, Fall, or Winter from the item (title, fabric, type, photos). Never leave it blank and never use Does Not Apply.
For every marketplace field shown after Show Optional Fields (eBay, Etsy, Depop, and others): fill a real value when it pertains to the item. Use Does Not Apply only when it literally does not apply.

Validation errors:
${lines.join("\n") || "- (no details)"}

Reply with JSON in this exact shape:

\`\`\`json
{"missing_fields":[${examples.join(",") || '{"marketplace":"ebay","field":"Season","value":"..."}'}]}
\`\`\`

Use marketplace ids and field names that match the errors. Studio saves the listing JSON from this reply; filling the live Vendoo draft is a separate step.
`;
}

export function jobErrorPrompt(errorText: string, listingTitle?: string): string {
  const title = String(listingTitle || "").trim() || "this listing";
  const detail = String(errorText || "").trim() || "(no details)";
  return `Fix this Studio job / verification error for "${title}".

Job error:
${detail}

From photos and seller notes, fill what you can. For fields you cannot support, say so clearly.
Prefer updating listing values with JSON in this shape:

\`\`\`json
{"missing_fields":[{"marketplace":"ebay","field":"Brand","value":"..."}]}
\`\`\`

Use marketplace ids and field names from the error. Do not publish.
`;
}

export function CopyableLlmError({
  text,
  prompt,
  onAskChat,
  className,
}: {
  text: string;
  prompt: string;
  onAskChat?: (text: string) => void;
  className?: string;
}) {
  const [copied, setCopied] = React.useState(false);
  const body = String(text || "").trim();
  if (!body) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={`llm-error-card${className ? ` ${className}` : ""}`}>
      <div className="llm-error-text text-xs text-error">{body}</div>
      <p className="llm-error-hint">
        Copy this and paste it into chat so the listing assistant can fix the fields.
      </p>
      <div className="llm-error-actions">
        <button type="button" className="btn btn-sm btn-outline" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy for chat"}
        </button>
        {onAskChat && (
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={() => onAskChat(prompt)}
          >
            Ask chat
          </button>
        )}
      </div>
    </div>
  );
}
