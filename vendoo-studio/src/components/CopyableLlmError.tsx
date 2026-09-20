type Blocker = { field?: string; message?: string };

export type BlockerField = {
  marketplace?: string;
  field?: string;
  expected?: unknown;
  observed?: unknown;
  error?: unknown;
  options?: string[];
};

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

function listingLabel(listingTitle?: string): string {
  return String(listingTitle || "").trim() || "this listing";
}

function compactBlockerFields(fields?: BlockerField[] | null): BlockerField[] {
  if (!Array.isArray(fields)) return [];
  const seen = new Set<string>();
  const rows: BlockerField[] = [];
  for (const item of fields) {
    const marketplace = String(item?.marketplace || "").trim().toLowerCase();
    const field = String(item?.field || "").trim();
    if (!marketplace || !field) continue;
    const key = `${marketplace}:${field.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({
      marketplace,
      field,
      expected: item.expected,
      observed: item.observed,
      error: item.error,
      options: Array.isArray(item.options) ? item.options.slice(0, 20) : undefined,
    });
    if (rows.length >= 40) break;
  }
  return rows;
}

function parseFieldsFromErrorText(errorText: string): BlockerField[] {
  const text = String(errorText || "");
  const markets = "general|ebay|etsy|poshmark|mercari|depop";
  const re = new RegExp(`\\b(${markets})\\s*\\/\\s*([^,;]+?)(?=\\s*,\\s*(?:${markets})\\b|\\s*\\.\\s|$)`, "gi");
  const rows: BlockerField[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(re)) {
    const marketplace = String(match[1] || "").trim().toLowerCase();
    const field = String(match[2] || "").trim().replace(/\s+/g, " ");
    if (!marketplace || !field) continue;
    const key = `${marketplace}:${field.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push({ marketplace, field });
  }
  return rows;
}

function missingFieldsJsonExamples(fields: BlockerField[]): string {
  const examples = fields.slice(0, 4).map((item) => {
    const marketplace = item.marketplace || "ebay";
    const field = item.field || "Brand";
    return `{"marketplace":"${marketplace}","field":"${field}","value":"..."}`;
  });
  return examples.join(",") || '{"marketplace":"ebay","field":"Brand","value":"..."}';
}

function fieldLines(fields: BlockerField[]): string {
  return fields
    .map((item) => {
      const bits = [`- ${item.marketplace} / ${item.field}`];
      if (item.expected != null && String(item.expected).trim()) bits.push(`  expected: ${String(item.expected)}`);
      if (item.observed != null && String(item.observed).trim()) bits.push(`  observed: ${String(item.observed)}`);
      if (item.error != null && String(item.error).trim()) bits.push(`  error: ${String(item.error)}`);
      if (item.options?.length) bits.push(`  options: ${item.options.join(" | ")}`);
      return bits.join("\n");
    })
    .join("\n");
}

function replyShape(fields: BlockerField[]): string {
  return `Reply with JSON in this exact shape:

\`\`\`json
{"missing_fields":[${missingFieldsJsonExamples(fields)}]}
\`\`\`

Use marketplace ids and field names exactly as listed. Studio saves the listing JSON from this reply; filling the live Vendoo draft is a separate step. Do not publish.
`;
}

export function validationErrorsPrompt(blockers: Blocker[], listingTitle?: string): string {
  const title = listingLabel(listingTitle);
  const lines = blockers
    .filter((item) => item.message)
    .map((item) => {
      const target = fieldPathToTarget(item.field);
      const where = target
        ? `${target.marketplace} / ${target.field}`
        : (item.field || "listing");
      return `- ${where}: ${item.message}`;
    });
  const fields = compactBlockerFields(
    blockers
      .map((item) => fieldPathToTarget(item.field))
      .filter((target): target is { marketplace: string; field: string } => Boolean(target))
      .map((target) => ({ marketplace: target.marketplace, field: target.field })),
  );
  const examples = fields
    .slice(0, 3)
    .map((target) => `{"marketplace":"${target.marketplace}","field":"${target.field}","value":"..."}`);

  return `Fix these Studio validation errors so Send to Vendoo can proceed for "${title}".

Update EVERY field listed below so the errors clear. Use photo analysis and seller notes. Do not invent unsupported facts.
For eBay Season intelligently choose exactly one of Spring, Summer, Fall, or Winter from the item (title, fabric, type, photos). Never leave it blank and never use Does Not Apply.
For every marketplace field shown after Show Optional Fields (eBay, Etsy, Depop, and others): fill a real value when it pertains to the item. Use Does Not Apply only when it literally does not apply.

Validation errors:
${lines.join("\n") || "- (no details)"}

${fields.length ? `Fields to fill:\n${fieldLines(fields)}\n\n` : ""}Reply with JSON in this exact shape:

\`\`\`json
{"missing_fields":[${examples.join(",") || '{"marketplace":"ebay","field":"Season","value":"..."}'}]}
\`\`\`

Use marketplace ids and field names that match the errors. Studio saves the listing JSON from this reply; filling the live Vendoo draft is a separate step.
`;
}

export function jobErrorPrompt(
  errorText: string,
  listingTitle?: string,
  blockerFields?: BlockerField[] | null,
): string {
  const title = listingLabel(listingTitle);
  const detail = String(errorText || "").trim() || "(no details)";
  const fields = (() => {
    const fromPayload = compactBlockerFields(blockerFields);
    return fromPayload.length ? fromPayload : parseFieldsFromErrorText(detail);
  })();
  if (fields.length) {
    return `Fix this Studio job / verification error for "${title}".

Job error:
${detail}

Generate values for EVERY field listed below from photos and seller notes — both the fields named in the error and any other missed fields included here. Do not rewrite unrelated fields.

Fields:
${fieldLines(fields)}

${replyShape(fields)}`;
  }
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

/** Specialized Ask-chat prompt for completion pauses (gaps, shipping, category, optionals). */
export function completionBlockerPrompt(
  errorText: string,
  listingTitle?: string,
  blockerFields?: BlockerField[] | null,
): string {
  const title = listingLabel(listingTitle);
  const detail = String(errorText || "").trim() || "(no details)";
  const fields = (() => {
    const fromPayload = compactBlockerFields(blockerFields);
    return fromPayload.length ? fromPayload : parseFieldsFromErrorText(detail);
  })();
  const lower = detail.toLowerCase();

  if (/packaged shipping|shipping weight|package dimensions|mailer size/i.test(detail)) {
    const targets = fields.length
      ? fields
      : [
          { marketplace: "general", field: "Package Weight" },
          { marketplace: "general", field: "Package Dimensions" },
        ];
    return `Estimate packaged shipping for "${title}" so verification can continue.

Studio could not finish shipping estimates. From photos and item type/size, choose realistic packaged weight and package dimensions (mailer/box). Do not ask clarifying questions.

Pause reason:
${detail}

Fields to fill:
${fieldLines(targets) || "- general / Package Weight\n- general / Package Dimensions"}

${replyShape(targets)}`;
  }

  if (/categor(y|ies)/i.test(detail) && /align|differ|repair|set vendoo category/i.test(lower)) {
    return `Fix marketplace category alignment for "${title}".

Pause reason:
${detail}

Update listing category_path and/or marketplace category fields so they match the intended Vendoo category. Prefer the category already chosen for this listing. Do not invent a new tree unless the current path is clearly wrong.

${fields.length ? `Targets:\n${fieldLines(fields)}\n\n` : ""}${replyShape(
      fields.length ? fields : [{ marketplace: "general", field: "category_path" }],
    )}`;
  }

  if (/optional fields still need real values|show optional fields/i.test(detail)) {
    return `Fill marketplace optional fields for "${title}" (Show Optional Fields).

Pause reason:
${detail}

For each field below: use a real value when it pertains to the item. Use Does Not Apply only when it literally does not apply. Prefer photo analysis and seller notes. Do not invent unsupported brands or materials.

Fields:
${fieldLines(fields) || "- (see pause reason)"}

${replyShape(fields)}`;
  }

  if (/could not resolve from photos and notes/i.test(detail) || fields.length > 0) {
    return `Resolve these remaining listing fields for "${title}" so verification can continue.

Pause reason:
${detail}

Generate values for ONLY these fields from photos and seller notes. Do not rewrite unrelated fields.

Fields:
${fieldLines(fields) || "- (see pause reason)"}

${replyShape(fields)}`;
  }

  return jobErrorPrompt(detail, title);
}

export function emptyFieldsButtonLabel(count: number): string {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  if (n <= 0) return "Ask chat for fields";
  return `Ask chat for ${n} field${n === 1 ? "" : "s"}`;
}

export function CopyableLlmError({
  text,
  prompt,
  onAskChat,
  emptyFieldsCount = 0,
  emptyFieldsPrompt,
  className,
}: {
  text: string;
  prompt: string;
  onAskChat?: (text: string) => void;
  emptyFieldsCount?: number;
  emptyFieldsPrompt?: string;
  className?: string;
}) {
  const body = String(text || "").trim();
  const emptyCount = Math.max(0, Math.floor(Number(emptyFieldsCount) || 0));
  const canFillEmpty = Boolean(onAskChat && emptyFieldsPrompt && emptyCount > 0);
  // No error and nothing left to fill — nothing to show. With fields still
  // empty the card stays so its fill button survives the error clearing.
  if (!body && !canFillEmpty) return null;

  return (
    <div className={`llm-error-card${className ? ` ${className}` : ""}`}>
      {body && <div className="llm-error-text text-xs text-error">{body}</div>}
      {onAskChat && (
        <div className="llm-error-ask">
          <div className="llm-error-actions">
            {body && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                title="Send these errors to chat so it can fix them"
                onClick={() => onAskChat(prompt)}
              >
                Fix errors
              </button>
            )}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={!canFillEmpty}
              title={canFillEmpty
                ? "Send empty listing fields to chat. Does not change Vendoo yet."
                : "No empty listing fields to fill"}
              onClick={() => {
                if (!canFillEmpty || !emptyFieldsPrompt) return;
                onAskChat(emptyFieldsPrompt);
              }}
            >
              {emptyFieldsButtonLabel(emptyCount)}
            </button>
          </div>
          <p className="llm-error-ask-hint">
            Empty listing values — writes listing JSON only, not Vendoo.
          </p>
        </div>
      )}
    </div>
  );
}
