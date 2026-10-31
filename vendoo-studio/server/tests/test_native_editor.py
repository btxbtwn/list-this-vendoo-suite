"""The direct editor reads catalogs without starting jobs or touching live listings."""
from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vendoo_studio.database import Base, get_db, load_models
from vendoo_studio.main import app
from vendoo_studio.repositories.queries import ConversationRepo, JobRepo, ListingRepo
from vendoo_studio.services import native_editor, marketplace_schemas, ebay_listings
from vendoo_studio.services.listing_result import ListingProblem
from vendoo_studio.services.vendoo_import import merge_notes


class NativeEditorTest(unittest.TestCase):
    def test_chat_reads_real_native_catalogs_and_saves_an_optional_field_without_a_job(self):
        import asyncio
        import json

        from vendoo_studio.services.chat_forms import forms_prompt
        from vendoo_studio.services.chat_listing import apply_listing_payload

        snapshot = {**self.listing, "direct_category_ids": {"depop": "menswear_jeans"}}
        ListingRepo(self.db).save_revision(self.conv.id, snapshot, "category_analysis")
        before = len(JobRepo(self.db).list_by_conversation(self.conv.id))
        with patch("vendoo_studio.services.chat_forms.get_selected_marketplaces", return_value=["poshmark", "depop"]), \
             patch("vendoo_studio.services.chat_forms.vinted_browser.category_rows", return_value=[{"title": "Jeans"}]):
            data = json.loads(asyncio.run(forms_prompt(self.db, self.conv.id)).split('\n')[-1])
        posh = {row["path"]: row for row in data["poshmark"]["fields"]}
        depop = {row["path"]: row for row in data["depop"]["fields"]}
        self.assertEqual(posh["direct_category_ids.poshmark"]["options_lookup"]["count"], 747)
        self.assertEqual(depop["direct_category_ids.depop"]["options_lookup"]["count"], 281)
        self.assertIn("Cotton", depop["depop_specifics.attributes.material"]["options"])
        _, saved = apply_listing_payload(self.db, self.conv.id, json.dumps({"fields": [
            {"path": "depop_specifics.attributes.material", "value": ["Cotton"]},
        ]}))
        self.assertTrue(saved)
        latest = ListingRepo(self.db).get_revisions(self.conv.id)[0].listing_json
        self.assertEqual(latest["depop_specifics"]["attributes"]["material"], ["Cotton"])
        self.assertEqual(len(JobRepo(self.db).list_by_conversation(self.conv.id)), before)
        self.bridge.assert_not_called()

    def test_mercari_override_keeps_the_saved_form_valid_through_posting_preparation(self):
        from vendoo_studio.services import direct_preflight, native_contract

        listing = copy.deepcopy(self.listing)
        listing["mercari_specifics"] = {"brand": "Anne Klein", "condition": "3"}
        form = {"category_id": "", "page_labels": True, "fields": [
            {"path": "mercari_specifics.brand", "label": "Brand", "options": []},
            {"path": "mercari_specifics.condition", "label": "Condition", "options": []},
        ]}
        listing[native_contract.KEY] = native_contract.capture(listing, {"mercari": form}, ["mercari"])
        revision = ListingRepo(self.db).save_revision(self.conv.id, listing, "native_schema")
        answer = self.client.get(f"{self.url}/mercari/form?revision_id={revision.id}")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(next(row for row in answer.json()["fields"]
                              if row["path"] == "mercari_specifics.brand")["value"], "Anne Klein")
        snapshot = direct_preflight.prepare(self.db, self.conv, listing, "mercari")
        self.assertEqual(native_contract.gaps(snapshot, "mercari"), [])
        self.bridge.assert_not_called()

    def test_fresh_poshmark_form_and_generation_choices_work_with_chrome_closed(self):
        import asyncio

        from vendoo_studio.services.native_field_fill import load_forms

        with patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)):
            answer = self.client.get(f"{self.url}/poshmark/form")
            generation_forms = asyncio.run(load_forms(self.db, self.conv.id, {"poshmark"}))
        self.assertEqual(answer.status_code, 200, answer.text)
        fields = {row["path"]: row for row in answer.json()["fields"]}
        self.assertEqual(len(fields["direct_category_ids.poshmark"]["options"]), 747)
        self.assertIn("poshmark_specifics.inventoryRows", fields)
        self.assertIn("poshmark", generation_forms)
        self.bridge.assert_not_called()

    def test_fresh_depop_form_and_generation_choices_work_with_chrome_closed(self):
        import asyncio

        from vendoo_studio.services.native_field_fill import load_forms

        snapshot = {**self.listing, "direct_category_ids": {"depop": "menswear_jeans"}}
        revision = ListingRepo(self.db).save_revision(self.conv.id, snapshot, "category_analysis")
        with patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)):
            answer = self.client.get(f"{self.url}/depop/form")
            generation_forms = asyncio.run(load_forms(self.db, self.conv.id, {"depop"}))
        self.assertEqual(answer.status_code, 200, answer.text)
        fields = {row["path"]: row for row in answer.json()["fields"]}
        self.assertEqual(len(fields["direct_category_ids.depop"]["option_values"]), 281)
        self.assertIn("Cotton", fields["depop_specifics.attributes.material"]["options"])
        self.assertIn('32"', fields["depop_specifics.size"]["options"])
        self.assertEqual(generation_forms["depop"]["category_id"], "menswear_jeans")
        self.assertEqual(ListingRepo(self.db).get_current(self.conv.id).current_revision_id, revision.id)
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])
        self.bridge.assert_not_called()

    def test_saved_forms_load_with_chrome_closed_and_current_values(self):
        from vendoo_studio.services import native_contract

        for market in ("ebay",):
            with self.subTest(market=market):
                snapshot = copy.deepcopy(self.listing)
                snapshot[f"{market}_specifics"] = {"material": "cotton", "description": "Edited description"}
                form = {"marketplace": market, "native": True, "known": True, "page_labels": True,
                        "category_id": snapshot["direct_category_ids"].get(market, ""), "fields": [
                    {"path": f"{market}_specifics.material", "label": "Material", "section": "Details",
                     "width": "half", "selection_only": True, "options": ["Cotton"],
                     "option_values": {"Cotton": "cotton"}, "value": "old"},
                    {"path": f"{market}_specifics.description", "label": "Description", "section": "Details"},
                    {"path": "price", "label": "Price", "section": "Pricing", "input_type": "number"},
                ]}
                snapshot[native_contract.KEY] = native_contract.capture(snapshot, {market: form}, [market])
                revision = ListingRepo(self.db).save_revision(self.conv.id, snapshot, "native_schema")
                before = copy.deepcopy(revision.listing_json)
                with patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)):
                    answer = self.client.get(f"{self.url}/{market}/form?revision_id={revision.id}")
                self.assertEqual(answer.status_code, 200, answer.text)
                result = answer.json()
                self.assertTrue(result["page_labels"])
                rows = result["fields"]
                self.assertEqual([row["value"] for row in rows], ["cotton", "Edited description", 20])
                self.assertEqual(rows[0]["section"], "Details")
                self.assertEqual(rows[0]["width"], "half")
                self.assertEqual(rows[0]["option_values"], {"Cotton": "cotton"})
                self.assertEqual(ListingRepo(self.db).get_current(self.conv.id).current_revision_id, revision.id)
                self.assertEqual(revision.listing_json, before)
                self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])
                self.bridge.assert_not_called()

    def test_saved_form_survives_the_category_path_posting_prepares(self):
        from vendoo_studio.services import native_contract

        snapshot = copy.deepcopy(self.listing)
        snapshot.update(title="Chase Authentics XL Y2K Tony Stewart #20 NASCAR T-Shirt Black Straight Cut",
                        category_path="Clothing, Shoes & Accessories > Men > Men's Clothing > Shirts & T-Shirts",
                        ebay_specifics={"condition": "3000"})
        form = {"marketplace": "ebay", "native": True, "known": True, "page_labels": True, "category_id": "15687",
                "fields": [
                    {"path": "ebay_specifics.condition", "label": "Item condition", "options": ["Pre-Owned - Good"],
                     "option_values": {"Pre-Owned - Good": "3000"}},
                    {"path": "ebay_specifics.brand", "label": "Brand", "options": ["Nike"],
                     "option_values": {"Nike": "Nike"}},
                ]}
        snapshot[native_contract.KEY] = native_contract.capture(snapshot, {"ebay": form}, ["ebay"])
        revision = ListingRepo(self.db).save_revision(self.conv.id, snapshot, "native_schema")
        answer = self.client.get(f"{self.url}/ebay/form?revision_id={revision.id}")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["marketplace"], "ebay")
        self.bridge.assert_not_called()

    def test_ebay_form_opens_when_general_condition_matches_its_saved_native_id(self):
        from vendoo_studio.services import native_contract

        snapshot = copy.deepcopy(self.listing)
        snapshot["ebay_specifics"] = {"Condition": "3000"}
        form = {"marketplace": "ebay", "native": True, "known": True, "page_labels": True,
                "category_id": "15687", "fields": [
                    {"path": "ebay_specifics.Condition", "label": "Item condition",
                     "options": ["Pre-owned - Good", "Pre-owned - Excellent"],
                     "option_values": {"Pre-owned - Good": "3000", "Pre-owned - Excellent": "2990"}},
                ]}
        snapshot[native_contract.KEY] = native_contract.capture(snapshot, {"ebay": form}, ["ebay"])
        snapshot["ebay_specifics"].pop("Condition")
        revision = ListingRepo(self.db).save_revision(self.conv.id, snapshot, "native_schema")
        answer = self.client.get(f"{self.url}/ebay/form?revision_id={revision.id}")
        self.assertEqual(answer.status_code, 200, answer.text)
        self.assertEqual(answer.json()["marketplace"], "ebay")
        self.assertEqual(ListingRepo(self.db).get_current(self.conv.id).current_revision_id, revision.id)
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])
        self.bridge.assert_not_called()

    def test_saved_form_with_changed_category_does_not_show_old_choices_or_contact_chrome(self):
        from vendoo_studio.services import native_contract

        snapshot = copy.deepcopy(self.listing)
        form = {"category_id": "men/shirts", "fields": [
            {"path": "mercari_specifics.nativeSizeId", "label": "Size", "options": ["L"]}]}
        snapshot[native_contract.KEY] = native_contract.capture(snapshot, {"mercari": form}, ["mercari"])
        snapshot["direct_category_ids"]["mercari"] = "men/shoes"
        ListingRepo(self.db).save_revision(self.conv.id, snapshot, "native_schema")
        answer = self.client.get(f"{self.url}/mercari/form")
        self.assertEqual(answer.status_code, 200)
        self.assertFalse(answer.json()["known"])
        self.assertNotIn("L", [choice for row in answer.json()["fields"]
                               if row["path"] == "mercari_specifics.nativeSizeId" for choice in row["options"]])
        self.bridge.assert_not_called()

    def setUp(self):
        load_models()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.conv = ConversationRepo(self.db).create(title="Private native form test")
        self.listing = {"title": "Nike L Tee", "description": "Details", "brand": "Nike", "size": "L", "price": 20,
                        "condition": "Pre-Owned - Good", "direct_category_ids": {"ebay": "15687", "poshmark": "men/shirts"}}
        self.rev = ListingRepo(self.db).save_revision(self.conv.id, self.listing, "test")
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.url = f"/api/conversations/{self.conv.id}/native-marketplaces"
        self.enterContext(patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=True)))
        self.bridge = self.enterContext(patch("vendoo_studio.services.browser_bridge.request", new_callable=AsyncMock))
        self.bridge.return_value = {"ok": True, "form": {"marketplace": "poshmark", "native": True, "known": True, "fields": []}}
        self.sellwild = self.enterContext(patch("vendoo_studio.services.sellwild_browser.account_choices", return_value={"ship_from": None, "coupons": [], "default_parcel": ""}))
        self.prepared = []
        prepare = native_editor.direct_preflight.prepare

        def record_prepared(*args, **kwargs):
            result = prepare(*args, **kwargs)
            self.prepared.append(result)
            return result

        self.enterContext(patch.object(native_editor.direct_preflight, "prepare", side_effect=record_prepared))

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.db.close()
        self.engine.dispose()

    def test_form_read_uses_posting_snapshot_and_does_not_save_or_launch(self):
        self.conv.notes = merge_notes(self.conv.notes, {"cog": "3.65", "packageDimensions": "13x10x3", "sku": "SKU1"})
        self.db.commit()
        before = copy.deepcopy(self.rev.listing_json)
        answer = self.client.get(f"{self.url}/poshmark/form?revision_id={self.rev.id}")
        self.assertEqual(answer.status_code, 200, answer.text)
        payload = {"listing": self.prepared[-1]}
        self.bridge.assert_not_called()
        self.assertEqual(payload["listing"]["cost"], 3.65)
        self.assertEqual(payload["listing"]["package_dimensions_in"], "13x10x3")
        self.assertEqual(payload["listing"]["sku"], "SKU1")
        self.assertNotIn("confirm", payload)
        self.assertEqual(ListingRepo(self.db).get_current(self.conv.id).current_revision_id, self.rev.id)
        self.assertEqual(ListingRepo(self.db).get_revision(self.rev.id).listing_json, before)
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])

    def test_stale_revision_and_disconnected_chrome_do_not_fall_back_to_vendoo(self):
        stale = self.client.get(f"{self.url}/poshmark/form?revision_id=old")
        self.assertEqual(stale.status_code, 409)
        self.bridge.assert_not_called()
        with patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)):
            answer = self.client.get(f"{self.url}/mercari/form")
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.json()["known"])
        self.bridge.assert_not_called()

    def test_fresh_mercari_form_and_generation_choices_work_with_chrome_closed(self):
        import asyncio
        from vendoo_studio.services.native_field_fill import load_forms

        with patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)):
            answer = self.client.get(f"{self.url}/mercari/form")
            generation_forms = asyncio.run(load_forms(self.db, self.conv.id, {"mercari"}))
        self.assertEqual(answer.status_code, 200, answer.text)
        fields = {row["path"]: row for row in answer.json()["fields"]}
        self.assertIn("Nike", fields["mercari_specifics.brand"]["options"])
        self.assertIn("Women > Maternity > Sweaters", fields["direct_category_ids.mercari"]["options"])
        self.assertIn("mercari", generation_forms)
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])
        self.bridge.assert_not_called()

    def test_native_choices_survive_form_save_and_posting_preparation(self):
        submitted = {**self.listing, "poshmark_specifics": {"sizeSetId": "native-group", "nativeSizeId": "XL", "smartSell": {"enabled": False}},
                     "depop_specifics": {"nativeSizeId": "123", "attributes": {"bottom-fit": ["straight"]}},
                     "mercari_specifics": {"nativeSizeId": "168"}}
        answer = self.client.put(f"/api/conversations/{self.conv.id}/listing", json={"expected_revision_id": ConversationRepo(self.db).current_revision_id(self.conv.id) or "", "listing": submitted})
        self.assertEqual(answer.status_code, 200, answer.text)
        self.client.get(f"{self.url}/poshmark/form")
        snapshot = self.prepared[-1]
        self.assertEqual(snapshot["poshmark_specifics"]["nativeSizeId"], "XL")
        self.assertEqual(snapshot["poshmark_specifics"]["sizeSetId"], "native-group")
        self.assertIs(snapshot["poshmark_specifics"]["smartSell"]["enabled"], False)
        self.assertEqual(snapshot["depop_specifics"]["attributes"], {"bottom-fit": ["straight"]})
        self.assertEqual(snapshot["depop_specifics"]["nativeSizeId"], "123")
        self.assertEqual(snapshot["mercari_specifics"]["nativeSizeId"], "168")

    def test_sellwild_form_is_native_and_has_no_ignored_brand_or_quantity(self):
        answer = self.client.get(f"{self.url}/sellwild/form")
        self.assertEqual(answer.status_code, 200, answer.text)
        form = answer.json()
        self.assertTrue(form["native"])
        fields = {row["path"]: row for row in form["fields"]}
        self.assertNotIn("brand", fields)
        self.assertNotIn("quantity", fields)
        self.assertNotIn("locked", fields["sellwild_specifics.nativeCategoryId"])
        self.assertTrue(fields["sellwild_specifics.nativeCategoryId"]["selection_only"])
        self.assertIn("246", fields["sellwild_specifics.nativeCategoryId"]["option_values"].values())
        self.assertFalse(fields["sellwild_specifics.description"]["required"])
        self.assertEqual(fields["sellwild_specifics.title"]["value"], "Nike L Tee")
        self.assertEqual(fields["sellwild_specifics.description"]["value"], "Details")
        # Account metadata comes from Anteroom, even with Chrome connected.
        self.sellwild.assert_called_once()
        self.bridge.assert_not_called()

    def test_sellwild_form_follows_the_sell_page_sections_and_order(self):
        answer = self.client.get(f"{self.url}/sellwild/form")
        self.assertEqual(answer.status_code, 200, answer.text)
        rows = answer.json()["fields"]
        self.assertEqual((rows[0]["input_type"], rows[0]["help"]), ("photos", "Please add Photos of your Listing. Max 20."))
        self.assertEqual([(row.get("section"), row["label"]) for row in rows], [
            ("", ""), ("Add a Title", "What are you selling? (Required)"), ("Name Your Price (USD)", "Price"),
            ("Name Your Price (USD)", "Sellwild Fee"), ("Name Your Price (USD)", "You Earn"),
            ("Name Your Price (USD)", "Sell it faster with a discount"),
            ("Add Details", "Describe your item (Optional)"), ("Add Details", "Category"), ("Add Details", "Condition"),
            ("Item Shipping", "Shipping From"),
            ("Item Shipping", "Package"), ("Item Shipping", "Weight (lbs)"), ("Item Shipping", "Height (in)"),
            ("Item Shipping", "Width (in)"), ("Item Shipping", "Depth (in)"),
        ])
        fields = {row["label"]: row for row in rows}
        self.assertEqual(fields["Price"]["min_value"], 5)
        category = fields["Category"]
        # The picker's order: groups and their categories by Sellwild's sort order. Pets > Adoption is hidden.
        self.assertEqual(category["options"][:3], ["Vehicles | Cars", "Vehicles | Electric Cars", "Vehicles | SUVs"])
        self.assertNotIn("206", category["option_values"].values())
        self.assertEqual(fields["Package"]["options"][:6], [
            "Custom Package Dimensions", "Small Flat Rate Box", "Medium Flat Rate Box 1", "Medium Flat Rate Box 2",
            "Large Flat Rate Box", "Flat Rate Envelope (12.5 × 9.5 × 0.75 in)"])
        self.assertEqual(fields["Package"]["options"][-2:], ["Soft Pack (poly mailer)", "Irregular Parcel (4 × 4 × 4 in)"])
        self.assertEqual(fields["Package"]["option_groups"]["Flat Rate Envelope (12.5 × 9.5 × 0.75 in)"], "Add other packaging")
        self.assertNotIn("Small Flat Rate Box", fields["Package"]["option_groups"])
        self.assertEqual(fields["Sell it faster with a discount"]["input_type"], "note")
        self.assertEqual(fields["Sellwild Fee"]["help"], "$2.00. Sellwild fee is 10% of sold price.")
        self.assertTrue(answer.json()["page_labels"])

    def test_sellwild_sign_in_is_explicit_and_never_starts_a_listing_job(self):
        with patch("vendoo_studio.services.sellwild_browser.connect", return_value={"ok": True}) as connect:
            self.assertEqual(self.client.post(f"{self.url}/sellwild/connect").json(), {"ok": True})
            connect.assert_called_once()
            answer = self.client.post("/api/conversations/missing/native-marketplaces/sellwild/connect")
            self.assertEqual(answer.status_code, 404)
            connect.assert_called_once()
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])
        self.bridge.assert_not_called()

    def test_sellwild_reloads_account_choices_instead_of_reusing_a_saved_form(self):
        from vendoo_studio.services import native_contract

        form = native_editor.sellwild_form(self.listing, self.conv.id, self.db, coupons=[])
        snapshot = copy.deepcopy(self.listing)
        snapshot[native_contract.KEY] = native_contract.capture(snapshot, {"sellwild": form}, ["sellwild"])
        revision = ListingRepo(self.db).save_revision(self.conv.id, snapshot, "native_schema")
        self.sellwild.return_value = {"ship_from": "Seller address", "default_parcel": "USPS_SoftPack",
                                     "coupons": [{"id": 117, "name": "25OFF", "discountType": "percentage", "discountValue": 25}]}
        with patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)):
            answer = self.client.get(f"{self.url}/sellwild/form?revision_id={revision.id}")
        fields = {row["label"]: row for row in answer.json()["fields"]}
        self.assertEqual(fields["Shipping From"]["value"], "Seller address")
        self.assertEqual(fields["Sell it faster with a discount"]["options"], ["25% 25OFF"])
        self.assertEqual(ListingRepo(self.db).get_current(self.conv.id).current_revision_id, revision.id)
        self.assertEqual(JobRepo(self.db).list_by_conversation(self.conv.id), [])
        self.bridge.assert_not_called()

    def test_sellwild_reports_account_connection_separately_from_missing_choices(self):
        for unavailable, connected in [([], True), (["coupons"], True), (["address", "parcel", "coupons"], False)]:
            with self.subTest(unavailable=unavailable):
                self.sellwild.return_value = {"ship_from": None, "default_parcel": "", "coupons": [],
                                             "unavailable": unavailable}
                response = self.client.get(f"{self.url}/sellwild/form")
                self.assertEqual(response.status_code, 200)
                self.assertIs(response.json()["account_connected"], connected)
                if connected:
                    self.assertNotIn("Sign in", " ".join(response.json().get("notes", [])))

    def test_sellwild_discount_and_profile_package_follow_the_sell_page(self):
        self.sellwild.return_value = {"ship_from": "Pat Seller", "default_parcel": "USPS_SoftPack",
                                    "coupons": [{"id": 117, "name": "25OFF", "discountType": "percentage", "discountValue": 25}]}
        fields = {row["label"]: row for row in self.client.get(f"{self.url}/sellwild/form").json()["fields"]}
        discount = fields["Sell it faster with a discount"]
        self.assertEqual(discount["value"], [])
        self.assertEqual(discount["options"], ["25% 25OFF"])
        self.assertTrue(discount["multi"])
        self.assertEqual(fields["Package"]["value"], "USPS_SoftPack")
        saved = {**self.listing, "sellwild_specifics": {"parcelTemplate": "", "couponIds": ["117"]}}
        self.assertEqual(self.client.put(f"/api/conversations/{self.conv.id}/listing", json={"expected_revision_id": ConversationRepo(self.db).current_revision_id(self.conv.id) or "", "listing": saved}).status_code, 200)
        fields = {row["label"]: row for row in self.client.get(f"{self.url}/sellwild/form").json()["fields"]}
        self.assertEqual(fields["Package"]["value"], "")
        self.assertEqual(fields["Sell it faster with a discount"]["value"], ["117"])
        # Weight and the three sides share one row on the page.
        self.assertEqual({fields[label].get("width") for label in ("Weight (lbs)", "Height (in)", "Width (in)", "Depth (in)")},
                         {"quarter"})

    def test_sellwild_shipping_from_shows_the_address_card_without_chrome(self):
        card = "Pat Seller\n12 Example St\nSpringfield, IL, 62701\nUnited States of America"
        self.sellwild.return_value = {"ship_from": card, "coupons": [], "default_parcel": ""}
        row = next(row for row in self.client.get(f"{self.url}/sellwild/form").json()["fields"] if row["label"] == "Shipping From")
        self.assertEqual((row["value"], row["locked"], row["section"], row.get("help")), (card, True, "Item Shipping", None))
        self.sellwild.return_value = {"ship_from": "", "coupons": [], "default_parcel": ""}
        row = next(row for row in self.client.get(f"{self.url}/sellwild/form").json()["fields"] if row["label"] == "Shipping From")
        self.assertEqual((row["value"], row["help"]), ("", "Add a Shipping From address in Sellwild's Address Book."))
        self.sellwild.return_value = {"ship_from": None, "coupons": [], "default_parcel": ""}
        with patch("vendoo_studio.services.extension_connection.extension_manager", SimpleNamespace(connected=False)):
            row = next(row for row in self.client.get(f"{self.url}/sellwild/form").json()["fields"] if row["label"] == "Shipping From")
        self.assertEqual(row["help"], "Sign in to Sellwild in Anteroom, then reload choices to show your address.")

    def test_sellwild_weight_and_sides_are_typed_on_the_sellwild_tab(self):
        from vendoo_studio.services.sellwild_listing import package_pounds, package_sides

        submitted = {**self.listing, "weight_lb": 1, "weight_oz": 8, "package_dimensions_in": "10x8x4",
                     "sellwild_specifics": {"nativeCategoryId": "1", "parcelTemplate": ""}}
        self.assertEqual(self.client.put(f"/api/conversations/{self.conv.id}/listing", json={"expected_revision_id": ConversationRepo(self.db).current_revision_id(self.conv.id) or "", "listing": submitted}).status_code, 200)
        fields = {row["label"]: row for row in self.client.get(f"{self.url}/sellwild/form").json()["fields"]}
        # They start from Item Details and can be changed here, as on Sellwild's page.
        self.assertEqual([fields[label]["value"] for label in ("Weight (lbs)", "Height (in)", "Width (in)", "Depth (in)")],
                         [1.5, 4.0, 8.0, 10.0])
        self.assertFalse(any(fields[label].get("locked") for label in ("Weight (lbs)", "Depth (in)")))
        own = {**submitted, "sellwild_specifics": {"parcelTemplate": "", "package": {"weight": 2.25, "depth": 12, "width": 9, "height": 5}}}
        self.assertEqual(package_pounds(own), 2.25)
        self.assertEqual(package_sides(own), [12.0, 9.0, 5.0])
        # An incomplete box on the tab falls back to Item Details.
        partial = {**submitted, "sellwild_specifics": {"parcelTemplate": "", "package": {"depth": 12}}}
        self.assertEqual(package_sides(partial), [10.0, 8.0, 4.0])

    def test_sellwild_vehicle_form_has_vehicle_information_and_no_package(self):
        submitted = {**self.listing, "sellwild_specifics": {"nativeCategoryId": "43", "vin": "1HGCM82633A004352"}}
        self.assertEqual(self.client.put(f"/api/conversations/{self.conv.id}/listing", json={"expected_revision_id": ConversationRepo(self.db).current_revision_id(self.conv.id) or "", "listing": submitted}).status_code, 200)
        rows = self.client.get(f"{self.url}/sellwild/form").json()["fields"]
        self.assertEqual([(row.get("section"), row["label"]) for row in rows][-3:], [
            ("Vehicle Information", "Vehicle Identification Number"), ("Vehicle Information", "Mileage"),
            ("Vehicle Shipping", "Shipping From")])
        self.assertNotIn("Package", [row["label"] for row in rows])

    def test_direct_depop_attribute_edits_survive_generated_style_padding(self):
        self.bridge.return_value = {"ok": True, "form": {"marketplace": "depop", "native": True, "fields": []}}
        submitted = {**self.listing, "depop_specifics": {
            "style": ["cute"], "age": [], "source": [],
        }}
        answer = self.client.put(f"/api/conversations/{self.conv.id}/listing", json={"expected_revision_id": ConversationRepo(self.db).current_revision_id(self.conv.id) or "", "listing": submitted})
        self.assertEqual(answer.status_code, 200, answer.text)
        response = self.client.get(f"{self.url}/depop/form")
        self.assertEqual(response.status_code, 200, response.text)
        fields = {row["path"]: row for row in response.json()["fields"]}
        self.assertEqual(fields["depop_specifics.style"]["value"], ["cute"])
        self.assertEqual(fields["depop_specifics.age"]["value"], [])
        self.assertEqual(fields["depop_specifics.source"]["value"], [])
        self.bridge.assert_not_called()

    def test_seller_original_price_survives_snapshot_defaults(self):
        submitted = {**self.listing, "poshmark_specifics": {"originalPrice": 55}}
        response = self.client.put(f"/api/conversations/{self.conv.id}/listing", json={"expected_revision_id": ConversationRepo(self.db).current_revision_id(self.conv.id) or "", "listing": submitted})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.get(f"{self.url}/poshmark/form")
        self.assertEqual(self.prepared[-1]["poshmark_specifics"]["originalPrice"], 55)

    def test_clearing_existing_depop_age_and_source_persists(self):
        previous = {**self.listing, "depop_specifics": {"style": ["Casual", "Retro", "Minimalist"], "age": "Modern", "source": "Preloved"}}
        ListingRepo(self.db).save_revision(self.conv.id, previous, "test")
        submitted = {**previous, "quantity": 3, "depop_specifics": {"style": ["casual", "retro"], "age": [], "source": []}}
        response = self.client.put(f"/api/conversations/{self.conv.id}/listing", json={"expected_revision_id": ConversationRepo(self.db).current_revision_id(self.conv.id) or "", "listing": submitted})
        self.assertEqual(response.status_code, 200, response.text)
        revision = ListingRepo(self.db).get_revision(ListingRepo(self.db).get_current(self.conv.id).current_revision_id)
        self.assertEqual(revision.listing_json["depop_specifics"]["age"], [])
        saved = self.client.get(f"/api/conversations/{self.conv.id}/listing").json()["listing"]
        self.assertEqual(saved["depop_specifics"]["age"], [])
        self.assertEqual(saved["depop_specifics"]["source"], [])
        self.assertEqual(saved["quantity"], 3)


