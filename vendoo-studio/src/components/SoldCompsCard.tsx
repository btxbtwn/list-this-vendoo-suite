import React from "react";

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

function marketplaceSlug(name: string): string {
  const slug = name.toLowerCase().replace(/[^a-z]/g, "");
  if (slug === "ebay" || slug === "poshmark" || slug === "mercari" || slug === "depop" || slug === "etsy") {
    return slug;
  }
  return "other";
}

function sourceLabel(source: string): string {
  if (/chatgpt/i.test(source)) return "ChatGPT";
  if (/brave/i.test(source)) return "Brave";
  return source;
}

export function parseSoldComps(text: string): SoldCompsReport | null {
  const blob = (text || "").trim();
  if (!blob.startsWith("Sold comps:")) return null;

  const report: SoldCompsReport = { query: "", source: "", market: "", note: "", comps: [] };
  let pending: SoldComp | null = null;

  const pushPending = () => {
    if (pending) report.comps.push(pending);
    pending = null;
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
    if (stripped === INSTRUCTION) continue;
    if (/^https?:\/\//i.test(stripped)) {
      if (pending) {
        pending.url = stripped;
        pushPending();
      } else if (!report.comps.length) {
        report.note = report.note ? `${report.note}\n${stripped}` : stripped;
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
    if (stripped && !report.comps.length && !pending) {
      report.note = report.note ? `${report.note}\n${stripped}` : stripped;
    }
  }
  pushPending();
  return report;
}

function CompRow({ comp }: { comp: SoldComp }) {
  const inner = (
    <>
      <span className="sold-comps-price">{comp.price}</span>
      <span className={`sold-comps-market sold-comps-market-${marketplaceSlug(comp.marketplace)}`}>
        {comp.marketplace}
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

export function SoldCompsCard({ text }: { text: string }) {
  const report = parseSoldComps(text);
  const meta = [report?.market ? `${report.market} market` : "", sourceLabel(report?.source || "")]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="evidence-card sold-comps-card">
      <div className="evidence-header">SOLD COMPS</div>
      {report?.comps.length ? (
        <div className="sold-comps-body">
          {meta ? <div className="sold-comps-meta">{meta}</div> : null}
          <div className="sold-comps-list">
            {report.comps.map((comp, index) => (
              <CompRow key={`${comp.price}-${comp.title}-${index}`} comp={comp} />
            ))}
          </div>
        </div>
      ) : (
        <div className="sold-comps-body">
          <div className="sold-comps-empty">{report?.note || text.replace(/^Sold comps:\n?/i, "").trim()}</div>
        </div>
      )}
    </div>
  );
}
