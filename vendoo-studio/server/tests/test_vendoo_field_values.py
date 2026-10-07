from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from vendoo_studio.models.ebay_fields import ebay_size_for_type
from vendoo_studio.routes.extension import _build_registry_selectors
from vendoo_studio.services.completion_gaps import deterministic_gap_patches
from vendoo_studio.services.listing_generate import propagate_general_size
from vendoo_studio.services.specifics_fill import fill_listing_specifics, specifics_gaps
from vendoo_studio.services.vendoo_api import build_vendoo_item, changed_fields
from vendoo_studio.services.vendoo_specifics import FieldSpec, encode_specific


def test_registry_payload_keeps_list_values_for_browser_selection():
    listing = {"tags": ["petite", "red"], "ebay_specifics": {
        "fabricType": ["Polyester"], "material": ["Polyester", "Spandex"],
    }}
    with patch("vendoo_studio.repositories.queries.RegistryRepo") as repo:
        repo.return_value.get_best_selectors.return_value = ["#field"]
        payload = _build_registry_selectors(listing, object(), ["ebay"])
    assert payload["ebay"]["fabricType"]["value"] == ["Polyester"]
    assert payload["ebay"]["material"]["value"] == ["Polyester", "Spandex"]
    assert payload["general"]["tags"]["value"] == ["petite", "red"]


def test_draft_repair_keeps_expected_list_values():
    patches, remaining = deterministic_gap_patches([{
        "marketplace": "ebay", "field": "Material", "error": "Empty field",
        "expected": ["Polyester", "Spandex"],
        "options": ["Polyester", "Spandex"], "options_complete": True,
    }], {})
    assert remaining == []
    assert patches[0]["value"] == ["Polyester", "Spandex"]


def test_fabric_type_resolves_single_option_and_material_keeps_chips():
    item, _ = build_vendoo_item({
        "marketplace_category_ids": {"ebay": "53159"},
        "ebay_specifics": {"fabricType": ["Polyester"], "material": ["Polyester", "Spandex"]},
    }, specifics={"ebay": {
        "Fabric Type": FieldSpec("Fabric Type", options={"poly": "Polyester"}),
        "Material": FieldSpec("Material", multi=True, options={"poly": "Polyester", "span": "Spandex"}),
    }})
    assert item["listings"]["ebay"]["categorySpecifics"] == {
        "53159_Fabric Type": "poly", "53159_Material": ["poly", "span"],
    }


@pytest.mark.parametrize("value", [["Polyester"], "Polyester", "['Polyester', 'Spandex']"])
def test_unsupported_fabric_type_needs_repair_even_for_creatable_select(value):
    spec = FieldSpec("Fabric Type", options={"knit": "Knit", "woven": "Woven"})
    assert encode_specific(spec, value) == ("", False)
    gaps = specifics_gaps({"ebay_specifics": {"fabricType": value}}, {"ebay": {spec.key: spec}})
    assert gaps[0]["field"] == "Fabric Type"
    assert gaps[0]["options"] == ["Knit", "Woven"]


def test_fabric_repair_replaces_literal_text_with_a_supported_option():
    fields = {"ebay": {"Fabric Type": FieldSpec("Fabric Type", options={"knit": "Knit"})}}

    async def reply(provider, *, listing, gaps, evidence):
        assert gaps[0]["rejected"] == "['Polyester', 'Spandex']"
        return [{"marketplace": "ebay", "field": "Fabric Type", "value": "Knit"}]

    with patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", reply):
        listing, gaps = asyncio.run(fill_listing_specifics({"ebay_specifics": {
            "fabricType": "['Polyester', 'Spandex']", "material": ["Polyester", "Spandex"],
        }}, fields, object()))
    assert gaps == []
    assert listing["ebay_specifics"]["fabricType"] == "Knit"
    assert listing["ebay_specifics"]["material"] == ["Polyester", "Spandex"]


@pytest.mark.parametrize(("size", "expected"), [
    ("L", "PL"), ("LP", "PL"), ("PL", "PL"), ("S", "PS"),
    ("XL", "PXL"), ("12", "12P"), ("12P", "12P"),
])
def test_ebay_petite_size_mapping(size, expected):
    assert ebay_size_for_type(size, "Petites") == expected
    assert ebay_size_for_type(size, "Regular") == size


def petite_listing():
    return {"size": "L", "marketplace_category_ids": {"ebay": "53159"},
            "ebay_specifics": {"sizeType": "Petites", "size": "L"}}


def petite_specs():
    return {"ebay": {
        "Size": FieldSpec("Size", required=True, selection_only=True, options={"L": "L", "PL": "PL"}),
        "Size Type": FieldSpec("Size Type", required=True, selection_only=True, options={"Petites": "Petites"}),
    }}


def test_size_sync_keeps_petite_pair_without_changing_general_size():
    listing = petite_listing()
    assert propagate_general_size(listing)
    assert listing["size"] == "L"
    assert listing["ebay_specifics"] == {"sizeType": "Petites", "size": "PL"}
    assert not propagate_general_size(listing)


def test_schema_preparation_and_saved_draft_update_keep_petite_pair():
    listing = petite_listing()
    prepared, gaps = asyncio.run(fill_listing_specifics(listing, petite_specs(), None))
    assert gaps == []
    assert prepared["ebay_specifics"]["size"] == "PL"
    assert listing["ebay_specifics"]["size"] == "L"
    # Encoding itself must also protect direct Send/Update callers.
    item, _ = build_vendoo_item(listing, specifics=petite_specs())
    fields = item["listings"]["ebay"]["categorySpecifics"]
    assert fields == {"53159_Size": "PL", "53159_Size Type": "Petites"}
    current = {"listings": {"ebay": {"categorySpecifics": {"53159_Size": "L"}}}}
    assert changed_fields(current, item)["listings.ebay.categorySpecifics.53159_Size"] == "PL"


def test_petite_size_absent_from_category_options_remains_a_gap():
    fields = petite_specs()
    fields["ebay"]["Size"].options = {"L": "L"}
    gaps = specifics_gaps(petite_listing(), fields)
    assert gaps[0]["field"] == "Size"
    assert gaps[0]["rejected"] == "PL"


def test_singular_general_petite_type_maps_to_ebay_petites():
    listing = petite_listing()
    listing["sizeType"] = "Petite"
    listing["ebay_specifics"] = {"size": "PL"}
    prepared, gaps = asyncio.run(fill_listing_specifics(listing, petite_specs(), None))
    assert gaps == []
    assert prepared["ebay_specifics"] == {"size": "PL", "sizeType": "Petites"}


def test_repairing_size_type_also_updates_size_to_the_petite_option():
    listing = petite_listing()
    listing["ebay_specifics"].pop("sizeType")

    async def reply(provider, *, listing, gaps, evidence):
        assert [gap["field"] for gap in gaps] == ["Size Type"]
        return [{"marketplace": "ebay", "field": "Size Type", "value": "Petites"}]

    with patch("vendoo_studio.services.listing_field_gaps._request_missing_field_values", reply):
        prepared, gaps = asyncio.run(fill_listing_specifics(listing, petite_specs(), object()))
    assert gaps == []
    assert prepared["ebay_specifics"] == {"size": "PL", "sizeType": "Petites"}


def test_learned_draft_shape_also_preserves_petite_size():
    item, _ = build_vendoo_item(petite_listing(), schema={"aspects": {"ebay": {
        "Size": "scalar", "Size Type": "scalar",
    }}})
    assert item["listings"]["ebay"]["categorySpecifics"]["53159_Size"] == "PL"
