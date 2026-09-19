"""Vendoo's own field schema for one category, per marketplace.

Vendoo's forms decide which inputs to render by asking
``/api/category/specifics/{marketplaceID}/category/{categoryID}`` as soon as a
leaf is chosen, passing that leaf's ancestor ids and ``extras``. The answer is
the only authority on which aspects a category has, which are required, which
take several values, and which coded options are allowed — so Studio asks the
same question instead of inferring fields from Studio's own key names.

Shape per entry (``parseCategorySpecificsV2ToV1`` in Vendoo's bundle):

    {"Season": {"id", "display", "rules": {"fieldOptions": {
        "minValues", "maxValues", "selectionMode"}}, "options": {...}}}

``minValues >= 1`` means required, ``maxValues > 1`` means the stored value is a
list, and ``selectionMode == "SelectionOnly"`` means only a coded option id may
be stored. Getting the last two wrong is what makes the marketplace form throw:
an eBay condition of ``"Pre-Owned - Good"`` where ``"3000"`` was required has no
matching option, so the form's lookup returns undefined and the tab crashes.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "FieldSpec",
    "MERCARI_STATIC_URL",
    "mercari_specifics",
    "normalize_specifics",
    "specs_from_rows",
    "specs_to_rows",
    "encode_specific",
    "encode_scaled",
    "is_not_applicable",
    "specifics_key",
    "scale_key",
    "missing_required",
]

SELECTION_ONLY = "SelectionOnly"

# Mercari is the one marketplace Vendoo does not serve category specifics for.
# Its only category-dependent field is size, and it ships as a static file that
# maps a category to a size group. Public, no session needed.
MERCARI_STATIC_URL = "https://images.vendoo.co/statics/mercari/mercari.sizes.json"


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


class FieldSpec:
    """One category field, as Vendoo describes it."""

    __slots__ = (
        "key", "display", "required", "multi", "selection_only", "options",
        "field_type", "scales",
    )

    def __init__(
        self,
        key: str,
        *,
        display: str = "",
        required: bool = False,
        multi: bool = False,
        selection_only: bool = False,
        options: dict[str, str] | None = None,
        field_type: str = "",
        scales: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.key = key
        self.display = display or key
        self.required = required
        self.multi = multi
        self.selection_only = selection_only
        self.options = options or {}
        self.field_type = field_type
        # ``{scale id: {"display", "options"}}``. Sizes come this way: the
        # seller picks a scale (US Juniors, EU Plus) and then a value within
        # it, and Vendoo stores both.
        self.scales = scales or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display": self.display,
            "required": self.required,
            "multi": self.multi,
            "selection_only": self.selection_only,
            "field_type": self.field_type,
            "options": dict(self.options),
            "scales": {
                scale_id: {
                    "display": str(scale.get("display") or scale_id),
                    "options": dict(scale.get("options") or {}),
                }
                for scale_id, scale in self.scales.items()
            },
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FieldSpec({self.key!r}, required={self.required}, multi={self.multi})"


def specs_to_rows(specs: dict[str, FieldSpec]) -> list[dict[str, Any]]:
    """Field specs as plain rows, for caching or for the UI."""
    return [specs[key].as_dict() for key in sorted(specs)]


def specs_from_rows(rows: Any) -> dict[str, FieldSpec]:
    """Rehydrate what ``specs_to_rows`` stored."""
    out: dict[str, FieldSpec] = {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("key"):
            continue
        out[str(row["key"])] = FieldSpec(
            str(row["key"]),
            display=str(row.get("display") or row["key"]),
            required=bool(row.get("required")),
            multi=bool(row.get("multi")),
            selection_only=bool(row.get("selection_only")),
            options={str(k): str(v) for k, v in (row.get("options") or {}).items()},
            field_type=str(row.get("field_type") or ""),
            scales={
                str(scale_id): {
                    "display": str((scale or {}).get("display") or scale_id),
                    "options": {str(k): str(v) for k, v in ((scale or {}).get("options") or {}).items()},
                }
                for scale_id, scale in (row.get("scales") or {}).items()
            },
        )
    return out


def mercari_specifics(master: Any, category_id: Any) -> dict[str, FieldSpec]:
    """Mercari's size field for one category, from its static master data.

    Mercari is the one marketplace ``/api/category/specifics`` answers nothing
    for. Its only category-dependent field is size, distributed as
    ``{"categorySizeGroup": {category id: group id}, "itemSizes": [{id, name,
    itemSizeGroupId, itemSizeSubGroupId}]}``. Vendoo stores the chosen size
    flat, as ``{categoryId}_Size`` holding the numeric ``itemSizeId`` — no
    scale companion, unlike Poshmark and Etsy.

    A size group repeats the same labels across its sub-groups (four of them
    carry an identical "M (8-10)"), so identical labels are collapsed to the
    lowest sub-group's id. That drops no distinct choice. Labels that merely
    look alike are kept apart: standard "M (8-10)" and juniors "M (7-9)" both
    survive, which is why a listing that only says "M" is reported rather than
    resolved — the seller has to say which.

    A category with no size group offers no size at all; that is an answer, not
    a failure.
    """
    if not isinstance(master, dict) or not category_id:
        return {}
    groups = master.get("categorySizeGroup")
    groups = groups if isinstance(groups, dict) else {}
    group = groups.get(str(category_id))
    if group is None:
        return {}
    rows = [
        size for size in (master.get("itemSizes") or [])
        if isinstance(size, dict) and size.get("itemSizeGroupId") == group
        and size.get("id") not in (None, "")
    ]
    rows.sort(key=lambda size: (
        size.get("itemSizeSubGroupId") or 0,
        size.get("displayOrder") or 0,
    ))
    options: dict[str, str] = {}
    seen: set[str] = set()
    for size in rows:
        label = str(size.get("name") or " ".join(
            str(part) for part in (size.get("title"), size.get("subtitle")) if part
        ) or size["id"])
        if label in seen:
            continue
        seen.add(label)
        options[str(size["id"])] = label
    if not options:
        return {}
    return {"Size": FieldSpec(
        "Size",
        display="Size",
        required=False,
        multi=False,
        selection_only=True,
        options=options,
        field_type="select",
    )}


def _options_of(entry: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for option in (entry.get("options") or {}).values():
        if not isinstance(option, dict):
            continue
        code = option.get("id")
        if code in (None, ""):
            continue
        out[str(code)] = str(option.get("display") or code)
    return out


def _scales_of(raw: dict[str, Any], key: str, entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The nested scales a field offers, if its options are other fields.

    Size works this way on Poshmark and Etsy: the parent's options are scale
    ids (``standard``, ``plus-eu``) and each names an ``embedded`` entry that
    holds the values for that scale. Vendoo stores the pair, so both have to
    survive normalising.
    """
    scales: dict[str, dict[str, Any]] = {}
    for scale_id in _options_of(entry):
        child = raw.get(scale_id)
        if not isinstance(child, dict):
            continue
        child_rules = child.get("rules") if isinstance(child.get("rules"), dict) else {}
        path = child.get("path") if isinstance(child.get("path"), list) else []
        if not child_rules.get("embedded") or not path or str(path[0]) != key:
            continue
        scales[str(scale_id)] = {
            "display": str(child.get("display") or scale_id),
            "options": _options_of(child),
        }
    return scales


