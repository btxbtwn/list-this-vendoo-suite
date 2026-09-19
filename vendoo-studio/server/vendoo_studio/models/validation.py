from __future__ import annotations

import re
from functools import lru_cache

from pydantic import ValidationError

from vendoo_studio.models.depop_fields import (
    DEPOP_CATEGORY_OPTIONAL_KEYS,
    VALID_DEPOP_GROUPING,
    VALID_DEPOP_PARCEL,
    ensure_depop_category_optionals,
)
from vendoo_studio.models.ebay_fields import (
    EBAY_CATEGORY_OPTIONAL_KEYS,
    EBAY_FABRIC_WEIGHT_RE,
    EBAY_KEY_ALIASES,
    EBAY_OPTIONAL_DNA_KEYS,
    EBAY_OPTIONAL_EVIDENCE_KEYS,
    REQUIRED_EBAY_KEYS,
    ebay_optional_blank,
    ebay_optional_raw,
    ebay_season_parts,
    ensure_ebay_category_optionals,
    exact_ebay_season,
    infer_ebay_season,
    normalize_ebay_fabric_weight,
    normalize_ebay_season_value,
    promote_required_ebay_specifics,
)
from vendoo_studio.models.etsy_fields import (
    ETSY_CATEGORY_OPTIONAL_KEYS,
    ETSY_OPTIONAL_DNA_KEYS,
    VALID_ETSY_WHAT,
    VALID_ETSY_WHO,
    ensure_etsy_category_optionals,
    etsy_listing_type,
    etsy_what_raw,
    etsy_when_is_modern,
    etsy_when_is_vintage_or_handmade,
    etsy_when_options,
    etsy_when_raw,
    etsy_who_raw,
    is_etsy_digital_listing,
    resolve_etsy_when,
)
from vendoo_studio.models.listing_values import (
    DNA_VALUE,
    ValidationResult,
    add_issue,
    allowed_match,
    as_list,
    as_mapping,
    canonical_option,
    dedupe_schema_errors,
    evidence_unknown,
    text_value,
)
from vendoo_studio.models.schema import (
    PACKAGE_DIMS_PATTERN,
    VALID_DEPOP_AGE,
    VALID_DEPOP_MATERIAL,
    VALID_DEPOP_OCCASION,
    VALID_DEPOP_SOURCE,
    VALID_DEPOP_STYLE,
    ListingSchema,
)
from vendoo_studio.services.marketplaces import (
    FILLABLE_MARKETPLACES,
    get_selected_marketplaces,
)

TITLE_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "with", "for", "in", "on", "to",
})


def _title_tokens(title: str) -> list[str]:
    return [part for part in re.split(r"\s+", title.strip()) if part]


def _title_follows_formula(title: str, brand: str, size: str) -> bool:
    tokens = [token.lower() for token in _title_tokens(title)]
    if len(tokens) < 4:
        return False
    if brand:
        brand_tokens = [part.lower() for part in brand.split() if part]
        if tokens[:len(brand_tokens)] != brand_tokens:
            return False
        rest = tokens[len(brand_tokens):]
    else:
        rest = tokens
    if size and rest:
        size_token = size.lower()
        if rest[0] != size_token and size_token not in rest[:2]:
            return False
    meaningful = [token for token in tokens if token not in TITLE_STOPWORDS]
    return len(meaningful) >= 4


def _description_follows_formula(description: str) -> bool:
    from vendoo_studio.services.skill_formulas import description_formula_markers

    text = description.strip()
    if len(text) < 40 or "\n" not in text:
        return False
    lower = text.lower()
    return all(marker in lower for marker in description_formula_markers())


def _category_is_terminal(path: str) -> bool:
    parts = [part.strip() for part in re.split(r"\s*>\s*", path) if part.strip()]
    return len(parts) >= 4


def _department_matches_category(department: str, category_path: str) -> bool:
    dep = department.lower()
    path = category_path.lower()
    if not dep or not path:
        return True
    if "women" in dep and "men" in path and "women" not in path:
        return False
    if dep == "men" and "women" in path:
        return False
    return True


