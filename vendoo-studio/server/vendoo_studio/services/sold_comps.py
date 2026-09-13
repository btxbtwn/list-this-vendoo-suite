from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

PREFIX = "Sold comps:"
INSTRUCTION = (
    "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
)
EMPTY_NOTE = (
    "No sold listings found. Use an estimated baseline and note pricing uncertainty in the description."
)

_PRICE_RE = re.compile(r"\$\s*(\d{1,4}(?:\.\d{1,2})?)")
_SOLD_FOR_RE = re.compile(
    r"sold(?:\s+(?:for|at))?\s*:?\s*\$\s*(\d{1,4}(?:\.\d{1,2})?)",
    re.I,
)
_RANGE_RE = re.compile(
    r"\$\s*(\d{1,4}(?:\.\d{1,2})?)\s*(?:[-–—]|to)\s*\$?\s*(\d{1,4}(?:\.\d{1,2})?)",
    re.I,
)
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
_ITEM_LINE_RE = re.compile(r"^(?:\d+[\.)]\s+|[-*]\s+)")
_CONDITION_RE = re.compile(
    r"\b(New with tags|New without tags|Like New|Pre-Owned|Pre-owned|Excellent|Very Good|Good|Fair|Worn|NWT|NWOT)\b",
    re.I,
)
_HOWTO_RE = re.compile(
    r"how to|what (?:are|is) (?:sold )?comps|"
    r"sold comps? (?:guide|tool|research)|"
    r"terapeak|pricing (?:guide|strategy|tool)|price research|worth checker|"
    r"sold listings? (?:search|tool|guide)",
    re.I,
)

_MARKET_ALIASES = {
    "ebay": "eBay",
    "e bay": "eBay",
    "poshmark": "Poshmark",
    "posh": "Poshmark",
    "mercari": "Mercari",
    "depop": "Depop",
    "etsy": "Etsy",
}
_MARKET_RE = re.compile(r"\b(eBay|Poshmark|Mercari|Depop|Etsy)\b", re.I)

_LISTING_HOSTS = (
    ("ebay.", "/itm/", "eBay"),
    ("poshmark.com", "/listing/", "Poshmark"),
    ("mercari.com", "/item/", "Mercari"),
    ("depop.com", "/products/", "Depop"),
    ("etsy.com", "/listing/", "Etsy"),
)


@dataclass(frozen=True)
class SoldComp:
    price: float
    marketplace: str
    title: str
    url: str = ""
    condition: str = ""


@dataclass
class SoldCompsReport:
    query: str
    source: str
    comps: list[SoldComp] = field(default_factory=list)
    market: str = ""
    note: str = ""


def format_price(value: float) -> str:
    if value == int(value):
        return f"${int(value)}"
    return f"${value:.2f}"


def extract_price(text: str | None) -> float | None:
    blob = text or ""
    sold = _SOLD_FOR_RE.search(blob)
    raw = sold.group(1) if sold else None
    if raw is None:
        match = _PRICE_RE.search(blob)
        raw = match.group(1) if match else None
    if raw is None:
        return None
    try:
        price = float(raw)
    except ValueError:
        return None
    if price < 1 or price > 9999:
        return None
    return price