def normalize_specifics(raw: Any) -> dict[str, FieldSpec]:
    """Vendoo's specifics payload into ``{key: FieldSpec}``.

    Entries Vendoo marks ``embedded`` are not fields of their own: they hold
    the values of one scale of their parent, and are folded into it rather than
    dropped — otherwise a Poshmark category looks like it has a single Size
    field with no values.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, FieldSpec] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        rules = entry.get("rules") if isinstance(entry.get("rules"), dict) else {}
        if rules.get("embedded"):
            continue
        field_options = rules.get("fieldOptions") if isinstance(rules.get("fieldOptions"), dict) else {}
        try:
            min_values = int(field_options.get("minValues") or 0)
        except (TypeError, ValueError):
            min_values = 0
        try:
            max_values = int(field_options.get("maxValues") or 1)
        except (TypeError, ValueError):
            max_values = 1
        scales = _scales_of(raw, str(key), entry)
        out[str(key)] = FieldSpec(
            str(key),
            display=str(entry.get("display") or key),
            required=min_values >= 1,
            multi=max_values > 1,
            selection_only=str(field_options.get("selectionMode") or "") == SELECTION_ONLY,
            # A scaled field's own options are the scale ids, not values.
            options={} if scales else _options_of(entry),
            field_type=str(rules.get("fieldType") or ""),
            scales=scales,
        )
    return out


def specifics_key(category_id: Any, key: str) -> str:
    """``categorySpecifics`` is keyed ``{categoryId}_{field key}``."""
    return f"{category_id}_{key}"


def scale_key(category_id: Any, key: str) -> str:
    """The companion key Vendoo stores a scaled field's chosen scale under."""
    return f"{category_id}_{key}_scale"


