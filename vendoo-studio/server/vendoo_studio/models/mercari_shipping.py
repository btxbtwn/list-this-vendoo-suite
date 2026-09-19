"""Mercari's USPS Ground Advantage shipping labels, keyed by package weight.

Vendoo's Mercari form stores the Shipping Label as a carrier id
(``listings.mercari.marketplaceSpecifics.shipping.carrierId``) and only offers
the tiers whose weight cap covers the package — a stored id outside that list
leaves the dropdown blank and is cleared on the next edit. So the tier has to
follow the listing's weight rather than being one fixed id.

The ids, prices and tier names are Vendoo's own ``shippingCarriers`` table
(``carrier: shippo_usps``, ``handlingType: standard``, ``rateType: standard``);
the label text is the form's ``displayValue`` for the same row.
"""

from __future__ import annotations

from typing import Any

# (max ounces inclusive, carrier id, tier name, price in cents)
GROUND_ADVANTAGE_TIERS: tuple[tuple[int, str, str, int], ...] = (
    (4, "2507", "0.25 lb", 587),
    (8, "2508", "0.5 lb", 641),
    (12, "2509", "0.75 lb", 748),
    (16, "2510", "1 lb", 812),
    (32, "2511", "2 lb", 1443),
    (48, "2512", "3 lb", 1604),
    (64, "2513", "4 lb", 1711),
    (80, "2514", "5 lb", 1818),
    (96, "2515", "6 lb", 1925),
    (112, "2516", "7 lb", 2032),
    (128, "2517", "8 lb", 2139),
    (144, "2518", "9 lb", 2246),
    (160, "2519", "10 lb", 2353),
    (176, "2520", "11 lb", 2781),
    (192, "2521", "12 lb", 2889),
    (208, "2522", "13 lb", 2996),
    (224, "2523", "14 lb", 3103),
    (240, "2524", "15 lb", 3210),
    (256, "2525", "16 lb", 3317),
    (272, "2526", "17 lb", 3424),
    (288, "2527", "18 lb", 3531),
    (304, "2528", "19 lb", 3745),
    (320, "2529", "20 lb", 3852),
)

# The weight every listing gets when it carries none. Half a pound is what this
# seller's garments are packed at, and the form refuses a label without one.
DEFAULT_PACKAGE_OUNCES = 8


def _label(name: str, fee_cents: int) -> str:
    return f"USPS Ground Advantage / 1 - 7 days / $ {fee_cents / 100:.2f} / {name}"


def ground_advantage(weight_oz: int | float | None) -> tuple[str, str]:
    """``(carrier id, label)`` for the tier that carries ``weight_oz``."""
    try:
        ounces = int(weight_oz or 0)
    except (TypeError, ValueError):
        ounces = 0
    if ounces <= 0:
        ounces = DEFAULT_PACKAGE_OUNCES
    for max_oz, carrier_id, name, fee in GROUND_ADVANTAGE_TIERS:
        if ounces <= max_oz:
            return carrier_id, _label(name, fee)
    max_oz, carrier_id, name, fee = GROUND_ADVANTAGE_TIERS[-1]
    return carrier_id, _label(name, fee)


def package_ounces(pounds: Any = 0, ounces: Any = 0) -> int:  # noqa: ANN401 - form strings
    """Total ounces the way Vendoo's form reads its weight fields."""
    def whole(value: Any) -> int:
        try:
            return int(float(str(value).strip() or 0))
        except (TypeError, ValueError):
            return 0

    return whole(pounds) * 16 + whole(ounces)


# Default label for a half-pound package — what almost every listing here ships as.
DEFAULT_SHIPPING_LABEL = ground_advantage(DEFAULT_PACKAGE_OUNCES)[1]