def market_range(text: str | None = None, comps: list[SoldComp] | None = None) -> str:
    blob = text or ""
    match = _RANGE_RE.search(blob)
    if match:
        lo, hi = float(match.group(1)), float(match.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return f"{format_price(lo)}–{format_price(hi)}"
    prices = [comp.price for comp in (comps or [])]
    if not prices:
        return ""
    lo, hi = min(prices), max(prices)
    if lo == hi:
        return format_price(lo)
    return f"{format_price(lo)}–{format_price(hi)}"


def normalize_marketplace(value: str | None) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    return _MARKET_ALIASES.get(text.lower(), text)


def marketplace_from_url(url: str | None) -> str:
    parsed = urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    for host_part, prefix, market in _LISTING_HOSTS:
        if host_part in host and prefix in path.lower():
            return market
    return ""


def marketplace_from_text(text: str | None) -> str:
    match = _MARKET_RE.search(text or "")
    return normalize_marketplace(match.group(1) if match else "")


def is_listing_url(url: str | None) -> bool:
    return bool(marketplace_from_url(url))


def looks_like_howto(title: str | None = None, url: str | None = None) -> bool:
    blob = " ".join(part for part in (title, url) if part)
    return bool(_HOWTO_RE.search(blob))


def extract_condition(text: str | None) -> str:
    match = _CONDITION_RE.search(text or "")
    if not match:
        return ""
    value = match.group(1)
    if value.lower() == "pre-owned":
        return "Pre-owned"
    return value


def _clean_title(text: str) -> str:
    title = _ITEM_LINE_RE.sub("", text or "")
    title = _URL_RE.sub("", title)
    title = title.replace("**", "")
    title = _PRICE_RE.sub("", title)
    title = _MARKET_RE.sub("", title)
    title = _CONDITION_RE.sub("", title)
    title = title.strip(" -–—|:·•\t")
    title = " ".join(title.split())
    for token in ("Sold comps:", "Sources:"):
        if title.startswith(token):
            return ""
    return title[:160]


def _comp(
    price: float | None,
    marketplace: str,
    title: str,
    url: str = "",
    condition: str = "",
) -> SoldComp | None:
    if price is None:
        return None
    title = _clean_title(title)
    marketplace = normalize_marketplace(marketplace) or marketplace_from_url(url)
    if url and not is_listing_url(url):
        if looks_like_howto(title, url):
            return None
        url = ""
    if looks_like_howto(title, url):
        return None
    if not title or title.lower() in {"sold", "comp", "listing"}:
        return None
    if not marketplace:
        return None
    return SoldComp(
        price=price,
        marketplace=marketplace,
        title=title,
        url=url,
        condition=condition,
    )


def _dedupe(comps: list[SoldComp]) -> list[SoldComp]:
    seen: set[str] = set()
    unique: list[SoldComp] = []
    for comp in comps:
        key = comp.url.lower() if comp.url else f"{comp.marketplace}|{comp.price}|{comp.title.lower()}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(comp)
        if len(unique) == 8:
            break
    return unique


def comps_from_web_results(results: list[dict] | None) -> list[SoldComp]:
    comps: list[SoldComp] = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not is_listing_url(url):
            continue
        title = " ".join(str(item.get("title") or "").split())
        snippets = [str(item.get("description") or "")]
        extras = item.get("extra_snippets")
        if isinstance(extras, list):
            snippets.extend(str(snippet) for snippet in extras)
        blob = " ".join([title, *snippets])
        comps.append(
            _comp(
                extract_price(blob),
                marketplace_from_url(url) or marketplace_from_text(blob),
                title,
                url,
                extract_condition(blob),
            )
        )
    return _dedupe([comp for comp in comps if comp])


def _extract_json(text: str | None) -> dict | None:
    blob = text or ""
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", blob, re.I)
    candidates: list[str] = []
    if fenced:
        candidates.append(fenced.group(1).strip())
    stripped = blob.strip()
    if stripped:
        candidates.append(stripped)
    match = re.search(r"\{[\s\S]*\}", blob)
    if match:
        candidates.append(match.group().strip())
    for raw in candidates:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("comps" in parsed or "market" in parsed or "market_range" in parsed):
            return parsed
    return None


def _comp_from_dict(raw: object) -> SoldComp | None:
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or "").strip()
    title = str(raw.get("title") or raw.get("item") or "")
    marketplace = str(raw.get("marketplace") or raw.get("market") or "")
    condition = str(raw.get("condition") or "")
    price = raw.get("price")
    if isinstance(price, (int, float)):
        amount = float(price) if price >= 1 else None
    else:
        amount = extract_price(str(price or "")) or extract_price(title)
    return _comp(amount, marketplace, title, url, condition)


def comps_from_markdown(text: str | None) -> list[SoldComp]:
    comps: list[SoldComp] = []
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        nxt = lines[index + 1].strip() if index + 1 < len(lines) else ""
        urls = [url for url in _URL_RE.findall(f"{stripped} {nxt}") if is_listing_url(url)]
        if not urls and not _ITEM_LINE_RE.match(stripped):
            continue
        window = f"{stripped} {nxt}"
        price = extract_price(stripped) or extract_price(nxt)
        if price is None:
            continue
        url = urls[0] if urls else ""
        title = _clean_title(stripped) or _clean_title(nxt)
        comps.append(
            _comp(
                price,
                marketplace_from_text(window) or marketplace_from_url(url),
                title,
                url,
                extract_condition(window),
            )
        )
    return _dedupe([comp for comp in comps if comp])


