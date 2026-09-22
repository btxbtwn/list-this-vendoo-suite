"""Decide which verified draft gaps can be patched deterministically and which need review."""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from vendoo_studio.repositories.queries import FillLogRepo
from vendoo_studio.services.fill_log import (
    field_lookup_key,
    listing_value_for_field,
    write_values_into_listing,
)
from vendoo_studio.services.registry import (
    SELLER_SETTING_LABELS,
    is_account_managed_field,
)

log = logging.getLogger(__name__)


SOFT_GAP_ERRORS = frozenset({"", "empty field", "saved value differs"})
DNA_VALUE = "Does Not Apply"


def field_option_labels(field: dict) -> set[str]:
    labels: set[str] = set()
    for option in field.get("options") or []:
        if isinstance(option, dict):
            label = str(option.get("label") or option.get("value") or "").strip()
        else:
            label = str(option).strip()
        if label:
            labels.add(label)
    return labels


def field_id(field: dict) -> tuple[str, str]:
    return str(field.get("marketplace") or "general"), field_lookup_key(field.get("field") or field.get("label") or "")


def field_out_of_scope(marketplace: str, label: str) -> bool:
    """Seller/account rows the automation never reads back: settings, shipping, policies."""
    return (
        field_lookup_key(label) in SELLER_SETTING_LABELS
        or is_account_managed_field(marketplace, label)
    )


def is_shipping_estimate_field(label: str) -> bool:
    key = field_lookup_key(label)
    return key in {
        "weight",
        "weight lb",
        "weight lbs",
        "weight (lbs)",
        "weight oz",
        "weight (oz)",
        "pounds",
        "ounces",
        "package weight",
        "package weight (lb)",
        "package weight (oz)",
        "package dimensions",
        "package dimensions (in)",
        "dimensions",
    } or "weight" in key or key.startswith("package dimension")


def values_equal(observed, expected: str) -> bool:
    def normalize(value):
        return " ".join(str(value).split()).casefold()
    if observed is None or expected is None:
        return False
    if isinstance(observed, list):
        return {normalize(v) for v in observed} == {normalize(v) for v in str(expected).split(",")}
    if normalize(observed) == normalize(expected):
        return True
    try:
        return float(observed) == float(expected)
    except (TypeError, ValueError):
        return False


# Neither form accepts a free-text brand. Depop offers an "Other" option; Mercari
# has no brand value at all — it has a "No Brand/Not sure" checkbox.
DEPOP_BRAND_FALLBACK = "Other"
MERCARI_NO_BRAND_LABEL = "No Brand/Not sure"
BRAND_FALLBACKS = {"depop": DEPOP_BRAND_FALLBACK, "mercari": MERCARI_NO_BRAND_LABEL}


def brand_fallback_for(marketplace: str) -> str:
    """The value that stands in for a brand this marketplace does not list."""
    return BRAND_FALLBACKS.get(str(marketplace or "").strip().lower(), "")


def brand_is_offered(field: dict, brand: str) -> bool:
    """True only when a captured option list proves the marketplace carries this brand."""
    text = str(brand or "").strip()
    if not text:
        return False
    labels = field_option_labels(field)
    if not field.get("options_complete") or not labels:
        return False
    return any(values_equal(label, text) for label in labels)


def brand_missing_from_options(field: dict, brand: str) -> bool:
    """True when there is no brand, or a captured list proves the marketplace lacks it."""
    text = str(brand or "").strip()
    if not text:
        return True
    labels = field_option_labels(field)
    if not field.get("options_complete") or not labels:
        return False
    return not brand_is_offered(field, text)


def _mercari_no_brand_checked(fields: list[dict] | None) -> bool:
    for field in fields or []:
        if field_lookup_key(str(field.get("label") or field.get("field") or "")) != "no brand not sure":
            continue
        value = field.get("value")
        if isinstance(value, str):
            return value.strip().casefold() in {"true", "yes", "on", "checked", "1"}
        return bool(value)
    return False