def ensure_poshmark_style_tags(listing: dict) -> bool:
    """Fill Poshmark style tags when empty so Additional Details is not blank."""
    if not isinstance(listing, dict):
        return False
    raw = listing.get("poshmark_specifics")
    if not isinstance(raw, dict):
        return False
    tags = as_list(raw.get("styleTags") or raw.get("style_tags"))
    if tags:
        return False
    depop = listing.get("depop_specifics") if isinstance(listing.get("depop_specifics"), dict) else {}
    ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
    candidates = [
        *as_list(depop.get("style")),
        text_value(ebay.get("style")),
        text_value(ebay.get("features")),
        "Casual",
    ]
    filled: list[str] = []
    for candidate in candidates:
        text = text_value(candidate)
        if text and text not in filled and text.casefold() != DNA_VALUE.casefold():
            filled.append(text)
        if len(filled) >= 3:
            break
    while len(filled) < 3:
        for fallback in ("Casual", "Retro", "Vintage"):
            if fallback not in filled:
                filled.append(fallback)
            if len(filled) >= 3:
                break
    posh = dict(raw)
    posh["styleTags"] = filled[:3]
    listing["poshmark_specifics"] = posh
    return True


def ensure_mercari_shipping_label(listing: dict) -> bool:
    if not isinstance(listing, dict):
        return False
    raw = listing.get("mercari_specifics")
    if not isinstance(raw, dict):
        return False
    if text_value(raw.get("shippingLabel") or raw.get("shipping_label")):
        return False
    mercari = dict(raw)
    mercari["shippingLabel"] = "USPS Ground Advantage / 1 - 7 days / $ 5.66 / 0.5 lb"
    listing["mercari_specifics"] = mercari
    return True


# Containers keep their own names — only leaf value keys are canonicalized.
KEY_CANONICAL_SKIP = frozenset({"category_specifics", "marketplace_specifics", "marketplaceSpecifics"})


def _squash_key(text: str) -> str:
    from vendoo_studio.services.fill_log import squash_field_key

    return squash_field_key(text)


@lru_cache(maxsize=1)
def _canonical_by_squash() -> dict[str, str]:
    """Known JSON keys indexed by their case/separator-free form."""
    from vendoo_studio.services.registry import LABEL_TO_JSON_KEY

    known: list[str] = [
        *ListingSchema.model_fields,
        *LABEL_TO_JSON_KEY.values(),
        *REQUIRED_EBAY_KEYS,
        *EBAY_CATEGORY_OPTIONAL_KEYS,
        *ETSY_CATEGORY_OPTIONAL_KEYS,
        *DEPOP_CATEGORY_OPTIONAL_KEYS,
    ]
    return {_squash_key(key): key for key in known if _squash_key(key)}


def _canonicalize_record_keys(record: dict, *, allowed: frozenset[str] | None = None) -> bool:
    """Rename keys that differ from the canonical JSON key only by case or separators.

    Heals listings where a gap fill wrote `sizetype` instead of `sizeType`, which reads
    as an empty required field even though the value is sitting in the JSON.
    """
    from vendoo_studio.services.fill_log import field_lookup_key
    from vendoo_studio.services.registry import label_to_json_key

    changed = False
    for key in list(record):
        if key in KEY_CANONICAL_SKIP:
            continue
        value = record[key]
        if isinstance(value, dict):
            continue
        squashed = _squash_key(key)
        known = _canonical_by_squash()
        # Keys the app reads may be reached through label normalization; anything else
        # is only renamed when it differs from its JSON key by case or separators alone.
        canonical = known.get(squashed) or known.get(_squash_key(field_lookup_key(key)))
        if not canonical:
            canonical = label_to_json_key(field_lookup_key(key))
            if not canonical or _squash_key(canonical) != squashed:
                continue
        if canonical == key:
            continue
        if allowed is not None and canonical not in allowed:
            continue
        # Same field under two spellings: the canonical value is the one everything reads.
        if ebay_optional_blank(record.get(canonical)):
            record[canonical] = value
        record.pop(key, None)
        changed = True
    return changed


