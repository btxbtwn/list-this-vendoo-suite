from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from urllib.parse import urlparse

PREFIX = "Sold comps:"
# One sold listing is a single data point, not a market: its price becomes the
# median and drives the whole listing price. Three is the smallest count where
# the median ignores an outlier.
MIN_CONFIDENT_COMPS = 3
# Upper bound on the comps kept and printed. The model and the price-drop median
# both read the printed block, so nothing is collected and then hidden.
MAX_COMPS = 16
# A comp more than this far from the median is a different item (a lot of 10, a
# designer collab, a mislabeled listing), not a signal about this one.
OUTLIER_FACTOR = 2.0
INSTRUCTION = (
    "Use these live results to set market price, then listing price = market × 1.35 (whole dollars)."
)
THIN_INSTRUCTION = (
    "Only {count} sold listing{plural} found — too thin to price from. Treat it as a weak signal, "
    "lean on an estimated baseline, and note pricing uncertainty in the description."
)
EMPTY_NOTE = (
    "No sold listings found. Use an estimated baseline and note pricing uncertainty in the description."
)

_PRICE_RE = re.compile(r"\$\s*(\d{1,4}(?:\.\d{1,2})?)")
_SOLD_FOR_RE = re.compile(
    r"sold(?:\s+(?:for|at))?\s*:?\s*\$\s*(\d{1,4}(?:\.\d{1,2})?)",
    re.I,
)
_PRICE_BEFORE_SOLD_RE = re.compile(
    r"\$\s*(\d{1,4}(?:\.\d{1,2})?)\s*(?:[-–—|·,:]\s*)?(?:sold|completed|ended)\b",
    re.I,
)
_SOLD_EVIDENCE_RE = re.compile(
    r"\b(?:sold(?:\s+(?:for|at|on))?|completed(?:\s+listing)?|item has sold|purchased)\b",
    re.I,
)
_NOT_SOLD_RE = re.compile(r"\b(?:not sold|has(?:n't| not) sold|unsold|sold out)\b", re.I)
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

_THIN_INSTRUCTION_RE = re.compile(
    re.escape(THIN_INSTRUCTION).replace(r"\{count\}", r"\d+").replace(r"\{plural\}", r"s?")
)

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


def trim_outliers(prices: list[float]) -> list[float]:
    """Drop prices more than OUTLIER_FACTOR off the median, keeping at least three."""
    values = [price for price in prices if price > 0]
    if len(values) < MIN_CONFIDENT_COMPS:
        return values
    middle = statistics.median(values)
    if middle <= 0:
        return values
    kept = [
        price
        for price in values
        if middle / OUTLIER_FACTOR <= price <= middle * OUTLIER_FACTOR
    ]
    return kept if len(kept) >= MIN_CONFIDENT_COMPS else values


def comps_instruction(count: int) -> str:
    if count >= MIN_CONFIDENT_COMPS:
        return INSTRUCTION
    return THIN_INSTRUCTION.format(count=count, plural="" if count == 1 else "s")


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


def extract_sold_price(text: str | None) -> float | None:
    """Return a price only when the result explicitly says it sold.

    Search snippets often contain both an original/list price and a current
    price. Without an explicit sold-price association, multiple amounts are
    ambiguous and are safer to discard than to price a listing from.
    """
    blob = text or ""
    if _NOT_SOLD_RE.search(blob) or not _SOLD_EVIDENCE_RE.search(blob):
        return None
    sold = _SOLD_FOR_RE.search(blob) or _PRICE_BEFORE_SOLD_RE.search(blob)
    if sold:
        return extract_price(f"${sold.group(1)}")
    prices = {float(match.group(1)) for match in _PRICE_RE.finditer(blob)}
    if len(prices) != 1:
        return None
    return prices.pop()


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
    url_marketplace = marketplace_from_url(url)
    marketplace = url_marketplace or normalize_marketplace(marketplace)
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
        if len(unique) == MAX_COMPS:
            break
    return unique


def _normalized_identity(text: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _matches_brand(text: str, expected_brand: str) -> bool:
    expected = _normalized_identity(expected_brand)
    if not expected or expected in {"unbranded", "unknown", "other"}:
        return True
    candidate = _normalized_identity(text)
    if expected in candidate:
        return True
    # Apostrophes and punctuation are inconsistently preserved in marketplace
    # titles ("Levi's" vs "Levis"). Compare compact forms for real brand
    # names, but not very short names where substring matches are noisy.
    compact_expected = expected.replace(" ", "")
    return len(compact_expected) > 3 and compact_expected in candidate.replace(" ", "")


def comps_from_web_results(
    results: list[dict] | None,
    *,
    expected_brand: str = "",
) -> list[SoldComp]:
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
        if not _matches_brand(blob, expected_brand):
            continue
        comps.append(
            _comp(
                extract_sold_price(blob),
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
    # Model-written prices without a directly inspectable marketplace listing
    # URL are not evidence and must never become pricing inputs.
    if not is_listing_url(url):
        return None
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
        # Markdown is model-written too; without an observed listing URL this
        # would turn an unsupported price sentence into a pricing input.
        if price is None or not urls:
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


def comps_from_chatgpt(
    answer: str | None,
    sources: list[dict] | None = None,
    *,
    expected_brand: str = "",
) -> tuple[str, list[SoldComp]]:
    comps: list[SoldComp] = []
    market = ""
    payload = _extract_json(answer)
    if payload:
        market = str(payload.get("market") or payload.get("market_range") or "").strip()
        raw_comps = payload.get("comps")
        if isinstance(raw_comps, list):
            comps.extend(
                comp
                for item in raw_comps
                if (comp := _comp_from_dict(item))
                and _matches_brand(comp.title, expected_brand)
            )
    if not any(comps):
        comps = list(comps_from_markdown(answer))
    else:
        comps = [comp for comp in comps if comp]
    for source in sources or []:
        if isinstance(source, dict):
            comps.extend(comps_from_web_results([source], expected_brand=expected_brand))
    comps = _dedupe(comps)
    return market_range(market or (answer or ""), comps), comps


def format_sold_comps(report: SoldCompsReport) -> str:
    lines = [PREFIX, f"Query: {report.query}", f"Source: {report.source}"]
    market = report.market or (market_range(comps=report.comps) if report.comps else "")
    if market:
        lines.append(f"Market: {market}")
    if report.comps:
        lines.append("")
        for comp in report.comps[:MAX_COMPS]:
            parts = [format_price(comp.price), comp.marketplace]
            if comp.condition:
                parts.append(comp.condition)
            parts.append(comp.title)
            lines.append("- " + " · ".join(parts))
            if comp.url:
                lines.append(f"  {comp.url}")
        lines.append("")
        lines.append(comps_instruction(len(report.comps)))
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
        if stripped == INSTRUCTION or _THIN_INSTRUCTION_RE.match(stripped):
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


def comps_count(text: str | None) -> int:
    report = parse_sold_comps(text)
    return len(report.comps) if report else 0


def comps_usable(text: str | None) -> bool:
    """Any parsed sold listing — worth showing, not necessarily worth pricing from."""
    return comps_count(text) > 0


def comps_confident(text: str | None) -> bool:
    """Enough sold listings to set a price from, and to stop searching for more."""
    return comps_count(text) >= MIN_CONFIDENT_COMPS