def brand_fallback_in_place(
    marketplace: str,
    field: dict,
    observed,
    expected: str,
    section_fields: list[dict] | None,
) -> bool:
    """True when the draft already shows this marketplace's no-brand answer."""
    label = str(field.get("label") or field.get("field") or "")
    if field_lookup_key(label) != "brand" or not brand_fallback_for(marketplace):
        return False
    if str(field.get("error") or "").strip().casefold() not in {"", "saved value differs"}:
        return False
    if brand_is_offered(field, expected):
        return False
    if str(marketplace).strip().lower() == "depop":
        return values_equal(observed, DEPOP_BRAND_FALLBACK)
    empty = observed is None or observed == "" or observed == []
    return empty and _mercari_no_brand_checked(section_fields)


def brand_live_check_done(db: Session, job, marketplace: str) -> bool:
    """True once this job's filler already wrote the marketplace's brand answer.

    The filler owns the choice between the real brand and the fallback, so one
    pass per job settles it — without this the forced check would reopen the
    same gap every round. Typed-fallback ``uncertain`` does not count: that is
    free text the form rejected, and Mercari still needs No Brand/Not sure.
    """
    want = str(marketplace or "").strip().lower()
    for entry in FillLogRepo(db).list_for_job(job.id):
        if str(entry.marketplace or "").strip().lower() != want:
            continue
        if "brand" not in field_lookup_key(entry.field or ""):
            continue
        if str(entry.status or "").strip().casefold() == "filled":
            return True
    return False


def brand_needs_live_check(marketplace: str, field: dict, expected: str) -> bool:
    """True when only the live dropdown can settle a Depop/Mercari brand.

    The API stores whatever string it is handed in ``overrides.brand``, so a
    draft that reads back the listing's brand is no proof the marketplace
    carries it. Keep brand a gap until the option list says it is offered, so
    the filler tries the real brand and falls back to Depop "Other" /
    Mercari "No Brand/Not sure" when the form rejects it.
    """
    label = str(field.get("label") or field.get("field") or "")
    if field_lookup_key(label) != "brand" or not brand_fallback_for(marketplace):
        return False
    if not str(expected or "").strip():
        return False
    return not brand_is_offered(field, expected)


def _stringify_observed(observed) -> str:
    if isinstance(observed, list):
        return ", ".join(str(part).strip() for part in observed if str(part).strip())
    return str(observed).strip() if observed is not None else ""


def _gap_is_empty(gap: dict) -> bool:
    observed = gap.get("observed")
    return observed is None or observed == "" or observed == []


def gap_already_has_value(gap: dict, value) -> bool:
    """True when the saved draft already shows the value we would write."""
    if value is None or value == "" or value == []:
        return False
    if _gap_is_empty(gap):
        return False
    observed = gap.get("observed")
    if values_equal(observed, value):
        return True
    mapped = gap.get("mapped_expected")
    if mapped not in (None, "") and values_equal(observed, mapped) and values_equal(mapped, value):
        return True
    if mapped not in (None, "") and values_equal(observed, mapped):
        # Browser mapped listing → display value; observed already matches display.
        listing_expected = gap.get("expected")
        if listing_expected in (None, "") or values_equal(value, listing_expected) or values_equal(value, mapped):
            return True
    return False


def prior_fill_covers_empty_gap(db: Session, job, gap: dict, value) -> bool:
    """Skip re-dispatch when Send/repair already wrote this value and readback still looks empty."""
    if not value or value == []:
        return False
    if not _gap_is_empty(gap):
        return False
    error = str(gap.get("error") or "").strip().casefold()
    if error not in {"", "empty field"}:
        return False
    from vendoo_studio.services.fill_log import preview_value

    want = preview_value(value).casefold()
    if not want:
        return False
    marketplace = str(gap.get("marketplace") or "general").strip().lower() or "general"
    field_key = field_lookup_key(gap.get("field") or gap.get("label") or "")
    if not field_key:
        return False
    for entry in FillLogRepo(db).list_for_job(job.id):
        if str(entry.marketplace or "").strip().lower() != marketplace:
            continue
        if field_lookup_key(entry.field or "") != field_key:
            continue
        if str(entry.status or "").strip().casefold() not in {"filled", "uncertain"}:
            continue
        preview = str(entry.value_preview or "").strip()
        if preview and preview.casefold() == want:
            return True
        reason = str(entry.reason or "")
        if preview and values_equal(preview, value):
            return True
        if re.search(r"already set", reason, flags=re.I) and preview and values_equal(preview, value):
            return True
    return False


