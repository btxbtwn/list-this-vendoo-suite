"""Facebook's prepaid-label Package weight, keyed by package weight.

Vendoo's Facebook form stores the dropdown's own label in
``listings.facebook.marketplaceSpecifics.packageWeightLabel`` and turns it back
into a weight with its own table (``"0.5-1 lbs"`` -> 0 lb 15 oz) when it lists.
The labels below are that table's, in the order the form offers them; each
tier's cap is the weight Vendoo sends for it.

The Shipping carrier beside it is not a fixed list: Facebook answers it per
category and weight, and Vendoo stores ``"<shipping_service_type>:<name>"``.
Studio learns that value from the seller's own Facebook forms — see
``observe_listing_encodings``.
"""

from __future__ import annotations

from typing import Any

from vendoo_studio.models.mercari_shipping import DEFAULT_PACKAGE_OUNCES, package_ounces

# (max ounces inclusive, label)
PACKAGE_WEIGHT_TIERS: tuple[tuple[int, str], ...] = (
    (7, "Under 0.5 lbs"),
    (15, "0.5-1 lbs"),
    (31, "1-2 lbs"),
    (79, "2-5 lbs"),
    (159, "5-10 lbs"),
)


def package_weight_label(weight: dict[str, Any] | None) -> str:
    """The Package weight tier for a ``{pounds, ounces}`` weight, or "".

    A listing with no weight ships as the default half-pound package, the same
    as Mercari's label. Past ten pounds Facebook's tiers are custom, so nothing
    is chosen and the seller picks it.
    """
    weight = weight if isinstance(weight, dict) else {}
    ounces = package_ounces(weight.get("pounds"), weight.get("ounces")) or DEFAULT_PACKAGE_OUNCES
    for max_oz, label in PACKAGE_WEIGHT_TIERS:
        if ounces <= max_oz:
            return label
    return ""
