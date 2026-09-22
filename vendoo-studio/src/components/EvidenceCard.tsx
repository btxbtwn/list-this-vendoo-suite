import type { ReactNode } from "react";

export interface EvidenceField {
  label: string;
  value: string;
  source?: string;
}

export interface EvidenceReport {
  fields: EvidenceField[];
  measurements: EvidenceField[];
  flaws: string[];
  tagText: string[];
  uncertainties: string[];
  extra: string[];
}

// Order and naming follow format_photo_analysis in
// server/vendoo_studio/services/listing_generate.py.
const FIELD_ORDER = [
  "brand",
  "size",
  "color",
  "material",
  "style",
  "department",
  "category",
  "condition",
];

const SOURCE_RE = /\s*\(source:\s*([^)]+)\)\s*$/i;
const MEASUREMENT_RE = /\d/;

function sentenceCase(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function splitList(value: string, separator: string): string[] {
  return value
    .split(separator)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function parseEvidence(text: string): EvidenceReport | null {
  const lines = (text || "").split("\n");
  const report: EvidenceReport = {
    fields: [],
    measurements: [],
    flaws: [],
    tagText: [],
    uncertainties: [],
    extra: [],
  };
  const byKey = new Map<string, EvidenceField>();

  for (const raw of lines) {
    const stripped = raw.trim();
    if (!stripped || /^photo analysis/i.test(stripped)) continue;
    if (!stripped.startsWith("- ")) {
      report.extra.push(stripped);
      continue;
    }
    const body = stripped.slice(2).trim();
    const split = body.indexOf(":");
    if (split < 0) {
      report.extra.push(body);
      continue;
    }
    const key = body.slice(0, split).trim();
    let value = body.slice(split + 1).trim();
    if (!value) continue;

    const lower = key.toLowerCase();
    if (lower === "flaws") {
      report.flaws.push(...splitList(value, ","));
      continue;
    }
    if (lower === "uncertainties") {
      report.uncertainties.push(...splitList(value, ","));
      continue;
    }
    if (lower === "tag text") {
      report.tagText.push(...splitList(value, ";"));
      continue;
    }

    let source = "";
    const match = value.match(SOURCE_RE);
    if (match) {
      source = match[1].trim();
      value = value.replace(SOURCE_RE, "").trim();
    }
    const field: EvidenceField = { label: sentenceCase(key), value, source: source || undefined };
    if (FIELD_ORDER.includes(lower)) {
      byKey.set(lower, field);
    } else if (MEASUREMENT_RE.test(value)) {
      report.measurements.push(field);
    } else {
      byKey.set(lower, field);
    }
  }

  for (const key of FIELD_ORDER) {
    const field = byKey.get(key);
    if (field) {
      report.fields.push(field);
      byKey.delete(key);
    }
  }
  report.fields.push(...byKey.values());

  const empty =
    !report.fields.length &&
    !report.measurements.length &&
    !report.flaws.length &&
    !report.tagText.length &&
    !report.uncertainties.length;
  return empty ? null : report;
}

export function evidenceFieldCount(report: EvidenceReport): number {
  return (
    report.fields.length +
    report.measurements.length +
    (report.flaws.length ? 1 : 0) +
    (report.tagText.length ? 1 : 0)
  );
}

/* lucide `eye`. T3 Code heads a card with a muted 14px glyph and a sentence-case
   label (WorktreeSetupCard.tsx, ProposedPlanCard.tsx) rather than a colored bar. */
function EyeIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="evidence-key">{label}</dt>
      <dd className="evidence-value">{children}</dd>
    </>
  );
}

export function EvidenceCard({ text }: { text: string }) {
  const report = parseEvidence(text);
  const count = report ? evidenceFieldCount(report) : 0;

  return (
    <div className="evidence-card">
      <div className="evidence-header">
        <EyeIcon />
        <span className="evidence-title">Evidence</span>
        {count ? <span className="evidence-count">{count}</span> : null}
      </div>
      <div className="evidence-body">
        {report ? (
          <dl className="evidence-grid">
            {report.fields.map((field) => (
              <Row key={`${field.label}-${field.value}`} label={field.label}>
                {field.value}
                {field.source ? <span className="evidence-source">{field.source}</span> : null}
              </Row>
            ))}
            {report.measurements.length ? (
              <Row label="Measurements">
                <span className="evidence-inline">
                  {report.measurements.map((m) => (
                    <span className="evidence-measure" key={`${m.label}-${m.value}`}>
                      {m.label.toLowerCase()} <span className="evidence-number">{m.value}</span>
                    </span>
                  ))}
                </span>
              </Row>
            ) : null}
            {report.flaws.length ? (
              <Row label="Flaws">
                {report.flaws.map((flaw) => (
                  <span className="evidence-line" key={flaw}>
                    {flaw}
                  </span>
                ))}
              </Row>
            ) : null}
            {report.tagText.length ? (
              <Row label="Tag text">
                {report.tagText.map((tag) => (
                  <span className="evidence-line evidence-muted" key={tag}>
                    {tag}
                  </span>
                ))}
              </Row>
            ) : null}
            {report.uncertainties.length ? (
              <Row label="Unverified">
                <span className="evidence-muted">{report.uncertainties.join(", ")}</span>
              </Row>
            ) : null}
            {report.extra.length ? (
              <Row label="Notes">
                <span className="evidence-line">{report.extra.join("\n")}</span>
              </Row>
            ) : null}
          </dl>
        ) : (
          <div className="evidence-note">{text}</div>
        )}
      </div>
    </div>
  );
}