def prefer_listing_over_observed(revisions: list) -> bool:
    """True when the seller's Studio form is the newest listing revision."""
    if not revisions:
        return False
    return str(getattr(revisions[0], "source", "") or "") == "user_form"


def deterministic_gap_patches(
    gaps: list[dict],
    listing: dict,
    *,
    tried: set | None = None,
) -> tuple[list[dict], list[dict]]:
    """Fill gaps from listing values without an LLM pass when possible.

    Returns (ready_patches, gaps_needing_model).
    """
    tried = tried or set()
    ready: list[dict] = []
    needs_model: list[dict] = []
    accepted: set[tuple[str, str]] = set()
    for gap in gaps:
        marketplace = str(gap.get("marketplace") or "general")
        field = str(gap.get("field") or gap.get("label") or "").strip()
        if not field:
            continue
        key = field_id({"marketplace": marketplace, "field": field})
        if key in accepted:
            continue
        error = str(gap.get("error") or "").strip().casefold()
        if error not in SOFT_GAP_ERRORS:
            needs_model.append(gap)
            continue
        value = str(gap.get("expected") or "").strip()
        if not value:
            value = listing_value_for_field(listing, marketplace, field)
        if not value and field_lookup_key(field) == "size":
            value = str((listing or {}).get("size") or "").strip()
        patch_value: object = value
        if not value and marketplace.lower() == "ebay" and field_lookup_key(field) == "season":
            from vendoo_studio.models.ebay_fields import infer_ebay_season
            patch_value = infer_ebay_season(listing)
            value = str(patch_value)
        if not value and marketplace.lower() == "ebay":
            from vendoo_studio.models.ebay_fields import (
                EBAY_OPTIONAL_DNA_LOOKUPS,
                ebay_optional_raw,
                ensure_ebay_category_optionals,
            )
            from vendoo_studio.models.listing_values import DNA_VALUE
            ensure_ebay_category_optionals(listing)
            value = listing_value_for_field(listing, marketplace, field)
            patch_value = value
            lookup = field_lookup_key(field)
            if not value and lookup in EBAY_OPTIONAL_DNA_LOOKUPS:
                ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
                raw = None
                for key in (
                    "mpn", "upc", "character", "characterFamily", "strapType",
                    "theme", "performanceActivity", "accents", "countryOfOrigin", "sleeveType",
                    "personalizationInstructions",
                ):
                    if field_lookup_key(key) == lookup:
                        raw = ebay_optional_raw(ebay, key)
                        break
                if raw is not None and str(raw).strip():
                    patch_value = raw
                    value = str(raw).strip()
                else:
                    patch_value = DNA_VALUE
                    value = DNA_VALUE
        if not value and marketplace.lower() == "etsy":
            from vendoo_studio.models.ebay_fields import ebay_optional_raw
            from vendoo_studio.models.etsy_fields import (
                ETSY_OPTIONAL_DNA_LOOKUPS,
                ensure_etsy_category_optionals,
            )
            from vendoo_studio.models.listing_values import DNA_VALUE
            ensure_etsy_category_optionals(listing)
            value = listing_value_for_field(listing, marketplace, field)
            patch_value = value
            lookup = field_lookup_key(field)
            if not value and lookup in {"pattern", "fabric pattern"}:
                etsy = listing.get("etsy_specifics") if isinstance(listing.get("etsy_specifics"), dict) else {}
                raw = ebay_optional_raw(etsy, "fabricPattern") or ebay_optional_raw(etsy, "pattern")
                if raw is not None and str(raw).strip():
                    patch_value = raw
                    value = str(raw).strip()
            if not value and lookup in ETSY_OPTIONAL_DNA_LOOKUPS:
                etsy = listing.get("etsy_specifics") if isinstance(listing.get("etsy_specifics"), dict) else {}
                raw = None
                for dna_key in ("graphic", "collarStyle", "holiday", "occasion", "sustainability"):
                    if field_lookup_key(dna_key) == lookup:
                        raw = ebay_optional_raw(etsy, dna_key)
                        break
                if raw is not None and str(raw).strip():
                    patch_value = raw
                    value = str(raw).strip()
                else:
                    patch_value = DNA_VALUE
                    value = DNA_VALUE
        if not value and marketplace.lower() == "depop":
            from vendoo_studio.models.depop_fields import (
                DEPOP_OPTIONAL_DNA_LOOKUPS,
                ensure_depop_category_optionals,
            )
            from vendoo_studio.models.listing_values import DNA_VALUE
            ensure_depop_category_optionals(listing)
            value = listing_value_for_field(listing, marketplace, field)
            patch_value = value
            lookup = field_lookup_key(field)
            if not value and lookup in {"style", "occasion", "material"}:
                depop = listing.get("depop_specifics") if isinstance(listing.get("depop_specifics"), dict) else {}
                raw = depop.get("style" if lookup == "style" else "occasion" if lookup == "occasion" else "material")
                if isinstance(raw, list) and raw:
                    patch_value = raw
                    value = ", ".join(str(item) for item in raw)
                elif raw not in (None, ""):
                    patch_value = raw
                    value = str(raw).strip()
            if not value and lookup in DEPOP_OPTIONAL_DNA_LOOKUPS:
                patch_value = DNA_VALUE
                value = DNA_VALUE
        # An unlisted brand is Depop "Other" / Mercari "No Brand/Not sure" — never a
        # question for the model, which must not invent a brand anyway.
        brand_fallback = ""
        if field_lookup_key(field) == "brand" and brand_missing_from_options(gap, value):
            brand_fallback = brand_fallback_for(marketplace)
            if brand_fallback:
                patch_value = brand_fallback
                value = brand_fallback
        if not value:
            needs_model.append(gap)
            continue
        # Draft already shows this value (or the mapped display form) — no write.
        # An unverified Depop/Mercari brand is the exception: only the live
        # dropdown can say whether the stored string is a real option.
        if not brand_fallback and not brand_needs_live_check(marketplace, gap, value) and (
            gap_already_has_value(gap, patch_value) or gap_already_has_value(gap, value)
        ):
            continue
        if (key, str(value)) in tried:
            needs_model.append(gap)
            continue
        options = gap.get("options") or []
        labels = {
            str(option.get("label")) if isinstance(option, dict) else str(option)
            for option in options
        }
        # Mercari's no-brand answer is a checkbox, so it is never in the brand options.
        if gap.get("options_complete") and labels and not brand_fallback:
            check_values = patch_value if isinstance(patch_value, list) else [patch_value]
            if any(str(item) not in labels for item in check_values):
                needs_model.append(gap)
                continue
        accepted.add(key)
        ready.append({
            "marketplace": marketplace,
            "field": field,
            "selector": gap.get("selector") or "",
            "value": patch_value,
        })
    return ready, needs_model