class NativeEbayFieldsTest(unittest.IsolatedAsyncioTestCase):
    async def test_category_search_keeps_the_breadcrumb_in_root_to_leaf_order(self):
        from vendoo_studio.services.ebay_workspace import read

        client = SimpleNamespace(request=AsyncMock(return_value={"categorySuggestions": [{
            "category": {"categoryId": "15709", "categoryName": "Athletic Shoes"},
            "categoryTreeNodeAncestors": [{"categoryName": "Men’s Shoes"}, {"categoryName": "Men"}, {"categoryName": "Clothing"}],
        }]}))
        result = await read(client, "categories", query="mens sneakers")
        self.assertEqual(result["rows"][0]["subtitle"], "Clothing › Men › Men’s Shoes")
        self.assertEqual(result["rows"][0]["id"], "15709")

    async def test_ebay_form_follows_the_create_listing_page(self):
        """eBay's Create listing page for Men's Jeans (11483), read 2026-10-27, and its Taxonomy tiers on 9 clothing leaves."""
        def aspect(name, required=False, usage="OPTIONAL", mode="free_text", values=()):
            return {"id": name, "name": name, "required": required, "usage": usage, "mode": mode, "multi": False,
                    "max_values": None, "max_length": None, "values": [{"id": v, "label": v} for v in values]}
        rows = [
            {"id": "condition", "name": "Condition", "required": True, "multi": False, "mode": "selection",
             "values": [{"id": "3000", "label": "Pre-owned - Good"}]},
            aspect("Brand", True, "RECOMMENDED"), aspect("Size", True, "RECOMMENDED", values=("30", "32")),
            aspect("Type", usage="RECOMMENDED", mode="selection", values=("Jeans",)),
            aspect("Rise"), aspect("Personalize", mode="selection", values=("Yes", "No")), aspect("Season"),
            aspect("Personalization Instructions"), aspect("Department", True, "RECOMMENDED", "selection", ("Men",)),
        ]
        listing = {"direct_category_ids": {"ebay": "11483"}, "condition": "Good", "price": 30,
                   "ebay_specifics": {"returnPolicyId": "r2"}}
        from vendoo_studio.services import ebay_listings
        profiles = {"payment": [{"id": "p1", "title": "eBay Payments"}],
                    "fulfillment": [{"id": "f1", "title": "Ground"}, {"id": "f2", "title": "Free"}],
                    "return": [{"id": "r1", "title": "No returns"}, {"id": "r2", "title": "30 days"}],
                    "locations": [{"id": "home", "title": "Home"}]}
        with patch.object(marketplace_schemas, "fields", new=AsyncMock(return_value=rows)), \
                patch.object(ebay_listings, "listing_profiles", new=AsyncMock(return_value=profiles)), \
                patch.object(native_editor, "_ebay_format_fields", new=AsyncMock(return_value=[
                    native_editor.field("ebay_specifics.listingFormat", "Format", "FIXED_PRICE")])), \
                patch.object(native_editor, "_ebay_variations_field", new=AsyncMock(return_value=[])):
            form = await native_editor.ebay_form(listing)
        sections = []
        for row in form["fields"]:
            if not sections or sections[-1][0] != row["section"]:
                sections.append((row["section"], []))
            sections[-1][1].append(row["label"])
        self.assertEqual(sections, [
            ("Photos & Video", [""]),
            ("Title", ["Item title", "Subtitle", "Custom label (SKU)"]),
            ("Item category", ["Category", "Second category"]),
            ("Store category", ["First category", "Second category"]),
            # Required, then recommended, then the rest, each in eBay's order; instructions follow Personalize.
            ("Item specifics: Required", ["Brand", "Size", "Department"]),
            ("Item specifics: Additional (optional)", ["Type", "Rise", "Personalize", "Personalization Instructions",
                                                       "Season", "UPC", "Custom item specific", "Custom detail"]),
            ("Condition", ["Item condition", "Condition description"]),
            ("Description", ["Item description"]),
            ("Pricing", ["Format", "Item price", "Quantity", "Payment policy", "Allow offers (optional)", "Minimum offer",
                         "Auto accept", "Schedule your listing", "Listing start time", "Sales tax", "Your cost",
                         "Quantity in lot", "Private listing"]),
            ("Shipping", ["Shipping policy", "Package weight (lbs.)", "Package weight (oz.)", "Package dimensions (in.)",
                          "Irregular package"]),
            ("Preferences", ["Item location", "Return policy"]),
            ("Charity", ["Charity", "Percentage"]),
        ])
        # What eBay's page keeps behind its buttons.
        self.assertEqual({(row["label"], row["reveal"]) for row in form["fields"] if row.get("reveal")}, {
            ("Subtitle", "See title options"), ("Custom label (SKU)", "See title options"), ("Rise", "Show more"),
            ("Personalize", "Show more"), ("Personalization Instructions", "Show more"), ("Season", "Show more"),
            ("UPC", "Show more"), ("Custom item specific", "Add custom item specific"),
            ("Custom detail", "Add custom item specific"),
            ("Your cost", "See pricing options"), ("Quantity in lot", "See pricing options"),
            ("Private listing", "See pricing options")})
        by_path = {row["path"]: row for row in form["fields"]}
        # The listing's own choice, else the account's only one; several and no choice: none picked.
        self.assertEqual(by_path["ebay_specifics.returnPolicyId"]["value"], "r2")
        self.assertEqual(by_path["ebay_specifics.paymentPolicyId"]["value"], "p1")
        self.assertEqual(by_path["ebay_specifics.fulfillmentPolicyId"]["value"], "")
        self.assertEqual(by_path["ebay_specifics.merchantLocationKey"]["option_values"], {"Home": "home"})
        fields = {row["label"]: row for row in form["fields"]}
        # eBay's page offers only its listed sizes, though Taxonomy calls Size free text.
        self.assertTrue(fields["Size"]["selection_only"])
        self.assertFalse(fields["Rise"]["selection_only"])
        self.assertEqual([row["label"] for row in form["fields"] if row.get("width") == "half"], [
            "Category", "Second category", "First category", "Second category", "Custom item specific", "Custom detail",
            "Minimum offer", "Auto accept", "Listing start time", "Your cost", "Quantity in lot", "Package dimensions (in.)",
            "Charity", "Percentage"])
        # Weight in lbs. and oz. and the dimensions share one row, as on eBay's page.
        self.assertEqual([label for label, row in fields.items() if row.get("width") == "quarter"], [
            "Package weight (lbs.)", "Package weight (oz.)"])
        self.assertEqual(fields["Allow offers (optional)"]["help"],
                         "Interested buyers can send an offer for this item. You can accept, counter, or decline.")

    async def test_ebay_auction_rows_follow_the_page(self):
        from vendoo_studio.services.ebay_client import EbayClient

        auction = {"FIXED_PRICE": ["GTC"], "AUCTION": ["DAYS_7"]}
        listing = {"direct_category_ids": {"ebay": "11483"}, "ebay_specifics": {"listingFormat": "AUCTION"}}
        with patch.object(EbayClient, "connect", new=AsyncMock()), \
                patch.object(marketplace_schemas, "ebay_listing_types", new=AsyncMock(return_value=auction)):
            rows = await native_editor._ebay_format_fields(listing, "11483", listing["ebay_specifics"])
        self.assertEqual([(row["label"], row.get("width")) for row in rows], [
            ("Format", None), ("Auction duration", None), ("Starting bid", "half"), ("Buy It Now (optional)", "half"),
            ("Reserve price (optional) — fees apply", "half")])
        self.assertEqual(rows[3]["help"], "Minimum: 30% more than starting bid")

    async def test_ebay_form_keeps_native_ids_limits_and_multiselects(self):
        rows = [{"id": "condition", "name": "Condition", "required": True, "multi": False, "mode": "selection",
                 "values": [{"id": "1000", "label": "New"}, {"id": "3000", "label": "Pre-owned"}]},
                {"id": "Season", "name": "Season", "required": False, "multi": True, "mode": "selection", "max_length": 65,
                 "usage": "RECOMMENDED", "values": [{"id": "Spring", "label": "Spring"}, {"id": "Summer", "label": "Summer"}]},
                {"id": "Theme", "name": "Theme", "required": False, "multi": False, "mode": "free_text", "usage": "OPTIONAL",
                 "values": []}]
        listing = {"direct_category_ids": {"ebay": "15687"}, "condition": "Good", "ebay_specifics": {"season": ["Spring", "Summer"]}}
        with patch.object(marketplace_schemas, "fields", new=AsyncMock(return_value=rows)):
            form = await native_editor.ebay_form(listing)
        fields = {row["path"]: row for row in form["fields"]}
        self.assertEqual(fields["ebay_specifics.Condition"]["value"], "3000")
        self.assertEqual(fields["ebay_specifics.Condition"]["option_values"]["New"], "1000")
        self.assertEqual(fields["ebay_specifics.Season"]["value"], ["Spring", "Summer"])
        self.assertTrue(fields["ebay_specifics.Season"]["multi"])
        self.assertEqual(fields["ebay_specifics.Season"]["max_length"], 65)
        self.assertTrue(fields["ebay_specifics.Season"]["category_specific"])
        self.assertNotIn("on_form", fields["ebay_specifics.Season"])
        self.assertNotIn("on_form", fields["ebay_specifics.Theme"])
        self.assertTrue(fields["ebay_specifics.Theme"]["category_specific"])
        self.assertNotIn("category_specific", fields["ebay_specifics.Condition"])
        self.assertEqual(fields["ebay_specifics.bestOffer.enabled"]["input_type"], "boolean")
        self.assertNotIn("locked", fields["ebay_specifics.conditionDescription"])
        self.assertEqual(fields["ebay_specifics.conditionDescription"]["max_length"], 1000)
        self.assertEqual(ebay_listings.ebay_condition({"ebay_specifics": {"condition": "1000"}}), "NEW")
        self.assertEqual(fields["sku"]["value"], "")
        # eBay's photo area comes first, as on its listing page.
        photos = form["fields"][0]
        self.assertEqual((photos["path"], photos["input_type"], photos["section"]), ("marketplace_photos.ebay", "photos", "Photos & Video"))
        self.assertTrue(photos["help"].startswith("You can add up to 24 photos and a 1-minute video."))

    async def test_ebay_format_choices_come_from_ebays_category_rules(self):
        from vendoo_studio.services.ebay_client import EbayClient

        rows = [{"id": "condition", "name": "Condition", "required": True, "multi": False, "mode": "selection", "values": []}]
        auction = {"FIXED_PRICE": ["GTC"], "AUCTION": ["DAYS_3", "DAYS_7"]}
        listing = {"direct_category_ids": {"ebay": "15687"}, "condition": "Good",
                   "ebay_specifics": {"listingFormat": "AUCTION", "auctionStartPrice": "9.99"}}
        from vendoo_studio.services import ebay_listings
        profiles = AsyncMock(return_value={"payment": [], "fulfillment": [], "return": [], "locations": []})
        with patch.object(marketplace_schemas, "fields", new=AsyncMock(return_value=rows)), \
                patch.object(EbayClient, "connect", new=AsyncMock()), \
                patch.object(ebay_listings, "listing_profiles", new=profiles), \
                patch.object(marketplace_schemas, "ebay_listing_types", new=AsyncMock(return_value=auction)):
            form = await native_editor.ebay_form(listing)
            fixed = await native_editor.ebay_form({**listing, "ebay_specifics": {}})
        fields = {row["path"]: row for row in form["fields"]}
        self.assertEqual(fields["ebay_specifics.listingFormat"]["options"], ["Auction", "Buy It Now"])
        self.assertEqual(fields["ebay_specifics.listingFormat"]["option_values"], {"Buy It Now": "FIXED_PRICE", "Auction": "AUCTION"})
        self.assertEqual(fields["ebay_specifics.listingFormat"]["value"], "AUCTION")
        self.assertIn("ebay_specifics.auctionStartPrice", fields["ebay_specifics.listingFormat"]["clears"])
        self.assertEqual(fields["ebay_specifics.listingDuration"]["option_values"],
                         {"Good 'Til Cancelled": "GTC", "3 days": "DAYS_3", "7 days": "DAYS_7"})
        self.assertFalse(fields["ebay_specifics.listingDuration"].get("locked"))
        self.assertEqual(fields["ebay_specifics.listingDuration"]["value"], "DAYS_7")
        self.assertEqual(fields["ebay_specifics.auctionStartPrice"]["value"], "9.99")
        self.assertIn("ebay_specifics.auctionBuyItNow", fields)
        self.assertIn("ebay_specifics.bestOffer.enabled", fields)
        fixed_fields = {row["path"]: row for row in fixed["fields"]}
        self.assertEqual(set(fields), set(fixed_fields))
        self.assertEqual(fixed_fields["ebay_specifics.listingFormat"]["value"], "FIXED_PRICE")
        self.assertEqual(fixed_fields["ebay_specifics.listingDuration"]["value"], "GTC")
        self.assertIn("ebay_specifics.auctionStartPrice", fixed_fields)
        self.assertIn("ebay_specifics.bestOffer.enabled", fixed_fields)
        # No auction in the category: Auction is not offered.
        with patch.object(marketplace_schemas, "fields", new=AsyncMock(return_value=rows)), \
                patch.object(EbayClient, "connect", new=AsyncMock()), \
                patch.object(ebay_listings, "listing_profiles", new=profiles), \
                patch.object(marketplace_schemas, "ebay_listing_types", new=AsyncMock(return_value={"FIXED_PRICE": ["GTC"]})):
            plain = await native_editor.ebay_form({**listing, "ebay_specifics": {}})
        choice = next(row for row in plain["fields"] if row["path"] == "ebay_specifics.listingFormat")
        self.assertEqual(choice["options"], ["Buy It Now"])
        self.assertNotIn("help", choice)
        # eBay's page shows no duration for Buy It Now.
        self.assertNotIn("ebay_specifics.listingDuration", {row["path"] for row in plain["fields"]})

    async def test_a_generated_ebay_inventory_key_is_not_shown_as_the_sku(self):
        rows = [{"id": "condition", "name": "Condition", "required": True, "multi": False, "mode": "selection", "values": []}]
        with patch.object(marketplace_schemas, "fields", new=AsyncMock(return_value=rows)):
            generated = await native_editor.ebay_form({"direct_category_ids": {"ebay": "15687"}, "sku": "ar-abc123", "condition": "Good"})
            typed = await native_editor.ebay_form({"direct_category_ids": {"ebay": "15687"}, "sku": "HAT-1", "condition": "Good"})
        generated_sku = next(row for row in generated["fields"] if row["path"] == "sku")
        typed_sku = next(row for row in typed["fields"] if row["path"] == "sku")
        self.assertEqual(generated_sku["value"], "")
        self.assertEqual(typed_sku["value"], "HAT-1")

    async def test_ebay_size_and_department_are_editable_and_filled_from_general(self):
        rows = [
            {"id": "Size", "name": "Size", "required": True, "multi": False, "mode": "selection",
             "values": [{"id": "M", "label": "M"}, {"id": "L", "label": "L"}]},
            {"id": "Department", "name": "Department", "required": False, "multi": False, "mode": "free",
             "values": []},
        ]
        listing = {
            "direct_category_ids": {"ebay": "15687"},
            "title": "General title",
            "description": "General description",
            "condition": "Good",
            "ebay_specifics": {"title": "eBay title"},
        }
        with patch.object(marketplace_schemas, "fields", new=AsyncMock(return_value=rows)):
            form = await native_editor.ebay_form(listing)
        fields = {row["path"]: row for row in form["fields"]}
        for path in ("ebay_specifics.Size", "ebay_specifics.Department"):
            row = fields[path]
            self.assertFalse(row.get("locked"))
            self.assertNotIn("help", row)
        self.assertEqual(fields["ebay_specifics.title"]["value"], "eBay title")
        self.assertEqual(fields["ebay_specifics.description"]["value"], "General description")
        self.assertFalse(fields["ebay_specifics.title"].get("locked"))

    def test_ebay_size_follows_size_type_from_taxonomys_parent_constraints(self):
        size = {
            "name": "Size", "required": True, "multi": False, "mode": "selection", "max_length": None,
            "values": [
                {"id": "M", "label": "M", "constraints": [{
                    "applicableForLocalizedAspectName": "Size Type",
                    "applicableForLocalizedAspectValues": ["Regular"],
                }]},
                {"id": "M", "label": "M", "constraints": [{
                    "applicableForLocalizedAspectName": "Size Type",
                    "applicableForLocalizedAspectValues": ["Petites"],
                }]},
                {"id": "S", "label": "S", "constraints": [{
                    "applicableForLocalizedAspectName": "Size Type",
                    "applicableForLocalizedAspectValues": ["Regular"],
                }]},
            ],
        }
        size_type = {"name": "Size Type", "required": True, "multi": False, "mode": "selection", "max_length": None,
                     "values": [{"id": "Regular", "label": "Regular"}, {"id": "Petites", "label": "Petites"}]}
        stored = marketplace_schemas._ebay_field({
            "localizedAspectName": "Size", "aspectConstraint": {"aspectMode": "SELECTION_ONLY", "aspectRequired": True},
            "aspectValues": [{"localizedValue": "M", "valueConstraints": size["values"][0]["constraints"]},
                             {"localizedValue": "M", "valueConstraints": size["values"][1]["constraints"]}]})
        self.assertEqual(stored["values"][0]["constraints"], [{"parentName": "Size Type", "parentValues": ["Regular"]}])
        self.assertEqual(marketplace_schemas.constraints_by_label(stored["values"])["M"],
                         [{"parentName": "Size Type", "parentValues": ["Regular", "Petites"]}])
        matched = ebay_listings._match_aspects([size_type, size], {"Size": ["M"], "Size Type": ["Regular"]})
        self.assertEqual(matched["Size"], ["M"])
        self.assertEqual(matched["Size Type"], ["Regular"])
        listing = {"size": "S", "sizeType": "Petites", "ebay_specifics": {"size": "M", "sizeType": "Regular"}}
        aspects = ebay_listings.ebay_aspects(listing, {})
        self.assertEqual(aspects["Size"], ["M"])
        self.assertEqual(aspects["Size Type"], ["Regular"])
        with self.assertRaises(ListingProblem) as caught:
            ebay_listings._match_aspects([size_type, size], {"Size": ["S"], "Size Type": ["Petites"]})
        self.assertIn("Choose Size for the selected parent aspects", str(caught.exception))

    def test_ebay_parent_constraints_are_preserved_and_enforced_before_posting(self):
        field = marketplace_schemas._ebay_field({"localizedAspectName": "Model", "aspectConstraint": {"aspectMode": "SELECTION_ONLY"},
            "aspectValues": [{"localizedValue": "Air Max", "valueConstraints": [{"parentName": "Brand", "parentValues": ["Nike"]}]},
                             {"localizedValue": "Gazelle", "valueConstraints": [{"parentName": "Brand", "parentValues": ["Adidas"]}]}]})
        self.assertEqual([v["label"] for v in marketplace_schemas.aspect_options(field, {"Brand": ["Nike"]})], ["Air Max"])
        with self.assertRaises(ListingProblem) as caught:
            ebay_listings._match_aspects([field], {"Brand": ["Adidas"], "Model": ["Air Max"]})
        self.assertIn("selected parent aspects", str(caught.exception))

    def test_an_explicitly_cleared_ebay_aspect_does_not_reappear_from_general_values(self):
        listing = {"brand": "Nike", "material": "Cotton", "ebay_specifics": {"brand": "", "material": []}}
        self.assertNotIn("Brand", ebay_listings.ebay_aspects(listing, {"overrides": {"brand": "Nike"}}))
        self.assertNotIn("Material", ebay_listings.ebay_aspects(listing, {}))