def canonicalize_listing_keys(listing: dict) -> bool:
    if not isinstance(listing, dict):
        return False
    changed = _canonicalize_record_keys(listing, allowed=frozenset(ListingSchema.model_fields))
    for marketplace in FILLABLE_MARKETPLACES:
        specifics = listing.get(f"{marketplace}_specifics")
        if not isinstance(specifics, dict):
            continue
        if _canonicalize_record_keys(specifics):
            changed = True
        nested = specifics.get("category_specifics")
        if isinstance(nested, dict) and _canonicalize_record_keys(nested):
            changed = True
    if promote_required_ebay_specifics(listing):
        changed = True
    return changed


def normalize_listing_dropdowns(listing: dict) -> bool:
    """Rewrite stale Depop/Etsy dropdown values to the current Vendoo options."""
    if not isinstance(listing, dict):
        return False
    changed = canonicalize_listing_keys(listing)

    # Shipping weight often lands only under marketplace specifics — promote it.
    if "weight_lb" not in listing and "weight_oz" not in listing:
        ebay = listing.get("ebay_specifics") if isinstance(listing.get("ebay_specifics"), dict) else {}
        pounds = ebay.get("pounds") if isinstance(ebay, dict) else None
        ounces = ebay.get("ounces") if isinstance(ebay, dict) else None
        if pounds is None and ounces is None:
            for key in ("mercari_specifics", "etsy_specifics", "depop_specifics"):
                block = listing.get(key)
                if isinstance(block, dict):
                    if pounds is None and block.get("pounds") is not None:
                        pounds = block.get("pounds")
                    if ounces is None and block.get("ounces") is not None:
                        ounces = block.get("ounces")
        try:
            lb = int(pounds or 0)
            oz = int(ounces or 0)
        except (TypeError, ValueError):
            lb, oz = 0, 0
        if lb > 0 or oz > 0:
            listing["weight_lb"] = lb
            listing["weight_oz"] = oz
            changed = True

    ebay = listing.get("ebay_specifics")
    if isinstance(ebay, dict):
        raw_season = ebay.get("season")
        if raw_season in (None, "") and ebay.get("Season") not in (None, ""):
            raw_season = ebay.get("Season")
        missing = raw_season in (None, "", [], ()) and "season" not in ebay and "Season" not in ebay
        if missing:
            ebay = dict(ebay)
            ebay["season"] = infer_ebay_season(listing, ebay=ebay)
            ebay.pop("Season", None)
            listing["ebay_specifics"] = ebay
            changed = True
        else:
            normalized_season, season_changed = normalize_ebay_season_value(
                raw_season,
                listing=listing,
                ebay=ebay,
            )
            if season_changed or ("Season" in ebay and ebay.get("Season") != normalized_season):
                ebay = dict(ebay)
                ebay["season"] = (
                    infer_ebay_season(listing, ebay=ebay)
                    if normalized_season is None
                    else normalized_season
                )
                ebay.pop("Season", None)
                listing["ebay_specifics"] = ebay
                changed = True

    if ensure_ebay_category_optionals(listing):
        changed = True
    if ensure_etsy_category_optionals(listing):
        changed = True
    if ensure_depop_category_optionals(listing):
        changed = True
    if ensure_poshmark_style_tags(listing):
        changed = True
    if ensure_mercari_shipping_label(listing):
        changed = True

    depop = listing.get("depop_specifics")
    if isinstance(depop, dict):
        depop = dict(depop)
        depop_changed = False
        raw = text_value(depop.get("parcelSize") or depop.get("parcel_size"))
        canonical = canonical_option(raw, VALID_DEPOP_PARCEL) if raw else None
        if canonical and canonical != raw:
            depop["parcelSize"] = canonical
            if "parcel_size" in depop:
                depop["parcel_size"] = canonical
            depop_changed = True
        for key, allowed in (("source", VALID_DEPOP_SOURCE), ("age", VALID_DEPOP_AGE)):
            raw_value = text_value(depop.get(key))
            if not raw_value:
                continue
            hit = canonical_option(raw_value, allowed)
            if hit and hit != raw_value:
                depop[key] = hit
                depop_changed = True
        styles = as_list(depop.get("style"))
        mapped: list[str] = []
        had_invalid = False
        for style in styles:
            hit = canonical_option(style, VALID_DEPOP_STYLE)
            if hit:
                if hit not in mapped:
                    mapped.append(hit)
            elif str(style or "").strip():
                had_invalid = True
        if styles and had_invalid:
            if not mapped:
                mapped = ["Casual", "Retro", "Boho"]
            mapped = mapped[:3]
            if mapped != styles:
                depop["style"] = mapped
                depop_changed = True
        if depop_changed:
            listing["depop_specifics"] = depop
            changed = True

    etsy = listing.get("etsy_specifics")
    if isinstance(etsy, dict):
        etsy = dict(etsy)
        who = etsy_who_raw(etsy)
        what = etsy_what_raw(etsy)
        when_raw = etsy_when_raw(etsy, listing)
        if who and text_value(etsy.get("who_made")) != who:
            etsy["who_made"] = who
            changed = True
        if what and text_value(etsy.get("what_is")) != what:
            etsy["what_is"] = what
            changed = True
        canonical_when = resolve_etsy_when(when_raw, etsy_when_options()) if when_raw else ""
        if canonical_when and text_value(etsy.get("when_made")) != canonical_when:
            etsy["when_made"] = canonical_when
            if "whenMade" in etsy:
                etsy["whenMade"] = canonical_when
            changed = True
        listing["etsy_specifics"] = etsy

    return changed