def drop_noop_gaps(db: Session, job, gaps: list[dict], listing: dict) -> list[dict]:
    """Remove gaps that already match on Vendoo or were filled with the same value this job."""
    kept: list[dict] = []
    for gap in gaps:
        marketplace = str(gap.get("marketplace") or "general")
        field = str(gap.get("field") or gap.get("label") or "").strip()
        value = gap.get("expected") or listing_value_for_field(listing, marketplace, field)
        # A Depop/Mercari brand the option list does not vouch for still needs the
        # filler, even though the draft reads back the value the API stored.
        live_brand_check = brand_needs_live_check(marketplace, gap, value)
        if live_brand_check and brand_live_check_done(db, job, marketplace):
            continue
        if not live_brand_check and gap_already_has_value(gap, value):
            continue
        if prior_fill_covers_empty_gap(db, job, gap, value):
            log.info(
                "skipping refill for %s/%s — fill log already wrote the same value",
                marketplace,
                field,
            )
            continue
        kept.append(gap)
    return kept


def adopt_observed_draft_values(
    listing: dict,
    verification: dict,
    *,
    prefer_listing: bool,
) -> tuple[dict, list[dict]]:
    """Trust non-empty Vendoo draft values that differ from the listing JSON.

    When the seller just edited the right-hand Studio form (`user_form`), keep
    listing values and fill Vendoo instead. Otherwise adopt the saved draft so
    cascaded marketplace fields are not fought and rewritten.
    """
    if prefer_listing or not isinstance(listing, dict):
        return listing, []
    patches: list[dict] = []
    schema = verification.get("schema") or {}
    for marketplace, section in schema.items():
        for field in section.get("fields") or []:
            label = str(field.get("label") or "")
            if not label or field_out_of_scope(marketplace, label):
                continue
            if field_lookup_key(label) == "category":
                continue
            observed = field.get("value")
            empty = observed is None or observed == "" or observed == []
            if empty:
                continue
            error = str(field.get("error") or "").strip()
            if error and error.casefold() not in {"", "saved value differs"}:
                continue
            expected = listing_value_for_field(listing, marketplace, label)
            matches_expected = None
            if expected and values_equal(field.get("expected_input"), expected):
                expected = str(field.get("expected") or expected)
                matches_expected = field.get("matches_expected")
            if matches_expected is True:
                continue
            if expected and values_equal(observed, expected):
                continue
            if matches_expected is False or (expected and not values_equal(observed, expected)):
                patches.append({
                    "marketplace": marketplace,
                    "field": label,
                    "value": _stringify_observed(observed),
                })
    if not patches:
        return listing, []
    return write_values_into_listing(listing, patches), patches


