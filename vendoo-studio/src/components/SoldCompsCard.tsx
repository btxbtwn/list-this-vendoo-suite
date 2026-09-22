import { ChatMarkdown } from "./ChatMarkdown";
import { MarketplaceLogo, hasMarketplaceLogo } from "./MarketplaceLogo";

export interface SoldComp {
  price: string;
  marketplace: string;
  title: string;
  url?: string;
  condition?: string;
}

export interface SoldCompsReport {
  query: string;
  source: string;
  market: string;
  note: string;
  comps: SoldComp[];
}

const INSTRUCTION =
  "Use these live results to set market price, then listing price = market × 1.35 (whole dollars).";
const THIN_INSTRUCTION_RE = /^Only \d+ sold listings? found — too thin to price from\./;
// Matches MIN_CONFIDENT_COMPS in server/vendoo_studio/services/sold_comps.py.
const MIN_CONFIDENT_COMPS = 3;

const RANGE_RE =
  /\$\s*(\d{1,4}(?:\.\d{1,2})?)\s*(?:[-–—]|to)\s*\$?\s*(\d{1,4}(?:\.\d{1,2})?)/i;

// The comps come back with display names ("eBay", "Poshmark"); the logo set is
// keyed by Vendoo's ids, and anything it does not carry gets the general mark.
function marketplaceSlug(name: string): string {
  const slug = name.toLowerCase().replace(/[^a-z]/g, "");
  return hasMarketplaceLogo(slug) ? slug : "general";
}

function sourceLabel(source: string): string {
  if (/chatgpt/i.test(source)) return "ChatGPT";
  if (/brave/i.test(source)) return "Brave";
  return source;
}

function formatMoney(value: string): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return `$${value}`;
  return Number.isInteger(amount) ? `$${amount}` : `$${amount.toFixed(2)}`;
}

function marketFromText(text: string): string {
  const match = text.match(RANGE_RE);
  if (!match) return "";
  const lo = Number(match[1]);
  const hi = Number(match[2]);
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return "";
  return `${formatMoney(String(Math.min(lo, hi)))}–${formatMoney(String(Math.max(lo, hi)))}`;
}

function unwrapMarkdownFence(text: string): string {
  const match = text.trim().match(/^```(?:markdown|md)?\s*([\s\S]*?)\s*```$/i);
  return match ? match[1].trim() : text;
}

function isMetaLine(stripped: string): boolean {
  return (
    stripped === "Sold comps:" ||
    stripped === INSTRUCTION ||
    THIN_INSTRUCTION_RE.test(stripped) ||
    stripped.startsWith("Query:") ||
    stripped.startsWith("Source:") ||
    stripped.startsWith("Market:")
  );
}

export function parseSoldComps(text: string): SoldCompsReport | null {
  const blob = (text || "").trim();
  if (!blob.startsWith("Sold comps:")) return null;

  const report: SoldCompsReport = { query: "", source: "", market: "", note: "", comps: [] };
  let pending: SoldComp | null = null;
  const noteLines: string[] = [];

  const pushPending = () => {
    if (pending) report.comps.push(pending);
    pending = null;
  };

  const pushNote = (line: string) => {
    if (!line.trim() && !noteLines.length) return;
    noteLines.push(line.replace(/\s+$/, ""));
  };

  for (const raw of blob.split("\n").slice(1)) {
    const stripped = raw.trim();
    if (stripped.startsWith("Query:")) {
      report.query = stripped.slice(6).trim();
      continue;
    }
    if (stripped.startsWith("Source:")) {
      report.source = stripped.slice(7).trim();
      continue;
    }
    if (stripped.startsWith("Market:")) {
      report.market = stripped.slice(7).trim();
      continue;
    }
    if (isMetaLine(stripped)) continue;
    if (/^https?:\/\//i.test(stripped)) {
      if (pending) {
        pending.url = stripped;
        pushPending();
      } else if (!report.comps.length) {
        pushNote(stripped);
      }
      continue;
    }
    if (stripped.startsWith("- $") || stripped.startsWith("-$")) {
      pushPending();
      const parts = stripped.replace(/^-+\s*/, "").split(" · ").map((part) => part.trim()).filter(Boolean);
      if (parts.length < 3) continue;
      pending = {
        price: parts[0],
        marketplace: parts[1],
        condition: parts.length > 3 ? parts[2] : "",
        title: parts.length > 3 ? parts.slice(3).join(" · ") : parts[2],
      };
      continue;
    }
    if (!report.comps.length && !pending) {
      pushNote(raw);
    }
  }
  pushPending();
  report.note = unwrapMarkdownFence(noteLines.join("\n").trim());
  if (!report.market) report.market = marketFromText(report.note);
  return report;
}

/* lucide `tag`. Same 14px muted glyph the Evidence card heads with; T3 Code
   pairs an icon with a sentence-case title on its timeline cards. */
function TagIcon() {
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
      <path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z" />
      <circle cx="7.5" cy="7.5" r=".5" fill="currentColor" />
    </svg>
  );
}

function CompRow({ comp }: { comp: SoldComp }) {
  const inner = (
    <>
      <span className="sold-comps-price">{comp.price}</span>
      <span className="sold-comps-market">
        <MarketplaceLogo id={marketplaceSlug(comp.marketplace)} label={comp.marketplace} size={14} />
        <span className="sold-comps-market-name">{comp.marketplace}</span>
      </span>
      <span className="sold-comps-copy">
        <span className="sold-comps-title">{comp.title}</span>
        {comp.condition ? <span className="sold-comps-condition">{comp.condition}</span> : null}
      </span>
    </>
  );
  if (comp.url) {
    return (
      <a className="sold-comps-row" href={comp.url} target="_blank" rel="noopener noreferrer">
        {inner}
      </a>
    );
  }
  return <div className="sold-comps-row sold-comps-row-static">{inner}</div>;
}

function fallbackNote(text: string): string {
  const lines = text.replace(/^Sold comps:\s*/i, "").split("\n");
  return unwrapMarkdownFence(
    lines
      .filter((line) => !isMetaLine(line.trim()))
      .join("\n")
      .trim(),
  );
}

export function SoldCompsCard({ text }: { text: string }) {
  const report = parseSoldComps(text);
  const note = report ? report.note : fallbackNote(text);
  const count = report?.comps.length ?? 0;
  const thin = count > 0 && count < MIN_CONFIDENT_COMPS;
  const market = report?.market || "";
  const source = sourceLabel(report?.source || "");

  return (
    <div className="evidence-card sold-comps-card">
      <div className="evidence-header">
        <TagIcon />
        <span className="evidence-title">Sold comps</span>
        {market ? <span className="sold-comps-range">{market} market</span> : null}
        {source ? <span className="sold-comps-source">{source}</span> : null}
      </div>
      <div className="sold-comps-body">
        {thin ? (
          <div className="sold-comps-meta">only {count} sold — too thin to price from</div>
        ) : null}
        {report?.comps.length ? (
          <div className="sold-comps-list">
            {report.comps.map((comp, index) => (
              <CompRow key={`${comp.price}-${comp.title}-${index}`} comp={comp} />
            ))}
          </div>
        ) : null}
        {note ? (
          <div className="sold-comps-empty">
            <ChatMarkdown text={note} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