def validate_listing(
    data: dict,
    required_photo_count: int | None = None,
    *,
    require_photos: bool = True,
    selected_marketplaces: list[str] | None = None,
) -> ValidationResult:
    result = ValidationResult(valid=True)
    payload = data if isinstance(data, dict) else {}
    normalize_listing_dropdowns(payload)
    selected = list(selected_marketplaces) if selected_marketplaces is not None else get_selected_marketplaces()
    selected_set = {item.lower() for item in selected}
    digital_listing = is_etsy_digital_listing(payload)

    schema_errors: list[dict[str, str]] = []
    try:
        ListingSchema.model_validate(payload)
    except ValidationError as exc:
        result.valid = False
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err["loc"])
            message = err["msg"]
            schema_errors.append({
                "field": field,
                "message": f"{field}: {message}" if field else message,
            })

    required_fields = [
        ("title", "Title is required"),
        ("description", "Description is required"),
        ("price", "Price is required"),
        ("brand", "Brand is required"),
        ("sku", "SKU is required"),
    ]
    if not digital_listing:
        required_fields.insert(4, ("size", "Size is required"))
    for field, message in required_fields:
        if field in {err["field"] for err in schema_errors}:
            continue
        value = payload.get(field)
        missing = value is None or (isinstance(value, str) and not value.strip())
        if missing:
            add_issue(result, field, message)

    for err in dedupe_schema_errors(schema_errors):
        field = err["field"]
        if field in {"title", "description", "price"} and any(item["field"] == field for item in result.errors):
            continue
        result.errors.append(err)

    title = text_value(payload.get("title"))
    description = text_value(payload.get("description"))
    brand = text_value(payload.get("brand"))
    size = text_value(payload.get("size") or payload.get("size_us"))
    if title and len(title) > 80 and not any(err["field"] == "title" for err in result.errors):
        add_issue(result, "title", "Title must be 80 characters or less")
    if not digital_listing:
        if title and brand and not _title_follows_formula(title, brand, size):
            add_issue(result, "title", "Title must follow Brand Size Vibe Item Color Fit")
        if description and not _description_follows_formula(description):
            add_issue(
                result,
                "description",
                "Description must use the physical-item formula, including Flaws and Measurements",
            )
    elif description and "instant download" not in description.lower() and "no physical item" not in description.lower():
        add_issue(
            result,
            "description",
            "Digital listings must state instant download and that no physical item will be shipped",
            warning=True,
        )

    if not digital_listing:
        if "weight_lb" not in payload and "weight_oz" not in payload:
            add_issue(result, "weight_oz", "Weight is required")
        else:
            try:
                pounds = int(payload.get("weight_lb") or 0)
                ounces = int(payload.get("weight_oz") or 0)
            except (TypeError, ValueError):
                pounds, ounces = 0, 0
            if pounds <= 0 and ounces <= 0:
                add_issue(result, "weight_oz", "Weight is required")

        package = text_value(payload.get("package_dimensions_in"))
        if package and not re.match(PACKAGE_DIMS_PATTERN, package, re.I):
            add_issue(result, "package_dimensions_in", "Package dimensions must use LxWxH inches, such as 13x10x3")
        elif not package:
            add_issue(result, "package_dimensions_in", "Package dimensions are required")
    else:
        package = text_value(payload.get("package_dimensions_in"))
        if package and not re.match(PACKAGE_DIMS_PATTERN, package, re.I):
            add_issue(result, "package_dimensions_in", "Package dimensions must use LxWxH inches, such as 13x10x3")

    category_path = text_value(payload.get("category_path"))
    if category_path and not _category_is_terminal(category_path):
        add_issue(result, "category_path", "Category must be a terminal Vendoo path")
    department = text_value(payload.get("department"))
    if department and category_path and not _department_matches_category(department, category_path):
        add_issue(result, "department", "Department does not match the selected category")

    if require_photos and required_photo_count is not None and required_photo_count == 0:
        add_issue(result, "photos", "At least one product photo is required")

    ebay = as_mapping(payload.get("ebay_specifics"))
    if payload.get("ebay_specifics") is not None and ebay is None:
        add_issue(result, "ebay_specifics", "eBay specifics must be an object")
        ebay = {}
    ebay = ebay or {}
    if "ebay" in selected_set:
        for key in REQUIRED_EBAY_KEYS:
            if not text_value(ebay.get(key)):
                add_issue(result, f"ebay_specifics.{key}", f"eBay field '{key}' is required")
        for alias, canonical in EBAY_KEY_ALIASES.items():
            if alias in ebay and canonical not in ebay:
                add_issue(result, f"ebay_specifics.{canonical}", f"eBay key '{alias}' must be '{canonical}'")
        season = ebay.get("season")
        season_parts = ebay_season_parts(season)
        if not season_parts or any(exact_ebay_season(part) is None for part in season_parts):
            add_issue(
                result,
                "ebay_specifics.season",
                "eBay Season must be Spring, Summer, Fall, and/or Winter",
            )
        for key in EBAY_CATEGORY_OPTIONAL_KEYS:
            if key == "season":
                continue
            value = ebay_optional_raw(ebay, key)
            if ebay_optional_blank(value):
                if key in EBAY_OPTIONAL_EVIDENCE_KEYS:
                    continue
                add_issue(
                    result,
                    f"ebay_specifics.{key}",
                    f"eBay optional '{key}' must be filled (or Does Not Apply only when it truly does not apply)",
                )
                continue
            text = text_value(value) if not isinstance(value, (list, tuple)) else ",".join(str(v) for v in value)
            is_dna = text.casefold() in {
                DNA_VALUE.casefold(), "n/a", "na", "none", "does not apply",
            }
            if is_dna and key not in EBAY_OPTIONAL_DNA_KEYS:
                add_issue(
                    result,
                    f"ebay_specifics.{key}",
                    (
                        "eBay Fabric Weight must be left blank unless a numeric value "
                        "(greater than 0, up to 1 decimal) is evidenced — never Does Not Apply"
                        if key == "fabricWeight"
                        else f"eBay '{key}' applies to this item — use a real value, not Does Not Apply"
                    ),
                )
                continue
            if key == "fabricWeight" and text:
                normalized, _ = normalize_ebay_fabric_weight(text)
                match = EBAY_FABRIC_WEIGHT_RE.fullmatch(text_value(normalized) or text)
                if not match or float(match.group(1)) <= 0:
                    add_issue(
                        result,
                        "ebay_specifics.fabricWeight",
                        "eBay Fabric Weight must be a number greater than 0 with at most 1 decimal place",
                    )
        ebay_size = text_value(ebay.get("size"))
        if size and ebay_size and ebay_size.lower() != size.lower():
            add_issue(result, "ebay_specifics.size", "eBay size must match the general size")
        care = text_value(ebay.get("garmentCare"))
        if care and evidence_unknown(description, "care tag is not shown", "garment care", "unverified"):
            if "unknown" in description.lower() or "not shown" in description.lower() or "unverified" in description.lower():
                add_issue(result, "ebay_specifics.garmentCare", "Do not invent garment care when the care tag is not shown")
        material = text_value(ebay.get("material") or ebay_optional_raw(ebay, "material"))
        if material and evidence_unknown(
            description,
            "material tag is not shown",
            "fiber composition is unknown",
            "material is unknown",
        ):
            add_issue(result, "ebay_specifics.material", "Do not invent material composition without tag evidence")
        elif not material:
            add_issue(
                result,
                "ebay_specifics.material",
                "Material evidence is missing. Keep material blank and state the gap in the description.",
                warning=True,
            )

    depop = as_mapping(payload.get("depop_specifics"))
    if payload.get("depop_specifics") is not None and depop is None:
        add_issue(result, "depop_specifics", "Depop specifics must be an object")
        depop = {}
    depop = depop or {}
    if "depop" in selected_set:
        source = text_value(depop.get("source"))
        if source and not allowed_match(source, VALID_DEPOP_SOURCE):
            add_issue(result, "depop_specifics.source", "Depop source is not a current dropdown value")
        elif not source:
            add_issue(result, "depop_specifics.source", "Depop source is required")
        age = text_value(depop.get("age"))
        if age and not allowed_match(age, VALID_DEPOP_AGE):
            add_issue(result, "depop_specifics.age", "Depop age is not a current dropdown value")
        elif not age:
            add_issue(result, "depop_specifics.age", "Depop age is required")
        styles = as_list(depop.get("style"))
        if not styles:
            add_issue(result, "depop_specifics.style", "Depop style tags are required")
        elif len(styles) > 3:
            add_issue(result, "depop_specifics.style", "Depop allows only 3 style tags")
        for style in styles:
            if not allowed_match(style, VALID_DEPOP_STYLE):
                add_issue(result, "depop_specifics.style", f"Depop style '{style}' is not a current dropdown value")
                break
        occasions = as_list(depop.get("occasion"))
        if not occasions:
            add_issue(result, "depop_specifics.occasion", "Depop occasion tags are required")
        for occasion in occasions:
            if not allowed_match(occasion, VALID_DEPOP_OCCASION):
                add_issue(result, "depop_specifics.occasion", f"Depop occasion '{occasion}' is not a current dropdown value")
                break
        parcel = text_value(depop.get("parcelSize") or depop.get("parcel_size"))
        if parcel and not allowed_match(parcel, VALID_DEPOP_PARCEL):
            add_issue(result, "depop_specifics.parcelSize", "Depop parcel size is not a current dropdown value")
        elif not parcel:
            add_issue(result, "depop_specifics.parcelSize", "Depop parcel size is required")
        grouping = text_value(depop.get("sizeGrouping") or depop.get("size_grouping"))
        size_type = text_value(payload.get("sizeType"))
        if grouping:
            if grouping.casefold() in {DNA_VALUE.casefold(), "n/a", "na", "none"}:
                pass
            elif grouping not in VALID_DEPOP_GROUPING:
                add_issue(result, "depop_specifics.sizeGrouping", "Regular items must not use a Depop size grouping")
            elif size_type.lower() == "regular":
                add_issue(result, "depop_specifics.sizeGrouping", "Regular items must not use a Depop size grouping")
        elif size_type.lower() in {"petite", "plus", "plus size", "tall", "maternity"}:
            add_issue(result, "depop_specifics.sizeGrouping", "Depop size grouping is required for non-regular sizing")
        materials = as_list(depop.get("material"))
        for material in materials:
            if material not in VALID_DEPOP_MATERIAL:
                add_issue(result, "depop_specifics.material", f"Depop material '{material}' is not a current dropdown value")
                break
        if not materials:
            add_issue(
                result,
                "depop_specifics.material",
                "Depop material evidence is missing. Keep material blank and state the gap in the description.",
                warning=True,
            )

    etsy = as_mapping(payload.get("etsy_specifics"))
    if payload.get("etsy_specifics") is not None and etsy is None:
        add_issue(result, "etsy_specifics", "Etsy specifics must be an object")
        etsy = {}
    etsy = etsy or {}
    if "etsy" in selected_set:
        who = etsy_who_raw(etsy)
        what = etsy_what_raw(etsy)
        if not who:
            add_issue(result, "etsy_specifics.who_made", "Etsy who-made is required")
        elif who not in VALID_ETSY_WHO:
            add_issue(result, "etsy_specifics.who_made", "Etsy who-made is not a current dropdown value")
        if not what:
            add_issue(result, "etsy_specifics.what_is", "Etsy what-is is required")
        elif what not in VALID_ETSY_WHAT:
            add_issue(result, "etsy_specifics.what_is", "Etsy what-is is not a current dropdown value")
        when_options = etsy_when_options()
        when = etsy_when_raw(etsy, payload)
        dropdown_when = resolve_etsy_when(when, when_options) if when else ""
        if dropdown_when and dropdown_when != when:
            etsy = dict(etsy)
            etsy["when_made"] = dropdown_when
            payload["etsy_specifics"] = etsy
            when = dropdown_when
        if not when:
            add_issue(result, "etsy_specifics.when_made", "Etsy when-made is required")
        tags = as_list(etsy.get("tags"))
        if len(tags) > 13:
            add_issue(result, "etsy_specifics.tags", "Etsy allows at most 13 tags")
        materials = as_list(etsy.get("materials"))
        if len(materials) > 10:
            add_issue(result, "etsy_specifics.materials", "Etsy allows at most 10 materials")
        handmade = who in {"I did", "A member of my shop"}
        vintage_or_eligible = etsy_when_is_vintage_or_handmade(dropdown_when, who, what)
        digital_item = "digital" in etsy_listing_type(etsy).lower() or "digital" in what.lower()
        commercial_maker = who in {"", "Another company or person"}
        modern_resale = commercial_maker and (not when or etsy_when_is_modern(dropdown_when))
        if modern_resale and not vintage_or_eligible and not handmade and not digital_item:
            add_issue(
                result,
                "etsy_specifics.when_made",
                "This modern mass-produced item is not Etsy eligible. Deselect Etsy or use a vintage, handmade, craft-supply, or digital listing.",
                warning=True,
            )
        if not digital_item:
            for key in ETSY_CATEGORY_OPTIONAL_KEYS:
                if key == "pattern":
                    # fabricPattern is the Vendoo fill key; pattern is an alias.
                    if not ebay_optional_blank(ebay_optional_raw(etsy, "fabricPattern")):
                        continue
                if key == "fabricPattern":
                    if not ebay_optional_blank(ebay_optional_raw(etsy, "pattern")):
                        continue
                value = ebay_optional_raw(etsy, key)
                if ebay_optional_blank(value):
                    add_issue(
                        result,
                        f"etsy_specifics.{key}",
                        f"Etsy optional '{key}' must be filled (or Does Not Apply only when it truly does not apply)",
                    )
                    continue
                text = text_value(value) if not isinstance(value, (list, tuple)) else ",".join(str(v) for v in value)
                is_dna = text.casefold() in {
                    DNA_VALUE.casefold(), "n/a", "na", "none", "does not apply", "----",
                }
                if is_dna and key not in ETSY_OPTIONAL_DNA_KEYS:
                    add_issue(
                        result,
                        f"etsy_specifics.{key}",
                        f"Etsy '{key}' applies to this item — use a real value, not Does Not Apply",
                    )

    return result