def review_fields(verification: dict, listing: dict) -> list[dict]:
    """An empty snapshot can never prove completeness."""
    schema = verification.get("schema") or {}
    gaps = []
    for marketplace, section in schema.items():
        for field in section.get("fields") or []:
            label = str(field.get("label") or "")
            if not label or field_out_of_scope(marketplace, label):
                continue
            observed = field.get("value")
            listing_expected = listing_value_for_field(listing, marketplace, label)
            browser_input = field.get("expected_input")
            browser_mapped = field.get("expected")
            matches_expected = None
            compare_expected = listing_expected
            if listing_expected and browser_input is not None and values_equal(browser_input, listing_expected):
                compare_expected = str(browser_mapped or listing_expected)
                matches_expected = field.get("matches_expected")
            empty = observed is None or observed == "" or observed == []
            error = str(field.get("error") or "")
            # A stored Depop/Mercari brand is not proof the marketplace lists it.
            brand_unverified = brand_needs_live_check(marketplace, field, listing_expected)
            # Draft already shows the intended value — do not schedule another fill.
            if not empty and not error and not brand_unverified and matches_expected is not False:
                if matches_expected is True:
                    continue
                if compare_expected and values_equal(observed, compare_expected):
                    continue
                if listing_expected and values_equal(observed, listing_expected):
                    continue
                if (
                    browser_mapped not in (None, "")
                    and values_equal(observed, browser_mapped)
                    and browser_input is not None
                    and listing_expected
                    and values_equal(browser_input, listing_expected)
                ):
                    continue
            # Depop "Other" / Mercari "No Brand/Not sure" are the answers for a brand
            # the marketplace does not list — not a gap to fill again.
            if brand_fallback_in_place(marketplace, field, observed, listing_expected, section.get("fields")):
                continue
            # A browser comparison also handles chips, booleans and numeric formatting.
            if empty or error or brand_unverified or matches_expected is False or (
                matches_expected is None and compare_expected and not values_equal(observed, compare_expected)
            ):
                gaps.append({
                    **field,
                    "marketplace": marketplace,
                    "field": label,
                    "expected": listing_expected,
                    "mapped_expected": browser_mapped,
                    "observed": observed,
                    "error": error or ("Empty field" if empty else "Saved value differs"),
                })
    return gaps