def encode_scaled(spec: FieldSpec, value: Any) -> tuple[str, str, bool]:
    """Resolve a value against a scaled field's scales.

    Returns ``(scale_id, code, resolved)``. Scales are searched for one that
    actually offers the value, so "M" lands on US Juniors rather than on
    whichever scale happens to be first.
    """
    text = str(value or "").strip()
    if not text:
        return "", "", True
    wanted = _norm(text)
    for scale_id, scale in spec.scales.items():
        options = scale.get("options") or {}
        if text in options:
            return scale_id, text, True
        for code, display in options.items():
            if _norm(display) == wanted or _norm(code) == wanted:
                return scale_id, code, True
    return "", "", False


def _parts(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip() for part in value if str(part or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")
# What a model says when an attribute does not apply to the item. Only a real
# answer when the field actually offers it as a choice.
_DECLINED = frozenset({
    "does not apply", "doesn't apply", "not applicable", "n a", "na", "none",
    "no", "not specified", "unspecified", "unknown", "other",
})
# The literal "this attribute does not apply" answers, already normalized. The
# listing keeps them so Studio can show the field was answered; a marketplace
# form never gets the phrase itself.
_NOT_APPLICABLE = frozenset({
    "does not apply", "doesn t apply", "doesnt apply", "not applicable", "n a", "na",
})
# Fields where an unlisted answer belongs under a catch-all rather than being
# dropped: a brand Vendoo has never heard of is still a brand.
_OTHER_FALLBACK_FIELDS = frozenset({"brand", "style", "type", "material", "colour", "color"})


def is_not_applicable(value: Any) -> bool:
    """Every part of ``value`` says the attribute does not apply."""
    parts = _parts(value)
    return bool(parts) and all(_norm(part) in _NOT_APPLICABLE for part in parts)


def _encode_one(spec: FieldSpec, text: str) -> str | None:
    """A single human value into the option id Vendoo stores."""
    if not spec.options:
        return text
    if text in spec.options:
        return text
    wanted = _norm(text)
    for code, display in spec.options.items():
        if _norm(display) == wanted or _norm(code) == wanted:
            return code
    # Some vocabularies qualify the label — Mercari sizes read "M (8-10)" where
    # a listing just says "M". Accept that only when one option matches, so a
    # genuinely ambiguous size is reported instead of guessed.
    stripped = [
        code for code, display in spec.options.items()
        if _norm(_PARENTHETICAL.sub("", display)) == wanted
    ]
    if len(stripped) == 1:
        return stripped[0]
    return None


def _other_option(spec: FieldSpec) -> str | None:
    """The field's catch-all option, for answers its list does not carry."""
    if _norm(spec.key) not in _OTHER_FALLBACK_FIELDS and _norm(spec.display) not in _OTHER_FALLBACK_FIELDS:
        return None
    for code, display in spec.options.items():
        if _norm(display) in ("other", "others"):
            return code
    return None


def encode_specific(spec: FieldSpec, value: Any) -> tuple[Any, bool]:
    """Encode one field's value the way Vendoo stores it.

    Returns ``(stored, resolved)``. ``resolved`` is False only when the field
    accepts coded options exclusively and nothing matched — the caller should
    report that rather than store a value the form cannot look up.
    """
    parts = _parts(value)
    if not parts:
        return ([] if spec.multi else ""), True
    if not spec.multi:
        parts = parts[:1] if spec.selection_only or len(parts) == 1 else [", ".join(parts)]
    encoded: list[str] = []
    resolved = True
    for part in parts:
        # "Does Not Apply" is the model declining, never something to write —
        # even on the lists that offer it as a choice. eBay renders the phrase
        # verbatim in the form, so the field is left blank instead.
        if _norm(part) in _NOT_APPLICABLE:
            continue
        code = _encode_one(spec, part)
        if code is None and spec.selection_only:
            # The rest of the declines ("none", "unknown") against a list
            # that does not offer them are the model declining too, not a
            # value Vendoo rejected. Reporting them buries the real gaps.
            if _norm(part) in _DECLINED:
                continue
            code = _other_option(spec)
        if code is None:
            if spec.selection_only:
                resolved = False
                continue
            code = part
        encoded.append(code)
    if not encoded:
        return ([] if spec.multi else ""), resolved
    return (encoded if spec.multi else encoded[0]), resolved


def missing_required(specs: dict[str, FieldSpec], stored: dict[str, Any], category_id: Any) -> list[str]:
    """Required field keys this payload leaves empty."""
    out: list[str] = []
    for key, spec in specs.items():
        if not spec.required:
            continue
        value = stored.get(specifics_key(category_id, key))
        if value in (None, "", [], {}):
            out.append(key)
    return out
