"""Semantic search over local Vendoo catalog, skill rules, and fill helpers via Semble."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from vendoo_studio.config import extension_source_dir, skills_dir, user_data_root
from vendoo_studio.models.catalog import CategorySchema, CategoryTree, CategoryTreeNode
from vendoo_studio.services.category_tree import MARKETPLACES

log = logging.getLogger("vendoo_studio.catalog_index")

SEARCH_KINDS = frozenset({"category", "schema", "option", "skill", "fill", "all"})

_INDEX_LOCK = threading.RLock()
_INDEX = None
_INDEX_FINGERPRINT: str | None = None
_STALE = False

_META_RE = re.compile(
    r"^kind:\s*(?P<kind>\S+)\s*$"
    r"|^marketplace:\s*(?P<marketplace>\S+)\s*$"
    r"|^id:\s*(?P<id>.+?)\s*$"
    r"|^path:\s*(?P<path>.+?)\s*$"
    r"|^general_path:\s*(?P<general_path>.+?)\s*$"
    r"|^field:\s*(?P<field>.+?)\s*$"
    r"|^symbol:\s*(?P<symbol>.+?)\s*$"
    r"|^line:\s*(?P<line>\d+)\s*$"
    r"|^title:\s*(?P<title>.+?)\s*$",
    re.M,
)
_HEADING_RE = re.compile(r"(?m)^#{1,3}\s+.+$")
_FILL_FN_RE = re.compile(
    r"(?m)^(?:async\s+)?function\s+(fill\w*|select\w*|set\w*Field\w*|choose\w*)\s*\("
    r"|^(?:const|let|var)\s+(fill\w*|select\w*|set\w*Field\w*)\s*=\s*(?:async\s*)?(?:function|\()"
)
_FORM_MARKETPLACE = {
    "vendoo": "general",
    "general": "general",
    "ebay": "ebay",
    "poshmark": "poshmark",
    "mercari": "mercari",
    "depop": "depop",
    "etsy": "etsy",
}


def catalog_docs_dir() -> Path:
    return user_data_root() / "catalog-index" / "docs"


def catalog_meta_path() -> Path:
    return user_data_root() / "catalog-index" / "fingerprint.json"


def mark_catalog_index_stale() -> None:
    global _STALE
    with _INDEX_LOCK:
        _STALE = True


def reset_catalog_index_cache() -> None:
    """Drop the in-memory index (tests and forced rebuilds)."""
    global _INDEX, _INDEX_FINGERPRINT, _STALE
    with _INDEX_LOCK:
        _INDEX = None
        _INDEX_FINGERPRINT = None
        _STALE = True


def _safe_stem(value: str) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:20]


def _file_stamp(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _leaf_query(db: Session):
    return db.query(CategoryTreeNode).filter(
        CategoryTreeNode.is_leaf.is_(True),
        CategoryTreeNode.has_children.is_(False),
    )


def _dropdown_path() -> Path:
    return skills_dir() / "list-this" / "references" / "vendoo-dropdown-options.json"


def _skill_files() -> list[Path]:
    root = skills_dir() / "list-this"
    files = [root / "SKILL.md"]
    refs = root / "references"
    if refs.is_dir():
        files.extend(sorted(p for p in refs.glob("*.md") if p.is_file()))
    return [p for p in files if p.is_file()]


def _extension_script_files() -> list[Path]:
    root = extension_source_dir()
    paths = []
    for rel in (
        "content-scripts/vendoo.js",
        "content-scripts/ebay.js",
        "content-scripts/poshmark.js",
        "content-scripts/mercari.js",
        "content-scripts/depop.js",
        "content-scripts/etsy.js",
        "background.js",
    ):
        path = root / rel
        if path.is_file():
            paths.append(path)
    return paths


def fingerprint(db: Session) -> dict[str, Any]:
    trees = {}
    for marketplace in MARKETPLACES:
        tree = db.get(CategoryTree, marketplace)
        leaves = _leaf_query(db).filter_by(marketplace=marketplace).count()
        trees[marketplace] = {
            "status": tree.status if tree else "missing",
            "updated_at": tree.updated_at.isoformat() if tree and tree.updated_at else None,
            "leaves": leaves,
        }
    return {
        "trees": trees,
        "schemas": db.query(CategorySchema).count(),
        "dropdown": _file_stamp(_dropdown_path()),
        "skills": {str(path): _file_stamp(path) for path in _skill_files()},
        "extension": {str(path): _file_stamp(path) for path in _extension_script_files()},
    }


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _write_category_doc(root: Path, marketplace: str, category_id: str, path: str, label: str) -> None:
    _write_text(
        root / "categories" / marketplace / f"{_safe_stem(category_id)}.md",
        "\n".join([
            "kind: category",
            f"marketplace: {marketplace}",
            f"id: {category_id}",
            f"path: {path}",
            f"label: {label}",
            "",
            path,
        ]),
    )


def _write_schema_doc(root: Path, row: CategorySchema) -> None:
    fields = row.fields if isinstance(row.fields, list) else []
    labels = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        label = str(field.get("label") or field.get("key") or "").strip()
        if label:
            labels.append(label)
    _write_text(
        root / "schemas" / row.marketplace / f"{_safe_stem(row.id or row.general_path)}.md",
        "\n".join([
            "kind: schema",
            f"marketplace: {row.marketplace}",
            f"id: {row.id}",
            f"general_path: {row.general_path}",
            f"path: {row.category_path}",
            "",
            row.general_path,
            row.category_path,
            "fields: " + ", ".join(labels),
        ]),
    )


def _option_labels(raw: Any) -> list[str]:
    labels: list[str] = []
    if not isinstance(raw, list):
        return labels
    for option in raw:
        if isinstance(option, dict):
            label = str(option.get("label") or option.get("value") or "").strip()
        else:
            label = str(option).strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _write_option_doc(root: Path, marketplace: str, field: str, options: list[str], source: str) -> None:
    if not options:
        return
    option_id = f"{marketplace}:{field}:{source}"
    listed = "; ".join(options[:80])
    if len(options) > 80:
        listed += "; …"
    _write_text(
        root / "options" / marketplace / f"{_safe_stem(option_id)}.md",
        "\n".join([
            "kind: option",
            f"marketplace: {marketplace}",
            f"field: {field}",
            f"id: {option_id}",
            f"source: {source}",
            f"options_json: {json.dumps(options, ensure_ascii=False)}",
            "",
            f"{marketplace} {field} dropdown options",
            listed,
        ]),
    )


def _materialize_dropdown_options(root: Path) -> int:
    path = _dropdown_path()
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        log.exception("failed to read dropdown options at %s", path)
        return 0
    count = 0
    forms = payload.get("forms") if isinstance(payload, dict) else {}
    if not isinstance(forms, dict):
        return 0
    for form_name, fields in forms.items():
        marketplace = _FORM_MARKETPLACE.get(str(form_name).casefold(), str(form_name))
        if not isinstance(fields, dict):
            continue
        for field, options in fields.items():
            labels = _option_labels(options)
            if not labels:
                continue
            _write_option_doc(root, marketplace, str(field), labels, "dropdown_json")
            count += 1
    return count


def _chunk_markdown(text: str) -> list[tuple[str, str]]:
    text = str(text or "").strip()
    if not text:
        return []
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("Overview", text)]
    chunks: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preface = text[: matches[0].start()].strip()
        if preface:
            chunks.append(("Overview", preface))
    for index, match in enumerate(matches):
        title = match.group(0).lstrip("#").strip() or f"Section {index + 1}"
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.start():end].strip()
        if body:
            chunks.append((title, body))
    return chunks


def _materialize_skills(root: Path) -> int:
    count = 0
    for path in _skill_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(skills_dir())) if path.is_relative_to(skills_dir()) else path.name
        for title, body in _chunk_markdown(text):
            chunk_id = f"{rel}:{title}"
            _write_text(
                root / "skills" / f"{_safe_stem(chunk_id)}.md",
                "\n".join([
                    "kind: skill",
                    f"id: {chunk_id}",
                    f"path: {rel}",
                    f"title: {title}",
                    "",
                    body[:6000],
                ]),
            )
            count += 1
    return count


def _marketplace_from_script(path: Path) -> str:
    name = path.stem.casefold()
    if name in MARKETPLACES or name == "vendoo":
        return "general" if name == "vendoo" else name
    return "extension"


def _materialize_fill_helpers(root: Path) -> int:
    count = 0
    for path in _extension_script_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = path.name
        try:
            rel = str(path.relative_to(extension_source_dir()))
        except ValueError:
            pass
        marketplace = _marketplace_from_script(path)
        for match in _FILL_FN_RE.finditer(text):
            symbol = next((group for group in match.groups() if group), "")
            if not symbol:
                continue
            line = text.count("\n", 0, match.start()) + 1
            snippet = text[match.start(): match.start() + 500].strip()
            helper_id = f"{rel}:{symbol}:{line}"
            _write_text(
                root / "fill" / marketplace / f"{_safe_stem(helper_id)}.md",
                "\n".join([
                    "kind: fill",
                    f"marketplace: {marketplace}",
                    f"id: {helper_id}",
                    f"path: {rel}",
                    f"symbol: {symbol}",
                    f"line: {line}",
                    f"field: {symbol}",
                    "",
                    f"Fill helper {symbol} in {rel}",
                    snippet,
                ]),
            )
            count += 1
    return count


def materialize_catalog_docs(db: Session, root: Path | None = None) -> Path:
    docs = root or catalog_docs_dir()
    if docs.exists():
        shutil.rmtree(docs)
    docs.mkdir(parents=True, exist_ok=True)
    for node in _leaf_query(db).order_by(CategoryTreeNode.marketplace, CategoryTreeNode.path):
        _write_category_doc(docs, node.marketplace, node.category_id, node.path, node.label)
    for row in db.query(CategorySchema).order_by(CategorySchema.marketplace, CategorySchema.general_path):
        _write_schema_doc(docs, row)
        for field in (row.fields if isinstance(row.fields, list) else []):
            if not isinstance(field, dict):
                continue
            label = str(field.get("label") or field.get("key") or "").strip()
            options = _option_labels(field.get("options"))
            if label and options:
                _write_option_doc(docs, row.marketplace, label, options, f"schema:{row.general_path}")
    _materialize_dropdown_options(docs)
    _materialize_skills(docs)
    _materialize_fill_helpers(docs)
    return docs


def _load_semble_index(docs: Path):
    from semble import ContentType, SembleIndex

    return SembleIndex.from_path(str(docs), content=ContentType.DOCS)


def rebuild_catalog_index(db: Session) -> dict[str, Any]:
    """Export catalog/skill/fill docs and rebuild the Semble index."""
    global _INDEX, _INDEX_FINGERPRINT, _STALE
    fp = fingerprint(db)
    docs = materialize_catalog_docs(db)
    with _INDEX_LOCK:
        if any(path.suffix == ".md" for path in docs.rglob("*.md")):
            _INDEX = _load_semble_index(docs)
        else:
            _INDEX = None
        _INDEX_FINGERPRINT = json.dumps(fp, sort_keys=True)
        _STALE = False
        catalog_meta_path().parent.mkdir(parents=True, exist_ok=True)
        catalog_meta_path().write_text(_INDEX_FINGERPRINT, encoding="utf-8")
    counts = {
        name: sum(1 for _ in (docs / name).rglob("*.md")) if (docs / name).exists() else 0
        for name in ("categories", "schemas", "options", "skills", "fill")
    }
    log.info("catalog index rebuilt: %s", counts)
    return {"ok": True, "fingerprint": fp, "docs": str(docs), "counts": counts}


def ensure_catalog_index(db: Session) -> dict[str, Any]:
    """Rebuild only when fingerprint is stale or the in-memory index is missing."""
    global _INDEX, _INDEX_FINGERPRINT, _STALE
    fp = json.dumps(fingerprint(db), sort_keys=True)
    meta = catalog_meta_path()
    with _INDEX_LOCK:
        cached = meta.read_text(encoding="utf-8") if meta.is_file() else None
        needs = _STALE or _INDEX is None or _INDEX_FINGERPRINT != fp or cached != fp
    if not needs:
        return {"ok": True, "rebuilt": False, "fingerprint": json.loads(fp)}
    result = rebuild_catalog_index(db)
    result["rebuilt"] = True
    return result


def _parse_doc(content: str) -> dict[str, str]:
    parsed = {
        "kind": "", "marketplace": "", "id": "", "path": "", "general_path": "",
        "field": "", "symbol": "", "line": "", "title": "",
    }
    for match in _META_RE.finditer(content or ""):
        for key, value in match.groupdict().items():
            if value is not None:
                parsed[key] = value.strip()
    options_match = re.search(r"^options_json:\s*(.+)\s*$", content or "", re.M)
    if options_match:
        parsed["options_json"] = options_match.group(1).strip()
    return parsed


def _body_after_meta(content: str) -> str:
    lines = str(content or "").splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            return "\n".join(lines[index + 1:]).strip()
    return str(content or "").strip()


def _verify_category(db: Session, marketplace: str, category_id: str, path_prefix: str = "") -> dict | None:
    node = db.get(CategoryTreeNode, (marketplace, category_id))
    if node is None or not node.is_leaf or node.has_children:
        return None
    if path_prefix and not node.path.startswith(path_prefix.rstrip() + " >") and node.path != path_prefix:
        return None
    return {
        "kind": "category",
        "marketplace": node.marketplace,
        "id": node.category_id,
        "path": node.path,
        "label": node.label,
    }


def _verify_schema(db: Session, schema_id: str, general_path: str = "") -> dict | None:
    row = None
    if schema_id:
        row = db.get(CategorySchema, schema_id)
    if row is None and general_path:
        row = db.query(CategorySchema).filter_by(general_path=general_path).first()
    if row is None:
        return None
    return {
        "kind": "schema",
        "marketplace": row.marketplace,
        "id": row.id,
        "path": row.category_path,
        "general_path": row.general_path,
        "fields": row.fields if isinstance(row.fields, list) else [],
    }


def _verify_option(meta: dict[str, str], content: str) -> dict | None:
    field = meta.get("field") or ""
    marketplace = meta.get("marketplace") or ""
    if not field or not marketplace:
        return None
    options: list[str] = []
    raw = meta.get("options_json") or ""
    if raw:
        try:
            parsed = json.loads(raw)
            options = _option_labels(parsed)
        except (ValueError, TypeError):
            options = []
    if not options:
        return None
    return {
        "kind": "option",
        "marketplace": marketplace,
        "id": meta.get("id") or f"{marketplace}:{field}",
        "field": field,
        "options": options,
        "path": field,
        "snippet": _body_after_meta(content)[:500],
    }


def _verify_skill(meta: dict[str, str], content: str) -> dict | None:
    path = meta.get("path") or ""
    if not path:
        return None
    return {
        "kind": "skill",
        "id": meta.get("id") or path,
        "path": path,
        "title": meta.get("title") or "",
        "marketplace": "",
        "snippet": _body_after_meta(content)[:4000],
    }


def _verify_fill(meta: dict[str, str], content: str) -> dict | None:
    path = meta.get("path") or ""
    symbol = meta.get("symbol") or ""
    if not path or not symbol:
        return None
    line = int(meta["line"]) if str(meta.get("line") or "").isdigit() else 0
    return {
        "kind": "fill",
        "id": meta.get("id") or f"{path}:{symbol}",
        "marketplace": meta.get("marketplace") or "extension",
        "path": path,
        "symbol": symbol,
        "line": line,
        "field": meta.get("field") or symbol,
        "snippet": _body_after_meta(content)[:800],
    }


def _verify_hit(db: Session | None, meta: dict[str, str], content: str, path_prefix: str) -> dict | None:
    kind = meta.get("kind") or ""
    if kind == "category":
        if db is None:
            return None
        return _verify_category(db, meta.get("marketplace") or "", meta.get("id") or "", path_prefix)
    if kind == "schema":
        if db is None:
            return None
        return _verify_schema(db, meta.get("id") or "", meta.get("general_path") or "")
    if kind == "option":
        return _verify_option(meta, content)
    if kind == "skill":
        return _verify_skill(meta, content)
    if kind == "fill":
        return _verify_fill(meta, content)
    return None


def _lexical_docs(
    query: str,
    *,
    marketplace: str | None,
    kind: str,
    top_k: int,
) -> list[dict]:
    docs = catalog_docs_dir()
    if not docs.is_dir():
        return []
    tokens = [token.casefold() for token in re.findall(r"[a-z0-9']+", query.casefold()) if len(token) > 1]
    hits: list[tuple[int, dict]] = []
    folders = {
        "category": ["categories"],
        "schema": ["schemas"],
        "option": ["options"],
        "skill": ["skills"],
        "fill": ["fill"],
        "all": ["categories", "schemas", "options", "skills", "fill"],
    }.get(kind, [])
    for folder in folders:
        base = docs / folder
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            meta = _parse_doc(content)
            mp = meta.get("marketplace") or ""
            if marketplace and mp and mp != marketplace:
                continue
            hay = content.casefold()
            score = sum(hay.count(token) for token in tokens) if tokens else 0
            if tokens and score <= 0:
                continue
            verified = _verify_hit(None, meta, content, "")  # type: ignore[arg-type]
            if kind in {"category", "schema"}:
                continue  # category/schema lexical uses DB below
            if not verified:
                continue
            verified["score"] = float(score)
            hits.append((score, verified))
    hits.sort(key=lambda item: (-item[0], item[1].get("id") or ""))
    return [item for _, item in hits[:top_k]]


def _lexical_fallback(
    db: Session,
    query: str,
    *,
    marketplace: str | None,
    kind: str,
    top_k: int,
    path_prefix: str,
) -> list[dict]:
    """Substring rank when the Semble index is empty or returns nothing."""
    tokens = [token.casefold() for token in re.findall(r"[a-z0-9']+", query.casefold()) if len(token) > 1]
    hits: list[tuple[int, dict]] = []
    if kind in {"category", "all"}:
        q = _leaf_query(db)
        if marketplace:
            q = q.filter_by(marketplace=marketplace)
        for node in q.all():
            if path_prefix and not node.path.startswith(path_prefix.rstrip() + " >") and node.path != path_prefix:
                continue
            hay = node.path.casefold()
            score = sum(hay.count(token) for token in tokens) if tokens else 0
            if tokens and score <= 0:
                continue
            hits.append((score, {
                "kind": "category",
                "marketplace": node.marketplace,
                "id": node.category_id,
                "path": node.path,
                "label": node.label,
                "score": float(score),
            }))
    if kind in {"schema", "all"}:
        q = db.query(CategorySchema)
        if marketplace:
            q = q.filter_by(marketplace=marketplace)
        for row in q.all():
            hay = f"{row.general_path} {row.category_path}".casefold()
            score = sum(hay.count(token) for token in tokens) if tokens else 0
            if tokens and score <= 0:
                continue
            hits.append((score, {
                "kind": "schema",
                "marketplace": row.marketplace,
                "id": row.id,
                "path": row.category_path,
                "general_path": row.general_path,
                "fields": row.fields if isinstance(row.fields, list) else [],
                "score": float(score),
            }))
    if kind in {"option", "skill", "fill", "all"}:
        for hit in _lexical_docs(query, marketplace=marketplace, kind=kind if kind != "all" else "all", top_k=top_k):
            hits.append((int(hit.get("score") or 0), hit))
    hits.sort(key=lambda item: (-item[0], item[1].get("path") or item[1].get("id") or ""))
    return [item for _, item in hits[:top_k]]


def search_catalog(
    db: Session,
    query: str,
    *,
    marketplace: str | None = None,
    kind: str = "all",
    top_k: int = 15,
    path_prefix: str = "",
    ensure: bool = True,
) -> list[dict]:
    """Return verified catalog hits for a natural-language or path-like query."""
    query = str(query or "").strip()
    kind = str(kind or "all").strip().lower()
    if kind not in SEARCH_KINDS:
        raise ValueError("kind must be category, schema, option, skill, fill, or all")
    if not query:
        return []
    if ensure:
        ensure_catalog_index(db)

    with _INDEX_LOCK:
        index = _INDEX
    results: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    if index is not None:
        try:
            raw = index.search(query, top_k=max(top_k * 4, top_k))
        except Exception:
            log.exception("semble catalog search failed; using lexical fallback")
            raw = []
        for item in raw:
            chunk = getattr(item, "chunk", None)
            content = getattr(chunk, "content", "") if chunk is not None else ""
            meta = _parse_doc(content)
            hit_kind = meta.get("kind") or ""
            if kind != "all" and hit_kind != kind:
                continue
            mp = meta.get("marketplace") or ""
            if marketplace and mp and mp != marketplace:
                continue
            verified = _verify_hit(db, meta, content, path_prefix)
            if not verified:
                continue
            key = (verified["kind"], verified.get("marketplace") or "", verified.get("id") or verified.get("path") or "")
            if key in seen:
                continue
            seen.add(key)
            verified["score"] = float(getattr(item, "score", 0.0) or 0.0)
            results.append(verified)
            if len(results) >= top_k:
                return results

    if not results:
        return _lexical_fallback(
            db, query, marketplace=marketplace, kind=kind, top_k=top_k, path_prefix=path_prefix,
        )
    return results[:top_k]


def relevant_skill_rules(db: Session, query: str, *, max_chars: int = 8000, top_k: int = 8) -> str:
    """Return the most relevant list-this skill/reference chunks for a listing query."""
    query = str(query or "").strip()
    if not query:
        parts = []
        for path in _skill_files():
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except OSError:
                continue
        return "\n\n---\n\n".join(parts)[:max_chars]

    hits = search_catalog(db, query, kind="skill", top_k=top_k)
    if not hits:
        skill_md = skills_dir() / "list-this" / "SKILL.md"
        return skill_md.read_text(encoding="utf-8")[:max_chars] if skill_md.is_file() else ""

    parts: list[str] = []
    used = 0
    for hit in hits:
        title = hit.get("title") or hit.get("path") or "Rule"
        snippet = str(hit.get("snippet") or "").strip()
        if not snippet:
            continue
        block = f"### {title}\n{snippet}"
        if used + len(block) + 2 > max_chars:
            remain = max_chars - used - 2
            if remain > 200:
                parts.append(block[:remain])
            break
        parts.append(block)
        used += len(block) + 2
    return "\n\n".join(parts)


def enrich_gaps_with_catalog_options(db: Session, gaps: list[dict], *, top_k: int = 3) -> list[dict]:
    """Attach verified dropdown options from the catalog index onto repair gaps."""
    enriched: list[dict] = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        copy = dict(gap)
        existing = _option_labels(copy.get("options"))
        if copy.get("options_complete") and existing:
            enriched.append(copy)
            continue
        marketplace = str(copy.get("marketplace") or "general")
        field = str(copy.get("field") or "").strip()
        if not field:
            enriched.append(copy)
            continue
        search_mp = "general" if marketplace in {"vendoo", "general"} else marketplace
        try:
            hits = search_catalog(
                db,
                f"{search_mp} {field} dropdown options",
                marketplace=search_mp,
                kind="option",
                top_k=top_k,
            )
        except Exception:
            log.exception("catalog option enrichment failed for %s/%s", marketplace, field)
            enriched.append(copy)
            continue
        field_key = field.casefold()
        merged = list(existing)
        matched_dropdown = False
        for hit in hits:
            hit_field = str(hit.get("field") or "").casefold()
            if hit_field != field_key and field_key not in hit_field and hit_field not in field_key:
                continue
            for option in hit.get("options") or []:
                if option not in merged:
                    merged.append(option)
            if str(hit.get("id") or "").endswith(":dropdown_json") and hit_field == field_key:
                matched_dropdown = True
        if merged:
            copy["options"] = merged[:60]
            if matched_dropdown:
                copy["options_complete"] = True
        enriched.append(copy)
    return enriched


def fill_helpers_for_fields(
    db: Session,
    fields: list[dict],
    *,
    top_k: int = 3,
) -> list[dict]:
    """Find extension fill helpers related to failed/uncertain fill-log fields."""
    hints: list[dict] = []
    seen: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("field") or "").strip()
        marketplace = str(field.get("marketplace") or "").strip()
        status = str(field.get("status") or "").strip().casefold()
        if not name or status not in {"failed", "invalid", "not_found", "uncertain", "skipped"}:
            continue
        query = f"{marketplace} {name} fill"
        for hit in search_catalog(db, query, marketplace=marketplace or None, kind="fill", top_k=top_k):
            helper_id = str(hit.get("id") or "")
            if helper_id in seen:
                continue
            seen.add(helper_id)
            hints.append({
                "field": name,
                "marketplace": marketplace,
                "symbol": hit.get("symbol"),
                "path": hit.get("path"),
                "line": hit.get("line"),
                "snippet": hit.get("snippet"),
                "score": hit.get("score"),
            })
    return hints