def research_note(answer: str | None) -> str:
    blob = (answer or "").strip()
    if not blob:
        return ""
    remainder = re.sub(r"```(?:json)?\s*[\s\S]*?```", "", blob, flags=re.I).strip()
    payload = _extract_json(blob)
    if payload is not None and not remainder:
        return ""
    if payload is not None:
        try:
            if json.loads(blob) == payload:
                return ""
        except json.JSONDecodeError:
            pass
        return remainder
    return remainder or blob


def comps_from_chatgpt(answer: str | None, sources: list[dict] | None = None) -> tuple[str, list[SoldComp]]:
    comps: list[SoldComp] = []
    market = ""
    payload = _extract_json(answer)
    if payload:
        market = str(payload.get("market") or payload.get("market_range") or "").strip()
        raw_comps = payload.get("comps")
        if isinstance(raw_comps, list):
            comps.extend(_comp_from_dict(item) for item in raw_comps)
    if not any(comps):
        comps = list(comps_from_markdown(answer))
    else:
        comps = [comp for comp in comps if comp]
    for source in sources or []:
        if isinstance(source, dict):
            comps.extend(comps_from_web_results([source]))
    comps = _dedupe(comps)
    return market_range(market or (answer or ""), comps), comps


def format_sold_comps(report: SoldCompsReport) -> str:
    lines = [PREFIX, f"Query: {report.query}", f"Source: {report.source}"]
    market = report.market or (market_range(comps=report.comps) if report.comps else "")
    if market:
        lines.append(f"Market: {market}")
    if report.comps:
        lines.append("")
        for comp in report.comps[:8]:
            parts = [format_price(comp.price), comp.marketplace]
            if comp.condition:
                parts.append(comp.condition)
            parts.append(comp.title)
            lines.append("- " + " · ".join(parts))
            if comp.url:
                lines.append(f"  {comp.url}")
        lines.append("")
        lines.append(INSTRUCTION)
        return "\n".join(lines)
    lines.append(report.note or EMPTY_NOTE)
    return "\n".join(lines)


def parse_sold_comps(text: str | None) -> SoldCompsReport | None:
    blob = (text or "").strip()
    if not blob.startswith(PREFIX):
        return None
    query = ""
    source = ""
    market = ""
    note_lines: list[str] = []
    comps: list[SoldComp] = []
    pending: SoldComp | None = None
    for raw in blob.splitlines()[1:]:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("Query:"):
            query = stripped[6:].strip()
            continue
        if stripped.startswith("Source:"):
            source = stripped[7:].strip()
            continue
        if stripped.startswith("Market:"):
            market = stripped[7:].strip()
            continue
        if stripped == INSTRUCTION:
            continue
        if stripped.startswith("http://") or stripped.startswith("https://"):
            if pending and is_listing_url(stripped):
                pending = SoldComp(
                    price=pending.price,
                    marketplace=pending.marketplace,
                    title=pending.title,
                    url=stripped,
                    condition=pending.condition,
                )
                comps.append(pending)
                pending = None
            elif not comps and not pending:
                note_lines.append(stripped)
            continue
        if stripped.startswith("- $") or stripped.startswith("-$"):
            if pending:
                comps.append(pending)
                pending = None
            body = stripped.lstrip("- ").strip()
            parts = [part.strip() for part in body.split(" · ") if part.strip()]
            if len(parts) < 3:
                continue
            price = extract_price(parts[0])
            marketplace = parts[1]
            if len(parts) == 3:
                condition, title = "", parts[2]
            else:
                condition, title = parts[2], " · ".join(parts[3:])
            pending = _comp(price, marketplace, title, condition=condition)
            continue
        if not comps and not pending:
            if stripped or note_lines:
                note_lines.append(line)
    if pending:
        comps.append(pending)
    note = "\n".join(note_lines).strip()
    if not market:
        market = market_range(note)
    return SoldCompsReport(
        query=query,
        source=source,
        comps=_dedupe([comp for comp in comps if comp]),
        market=market,
        note=note,
    )


def comps_usable(text: str | None) -> bool:
    report = parse_sold_comps(text)
    return bool(report and report.comps)
