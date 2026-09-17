"""Always-on list-this title/description/pricing formulas for generation prompts."""

from __future__ import annotations

import re
from functools import lru_cache

from vendoo_studio.config import skills_dir
from vendoo_studio.services.user_settings import get_listing_formulas

_FORMULA_HEADING = re.compile(r"^##\s+Formula Reference\b.*$", re.M)
_SECTION_HEADING = re.compile(r"^##\s+\S", re.M)
_TITLE_BLOCK_RE = re.compile(r"(?s)(### TITLE Formula\n```\n).*?(\n```)")
_DESCRIPTION_BLOCK_RE = re.compile(r"(?s)(### DESCRIPTION Formula[^\n]*\n```\n).*?(\n```)")
_MARKER_LINE_RE = re.compile(r"(?m)^([A-Za-z][A-Za-z /]{1,20}):\s*\{")

DEFAULT_TITLE_FORMULA = "{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}"
DEFAULT_DESCRIPTION_FORMULA = (
    "{trendy vibe/style keyword sentence with period}\n\n"
    "Flaws: {none noted or specific}. See photos for details.\n\n"
    "Measurements: {See photos OR specific measurements}"
)
DEFAULT_DESCRIPTION_MARKERS = ("flaws:", "measurements:")

_FALLBACK_FORMULAS = f"""## Formula Reference (NON-NEGOTIABLE)

### TITLE Formula
```
{DEFAULT_TITLE_FORMULA}
```
- EXACT order
- Max 80 characters
- Example: `Levi's 33 Y2K 511 Slim Shorts Black Denim`

### DESCRIPTION Formula (Line breaks MANDATORY)
```
{DEFAULT_DESCRIPTION_FORMULA}
```

### PRICING Formula
```
Listing Price = Market comp × 1.35 (round to nearest dollar)
```
"""


@lru_cache(maxsize=1)
def _base_formula_rules(*, max_chars: int = 3500) -> str:
    """Return the non-negotiable Formula Reference section from list-this SKILL.md."""
    skill_md = skills_dir() / "list-this" / "SKILL.md"
    if not skill_md.is_file():
        return _FALLBACK_FORMULAS[:max_chars]
    text = skill_md.read_text(encoding="utf-8")
    start = _FORMULA_HEADING.search(text)
    if not start:
        return _FALLBACK_FORMULAS[:max_chars]
    rest = text[start.start() :]
    end = len(rest)
    for match in _SECTION_HEADING.finditer(rest):
        if match.start() > 0:
            end = match.start()
            break
    section = rest[:end].strip()
    if "TITLE Formula" not in section or "DESCRIPTION Formula" not in section:
        return _FALLBACK_FORMULAS[:max_chars]
    return section[:max_chars]


def listing_formula_rules(*, max_chars: int = 3500) -> str:
    """Base formula reference with any user-customized title/description swapped in."""
    text = _base_formula_rules(max_chars=max_chars)
    custom = get_listing_formulas()
    if not custom:
        return text
    title = custom.get("title")
    if title:
        text = _TITLE_BLOCK_RE.sub(lambda m: m.group(1) + title + m.group(2), text, count=1)
    description = custom.get("description")
    if description:
        text = _DESCRIPTION_BLOCK_RE.sub(lambda m: m.group(1) + description + m.group(2), text, count=1)
    return text[:max_chars]


def description_formula_markers() -> tuple[str, ...]:
    """Required `Label:` markers a generated description must contain.

    Derived from the active (custom or default) DESCRIPTION formula so validation
    stays in sync when the user edits the formula in Settings.
    """
    template = get_listing_formulas().get("description") or DEFAULT_DESCRIPTION_FORMULA
    found = tuple(sorted({f"{m.group(1).strip().lower()}:" for m in _MARKER_LINE_RE.finditer(template)}))
    return found or DEFAULT_DESCRIPTION_MARKERS


def with_pinned_formulas(skill_rules: str, *, max_chars: int = 10000) -> str:
    """Put title/description formulas first, then other skill chunks."""
    pinned = listing_formula_rules()
    rest = str(skill_rules or "").strip()
    if not rest:
        return pinned[:max_chars]
    # Avoid duplicating the same Formula Reference block when the fallback is full SKILL.md.
    if rest.lstrip().startswith("## Formula Reference") or "### TITLE Formula" in rest[:2000]:
        return rest[:max_chars]
    combined = f"{pinned}\n\n--- Additional listing rules ---\n\n{rest}"
    return combined[:max_chars]
