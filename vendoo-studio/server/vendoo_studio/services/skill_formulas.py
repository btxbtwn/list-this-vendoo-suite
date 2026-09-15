"""Always-on list-this title/description/pricing formulas for generation prompts."""

from __future__ import annotations

import re
from functools import lru_cache

from vendoo_studio.config import skills_dir

_FORMULA_HEADING = re.compile(r"^##\s+Formula Reference\b.*$", re.M)
_SECTION_HEADING = re.compile(r"^##\s+\S", re.M)

_FALLBACK_FORMULAS = """## Formula Reference (NON-NEGOTIABLE)

### TITLE Formula
```
{BRAND} {SIZE} {VIBE} {ITEM} {COLOR} {FIT}
```
- EXACT order
- Max 80 characters
- Example: `Levi's 33 Y2K 511 Slim Shorts Black Denim`

### DESCRIPTION Formula (Line breaks MANDATORY)
```
{vibe sentence with period}

{fit/fabric sentence with period}

Size: {size}

Condition: {status}; Flaws: {none or specific}. See photos for details.

Measurements: {See photos OR specific measurements}

OFFERS WELCOME! Ships in 1-2 business days.

15% off bundles of 2+ items.
```

### PRICING Formula
```
Listing Price = Market comp × 1.35 (round to nearest dollar)
```
"""


@lru_cache(maxsize=1)
def listing_formula_rules(*, max_chars: int = 3500) -> str:
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
