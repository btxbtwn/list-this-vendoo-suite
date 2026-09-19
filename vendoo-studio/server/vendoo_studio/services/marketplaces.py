from __future__ import annotations

from vendoo_studio.services.user_settings import read_settings, update_settings

# Order used when filling Vendoo marketplace forms.
#
# The goal is to sell everywhere Vendoo reaches, so treat this list as the
# current reach rather than the intended one. Adding a marketplace needs two
# things, and they are independent:
#
#   * a field schema. Vendoo answers
#     GET /api/category/specifics/{marketplace}/category/{id} for ebay, etsy,
#     whatnot, sellwild, vestiaireApi, shopify, mercari, grailed, poshmark,
#     facebook, depop, vestiaire, vinted and vendoo — so grailed, vinted,
#     facebook, whatnot and kidizen could be filled today with no new
#     discovery work. Tradesy is gone: Vendoo dropped it from that list and
#     the company itself closed in 2022.
#   * somewhere for the values to go, which is what this list drives.
FILLABLE_MARKETPLACES = ("ebay", "etsy", "poshmark", "mercari", "depop")

# Marketplaces shown in Settings and Fields. `fillable` ones have Send-to-Vendoo form fillers.
MARKETPLACE_CATALOG: tuple[tuple[str, str, bool], ...] = (
    ("ebay", "eBay", True),
    ("poshmark", "Poshmark", True),
    ("mercari", "Mercari", True),
    ("depop", "Depop", True),
    ("etsy", "Etsy", True),
    ("facebook", "Facebook", False),
    ("grailed", "Grailed", False),
    ("whatnot", "Whatnot", False),
    ("shopify", "Shopify", False),
)

KNOWN_MARKETPLACES = tuple(item[0] for item in MARKETPLACE_CATALOG)
DEFAULT_SELECTED = list(FILLABLE_MARKETPLACES)


def marketplace_label(marketplace_id: str) -> str:
    for item_id, label, _fillable in MARKETPLACE_CATALOG:
        if item_id == marketplace_id:
            return label
    return marketplace_id[:1].upper() + marketplace_id[1:] if marketplace_id else marketplace_id


def catalog_payload() -> list[dict]:
    return [
        {"id": item_id, "label": label, "fillable": fillable}
        for item_id, label, fillable in MARKETPLACE_CATALOG
    ]


def normalize_selected(raw: object) -> list[str]:
    """Normalize a marketplace selection.

    Only fillable platforms may remain selected. Unsupported catalog entries
    (Facebook, Grailed, Whatnot, Shopify) are dropped so they cannot reach
    Send or the approved job snapshot.
    """
    if not isinstance(raw, list):
        return list(DEFAULT_SELECTED)
    chosen = {str(item).strip().lower() for item in raw if str(item).strip()}
    unknown = sorted(chosen - set(KNOWN_MARKETPLACES))
    if unknown:
        raise ValueError(f"Unknown marketplace: {', '.join(unknown)}")
    return [item_id for item_id in FILLABLE_MARKETPLACES if item_id in chosen]


def unsupported_in_selection(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    chosen = {str(item).strip().lower() for item in raw if str(item).strip()}
    return [item_id for item_id, _label, fillable in MARKETPLACE_CATALOG if not fillable and item_id in chosen]


def get_selected_marketplaces() -> list[str]:
    payload = read_settings()
    if "marketplaces" not in payload:
        return list(DEFAULT_SELECTED)
    try:
        normalized = normalize_selected(payload.get("marketplaces"))
    except ValueError:
        return list(DEFAULT_SELECTED)
    # Persist strip of unsupported selections so Settings and Send stay aligned.
    stored = payload.get("marketplaces")
    if isinstance(stored, list):
        stored_norm = [str(item).strip().lower() for item in stored if str(item).strip()]
        if stored_norm != normalized:
            update_settings(lambda body: body.__setitem__("marketplaces", normalized))
    return normalized


def set_selected_marketplaces(selected: object) -> list[str]:
    blocked = unsupported_in_selection(selected)
    if blocked:
        labels = ", ".join(marketplace_label(item_id) for item_id in blocked)
        raise ValueError(
            f"{labels} cannot be selected for Send — automation is not available for "
            "these marketplaces yet. Choose only eBay, Poshmark, Mercari, Depop, or Etsy."
        )
    normalized = normalize_selected(selected)
    update_settings(lambda payload: payload.__setitem__("marketplaces", normalized))
    return normalized


def selected_fillable_platforms(selected: list[str] | None = None) -> list[str]:
    chosen = set(selected if selected is not None else get_selected_marketplaces())
    return [marketplace for marketplace in FILLABLE_MARKETPLACES if marketplace in chosen]
