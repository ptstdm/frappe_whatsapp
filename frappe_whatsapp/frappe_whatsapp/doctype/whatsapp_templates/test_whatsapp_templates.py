# Copyright (c) 2022, Shridhar Patil and Contributors
# See license.txt

import json
from unittest.mock import patch, MagicMock

import frappe
from frappe_whatsapp.testing import IntegrationTestCase


class TestWhatsAppTemplates(IntegrationTestCase):
    """Tests for WhatsApp Templates doctype."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_test_account()
        cls._ensure_second_test_account()

    @classmethod
    def _ensure_test_account(cls):
        if not frappe.db.exists("WhatsApp Account", "Test WA Tmpl Account"):
            account = frappe.get_doc({
                "doctype": "WhatsApp Account",
                "account_name": "Test WA Tmpl Account",
                "status": "Active",
                "url": "https://graph.facebook.com",
                "version": "v17.0",
                "phone_id": "tmpl_test_phone_id",
                "business_id": "tmpl_test_business_id",
                "app_id": "tmpl_test_app_id",
                "webhook_verify_token": "tmpl_test_verify_token",
                "is_default_incoming": 1,
                "is_default_outgoing": 1,
            })
            account.insert(ignore_permissions=True)
            frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture must be visible to later queries

    @classmethod
    def _ensure_second_test_account(cls):
        """A second active account on its own WhatsApp Business Account, for multi-account sync."""
        if not frappe.db.exists("WhatsApp Account", "Test WA Tmpl Account 2"):
            account = frappe.get_doc({
                "doctype": "WhatsApp Account",
                "account_name": "Test WA Tmpl Account 2",
                "status": "Active",
                "url": "https://graph.facebook.com",
                "version": "v17.0",
                "phone_id": "tmpl_test_phone_id_2",
                "business_id": "tmpl_test_business_id_2",
                "app_id": "tmpl_test_app_id_2",
                "webhook_verify_token": "tmpl_test_verify_token_2",
            })
            account.insert(ignore_permissions=True)
            frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture must be visible to later queries

    def setUp(self):
        # Set password within each test's transaction scope
        from frappe.utils.password import set_encrypted_password
        set_encrypted_password("WhatsApp Account", "Test WA Tmpl Account", "test_tmpl_token", "token")
        # Clear ALL defaults then set ours (db.set_value bypasses on_update hooks)
        frappe.db.sql("UPDATE `tabWhatsApp Account` SET is_default_outgoing=0, is_default_incoming=0")
        frappe.db.set_value("WhatsApp Account", "Test WA Tmpl Account", {
            "is_default_outgoing": 1,
            "is_default_incoming": 1,
        })

    def tearDown(self):
        # Reset the request-scoped flag set by the Meta error-surfacing tests.
        frappe.flags.integration_request = None
        # Use SQL-level delete to avoid triggering on_trash (which calls get_settings)
        frappe.db.delete("WhatsApp Templates", {"template_name": ["like", "test_tmpl_%"]})
        frappe.db.delete("WhatsApp Templates", {"template_name": ["like", "test_msg_template%"]})
        # Also delete child button rows: deleting the parent above does not cascade,
        # so without this they linger as orphans and get re-loaded when a later test
        # recreates a template with the same (reused) name.
        frappe.db.delete("WhatsApp Button", {"parent": ["like", "test_tmpl_%"]})
        frappe.db.delete("WhatsApp Button", {"parent": ["like", "test_msg_template%"]})
        frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture must be visible to later queries

    def _make_template_without_hooks(self, **kwargs):
        """Create a template directly in DB to avoid Meta API calls."""
        template_name = kwargs.get("template_name", "test_tmpl_basic")
        language_code = kwargs.get("language_code", "en")
        doc = frappe.get_doc({
            "doctype": "WhatsApp Templates",
            "template_name": template_name,
            "actual_name": template_name.lower().replace(" ", "_"),
            "template": kwargs.get("template", "Hello {{1}}"),
            "category": kwargs.get("category", "TRANSACTIONAL"),
            "language": kwargs.get("language", frappe.db.get_value("Language", {"language_code": "en"}) or "en"),
            "language_code": language_code,
            "whatsapp_account": kwargs.get("whatsapp_account", "Test WA Tmpl Account"),
            "status": kwargs.get("status", "APPROVED"),
            "id": kwargs.get("id", f"tmpl_id_{template_name}"),
            "header_type": kwargs.get("header_type", ""),
            "header": kwargs.get("header", ""),
            "footer": kwargs.get("footer", ""),
            "sample_values": kwargs.get("sample_values", ""),
        })
        doc.db_insert()
        frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture must be visible to later queries
        return frappe.get_doc("WhatsApp Templates", doc.name)

    def test_template_autoname(self):
        """Test template autoname format: template_name-language_code."""
        doc = self._make_template_without_hooks(template_name="test_tmpl_autoname")
        self.assertEqual(doc.name, "test_tmpl_autoname-en")

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_language_code_set_on_validate(self, mock_post):
        """Test language_code is derived from language field on validate."""
        mock_post.return_value = {}
        # Body has one variable, so give it one sample value (validate_sample_values).
        doc = self._make_template_without_hooks(template_name="test_tmpl_langcode", sample_values="John")
        doc.language_code = ""
        doc.language = frappe.db.get_value("Language", {"language_code": "en"}) or "en"
        doc.validate()
        self.assertTrue(len(doc.language_code) > 0)

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_new_template_name_includes_language_code(self, mock_post):
        """A template saved from the form (language_code not filled yet) is named {template_name}-{language_code}."""
        mock_post.return_value = {"id": "tmpl_name_lang_id", "status": "PENDING"}

        doc = frappe.get_doc({
            "doctype": "WhatsApp Templates",
            "template_name": "test_tmpl_name_lang",
            "template": "Hello",
            "category": "UTILITY",
            "language": frappe.db.get_value("Language", {"language_code": "en"}) or "en",
            "whatsapp_account": "Test WA Tmpl Account",
        })
        doc.insert(ignore_permissions=True)

        self.assertEqual(doc.language_code, "en")
        self.assertEqual(doc.name, "test_tmpl_name_lang-en")

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_same_template_name_in_two_languages(self, mock_post):
        """The same Template Label can be created once per language."""
        mock_post.return_value = {"id": "tmpl_two_lang_id", "status": "PENDING"}

        names = []
        for code in ("en", "hi"):
            doc = frappe.get_doc({
                "doctype": "WhatsApp Templates",
                "template_name": "test_tmpl_two_lang",
                "template": "Hello",
                "category": "UTILITY",
                "language": frappe.db.get_value("Language", {"language_code": code}) or code,
                "whatsapp_account": "Test WA Tmpl Account",
            })
            doc.insert(ignore_permissions=True)
            names.append(doc.name)

        self.assertEqual(names, ["test_tmpl_two_lang-en", "test_tmpl_two_lang-hi"])
        sent = [json.loads(c.kwargs["data"]) for c in mock_post.call_args_list]
        self.assertEqual([(d["name"], d["language"]) for d in sent], [("test_tmpl_two_lang", "en"), ("test_tmpl_two_lang", "hi")])

    def test_set_whatsapp_account_default(self):
        """Test whatsapp_account is set to default if missing."""
        doc = self._make_template_without_hooks(
            template_name="test_tmpl_default_acct",
            whatsapp_account=""
        )
        doc.whatsapp_account = ""
        doc.set_whatsapp_account()
        self.assertTrue(len(doc.whatsapp_account) > 0)

    def test_read_local_file_uses_file_doctype(self):
        """_read_local_file resolves through the File doctype, not raw paths."""
        doc = self._make_template_without_hooks(template_name="test_tmpl_path")

        mock_file = MagicMock()
        mock_file.get_content.return_value = b"binary-content"
        with patch("frappe.get_doc", return_value=mock_file) as mock_get_doc:
            content = doc._read_local_file("/files/test_image.png")

        self.assertEqual(content, b"binary-content")
        mock_get_doc.assert_called_once_with("File", {"file_url": "/files/test_image.png"})

    def test_get_header_text(self):
        """Test get_header for TEXT header type."""
        doc = self._make_template_without_hooks(
            template_name="test_tmpl_hdr_text",
            header_type="TEXT",
            header="Order Update"
        )
        header = doc.get_header()
        self.assertEqual(header["type"], "header")
        self.assertEqual(header["format"], "TEXT")
        self.assertEqual(header["text"], "Order Update")

    def test_get_header_text_with_sample(self):
        """Test get_header for TEXT header with sample values."""
        doc = self._make_template_without_hooks(
            template_name="test_tmpl_hdr_sample",
            header_type="TEXT",
            header="Hello {{1}}",
            sample_values="John"
        )
        doc.sample = "John"
        header = doc.get_header()
        self.assertEqual(header["format"], "TEXT")
        self.assertIn("example", header)
        self.assertEqual(header["example"]["header_text"], ["John"])

    def test_get_settings(self):
        """Test get_settings loads WhatsApp Account credentials."""
        doc = self._make_template_without_hooks(template_name="test_tmpl_settings")
        doc.get_settings()
        self.assertEqual(doc._url, "https://graph.facebook.com")
        self.assertEqual(doc._version, "v17.0")
        self.assertEqual(doc._business_id, "tmpl_test_business_id")

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_after_insert_creates_template_on_meta(self, mock_post):
        """Test after_insert sends template to Meta API."""
        mock_post.return_value = {
            "id": "new_template_id_123",
            "status": "PENDING",
        }

        doc = frappe.get_doc({
            "doctype": "WhatsApp Templates",
            "template_name": "test_tmpl_insert",
            "template": "Test body {{1}}",
            "sample_values": "World",
            "category": "TRANSACTIONAL",
            "language": frappe.db.get_value("Language", {"language_code": "en"}) or "en",
            "language_code": "en",
            "whatsapp_account": "Test WA Tmpl Account",
        })
        doc.insert(ignore_permissions=True)

        self.assertTrue(mock_post.called)
        call_args = mock_post.call_args
        sent_data = json.loads(call_args.kwargs.get("data", call_args[1].get("data", "")))
        self.assertEqual(sent_data["name"], "test_tmpl_insert")
        self.assertEqual(sent_data["language"], "en")
        self.assertEqual(sent_data["category"], "TRANSACTIONAL")
        self.assertTrue(any(c["type"] == "BODY" for c in sent_data["components"]))

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_after_insert_with_footer(self, mock_post):
        """Test template creation includes footer in components."""
        mock_post.return_value = {"id": "tmpl_footer_id", "status": "PENDING"}

        doc = frappe.get_doc({
            "doctype": "WhatsApp Templates",
            "template_name": "test_tmpl_footer",
            "template": "Body text",
            "footer": "Reply STOP to opt out",
            "category": "MARKETING",
            "language": frappe.db.get_value("Language", {"language_code": "en"}) or "en",
            "language_code": "en",
            "whatsapp_account": "Test WA Tmpl Account",
        })
        doc.insert(ignore_permissions=True)

        call_args = mock_post.call_args
        sent_data = json.loads(call_args.kwargs.get("data", call_args[1].get("data", "")))
        footer_components = [c for c in sent_data["components"] if c["type"] == "FOOTER"]
        self.assertEqual(len(footer_components), 1)
        self.assertEqual(footer_components[0]["text"], "Reply STOP to opt out")

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_after_insert_with_buttons(self, mock_post):
        """Test template creation includes buttons."""
        mock_post.return_value = {"id": "tmpl_btn_id", "status": "PENDING"}

        doc = frappe.get_doc({
            "doctype": "WhatsApp Templates",
            "template_name": "test_tmpl_buttons",
            "template": "Click below",
            "category": "TRANSACTIONAL",
            "language": frappe.db.get_value("Language", {"language_code": "en"}) or "en",
            "language_code": "en",
            "whatsapp_account": "Test WA Tmpl Account",
        })
        doc.append("buttons", {
            "button_type": "Quick Reply",
            "button_label": "Yes",
        })
        doc.append("buttons", {
            "button_type": "Visit Website",
            "button_label": "Visit",
            "website_url": "https://example.com",
            "url_type": "Static",
        })
        doc.insert(ignore_permissions=True)

        call_args = mock_post.call_args
        sent_data = json.loads(call_args.kwargs.get("data", call_args[1].get("data", "")))
        button_components = [c for c in sent_data["components"] if c["type"] == "BUTTONS"]
        self.assertEqual(len(button_components), 1)
        buttons = button_components[0]["buttons"]
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0]["type"], "QUICK_REPLY")
        self.assertEqual(buttons[1]["type"], "URL")

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_request")
    def test_on_trash_deletes_from_meta(self, mock_request, mock_post):
        """Test on_trash calls Meta API to delete template."""
        mock_post.return_value = {"id": "tmpl_trash_id", "status": "PENDING"}

        doc = frappe.get_doc({
            "doctype": "WhatsApp Templates",
            "template_name": "test_tmpl_trash",
            "template": "Delete me",
            "category": "TRANSACTIONAL",
            "language": frappe.db.get_value("Language", {"language_code": "en"}) or "en",
            "language_code": "en",
            "whatsapp_account": "Test WA Tmpl Account",
        })
        doc.insert(ignore_permissions=True)

        mock_request.return_value = {}
        doc.delete()

        # Verify DELETE was called on Meta API
        self.assertTrue(mock_request.called)
        delete_call = mock_request.call_args
        self.assertEqual(delete_call[0][0], "DELETE")
        self.assertIn("message_templates", delete_call[0][1])

    @patch("frappe.model.document.Document.get_password", return_value="mock_token")
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_request")
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_fetch_templates_from_meta(self, mock_post, mock_get, mock_get_password):
        """Test the fetch whitelisted function."""
        mock_get.return_value = {
            "data": [
                {
                    "name": "test_tmpl_fetched",
                    "status": "APPROVED",
                    "language": "en",
                    "category": "UTILITY",
                    "id": "fetched_tmpl_id",
                    "components": [
                        {"type": "BODY", "text": "Hello {{1}}, your order is ready"},
                        {"type": "FOOTER", "text": "Thank you"},
                    ]
                }
            ]
        }

        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import fetch
        result = fetch()
        self.assertEqual(result, "Successfully fetched templates from meta")

    def _templates_url(self, account_name):
        """message_templates endpoint fetch() calls for this account."""
        account = frappe.get_doc("WhatsApp Account", account_name)
        return f"{account.url}/{account.version}/{account.business_id}/message_templates"

    def _meta_template(self, name, language="en", body="Hello {{1}}", template_id=None):
        """One template in the shape Meta's message_templates API returns."""
        return {
            "name": name,
            "status": "APPROVED",
            "language": language,
            "category": "UTILITY",
            "id": template_id or f"meta_id_{name}_{language}",
            "components": [{"type": "BODY", "text": body}],
        }

    def _serve_meta_pages(self, mock_request, pages_by_url):
        """Answer each mocked GET with its page; other active accounts on the site get no templates."""
        mock_request.side_effect = lambda method, url, **kwargs: pages_by_url.get(url, {"data": []})

    @patch("frappe.model.document.Document.get_password", return_value="mock_token")
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_request")
    def test_fetch_syncs_every_active_account(self, mock_request, mock_get_password):
        """fetch() syncs all active accounts, not only the first one."""
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import fetch

        self._serve_meta_pages(mock_request, {
            self._templates_url("Test WA Tmpl Account"): {"data": [self._meta_template("test_tmpl_acct_one")]},
            self._templates_url("Test WA Tmpl Account 2"): {"data": [self._meta_template("test_tmpl_acct_two")]},
        })

        fetch()

        self.assertEqual(
            frappe.db.get_value("WhatsApp Templates", {"actual_name": "test_tmpl_acct_one"}, "whatsapp_account"),
            "Test WA Tmpl Account",
        )
        self.assertEqual(
            frappe.db.get_value("WhatsApp Templates", {"actual_name": "test_tmpl_acct_two"}, "whatsapp_account"),
            "Test WA Tmpl Account 2",
        )

    @patch("frappe.model.document.Document.get_password", return_value="mock_token")
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_request")
    def test_fetch_follows_paging_next(self, mock_request, mock_get_password):
        """fetch() reads every page Meta returns, following paging.next until it is absent."""
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import fetch

        first_page_url = self._templates_url("Test WA Tmpl Account")
        next_page_url = f"{first_page_url}?limit=1&after=cursor_page_2"
        self._serve_meta_pages(mock_request, {
            first_page_url: {
                "data": [self._meta_template("test_tmpl_page_one")],
                "paging": {"cursors": {"before": "cursor_page_1", "after": "cursor_page_2"}, "next": next_page_url},
            },
            next_page_url: {
                "data": [self._meta_template("test_tmpl_page_two")],
                "paging": {"cursors": {"before": "cursor_page_2", "after": "cursor_page_3"}},
            },
        })

        fetch()

        self.assertTrue(frappe.db.exists("WhatsApp Templates", {"actual_name": "test_tmpl_page_one"}))
        self.assertTrue(frappe.db.exists("WhatsApp Templates", {"actual_name": "test_tmpl_page_two"}))
        next_page_calls = [c for c in mock_request.call_args_list if c.args[1] == next_page_url]
        self.assertEqual(len(next_page_calls), 1)
        self.assertEqual(next_page_calls[0].kwargs["headers"]["authorization"], "Bearer mock_token")

    @patch("frappe.model.document.Document.get_password", return_value="mock_token")
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_request")
    def test_fetch_keeps_each_language_as_its_own_record(self, mock_request, mock_get_password):
        """Two languages of one Meta template stay two records, and a re-sync updates each in place."""
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import fetch

        english = self._meta_template("test_tmpl_multi_lang", language="en", body="Your order is ready")
        hindi = self._meta_template("test_tmpl_multi_lang", language="hi", body="Aapka order taiyaar hai")
        self._serve_meta_pages(mock_request, {
            self._templates_url("Test WA Tmpl Account"): {"data": [english, hindi]},
        })

        def synced_languages():
            return frappe.get_all(
                "WhatsApp Templates",
                filters={"actual_name": "test_tmpl_multi_lang"},
                fields=["name", "language_code", "id", "template"],
                order_by="language_code asc",
            )

        fetch()
        first_sync = synced_languages()
        self.assertEqual(
            [(t.name, t.language_code, t.id, t.template) for t in first_sync],
            [
                ("test_tmpl_multi_lang-en", "en", english["id"], "Your order is ready"),
                ("test_tmpl_multi_lang-hi", "hi", hindi["id"], "Aapka order taiyaar hai"),
            ],
        )

        hindi["components"][0]["text"] = "Aapka order bhej diya gaya hai"
        fetch()
        second_sync = synced_languages()
        self.assertEqual(
            [(t.name, t.template) for t in second_sync],
            [
                ("test_tmpl_multi_lang-en", "Your order is ready"),
                ("test_tmpl_multi_lang-hi", "Aapka order bhej diya gaya hai"),
            ],
        )

    def test_upsert_doc_without_hooks(self):
        """Test upsert_doc_without_hooks inserts and updates correctly."""
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import upsert_doc_without_hooks

        doc = self._make_template_without_hooks(template_name="test_tmpl_upsert")

        # Update template text
        doc.template = "Updated body text"
        upsert_doc_without_hooks(doc, "WhatsApp Button", "buttons")

        doc.reload()
        self.assertEqual(doc.template, "Updated body text")

    # ------------------------------------------------------------------
    # Open Point 1 — Sample Values validation
    # ------------------------------------------------------------------
    def _new_template_doc(self, **kwargs):
        """Build (not insert) a template doc with required fields defaulted."""
        data = {
            "doctype": "WhatsApp Templates",
            "template_name": kwargs.pop("template_name", "test_tmpl_op1"),
            "template": kwargs.pop("template", "Hello {{1}}"),
            "sample_values": kwargs.pop("sample_values", ""),
            # MARKETING is valid for both the base Select and leanerp_whatsapp's
            # custom_internal_category Select on v15.localhost.
            "category": kwargs.pop("category", "MARKETING"),
            "language": frappe.db.get_value("Language", {"language_code": "en"}) or "en",
            "language_code": "en",
            "whatsapp_account": "Test WA Tmpl Account",
        }
        data.update(kwargs)
        return frappe.get_doc(data)

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_sample_values_count_mismatch_blocks(self, mock_post):
        """3 variables but 2 values -> blocked, nothing sent to Meta."""
        doc = self._new_template_doc(
            template_name="test_tmpl_op1_count",
            template="Hi {{1}} {{2}} {{3}}",
            sample_values="a,b",
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_sample_values_newline_blocks(self, mock_post):
        """Values on separate lines -> blocked."""
        doc = self._new_template_doc(
            template_name="test_tmpl_op1_nl",
            template="Hi {{1}} {{2}} {{3}}",
            sample_values="a\nb\nc",
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_sample_values_gap_blocks(self, mock_post):
        """Only {{1}} and {{3}} (gap) -> blocked."""
        doc = self._new_template_doc(
            template_name="test_tmpl_op1_gap",
            template="Hi {{1}} {{3}}",
            sample_values="a,b",
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_sample_values_empty_but_vars_blocks(self, mock_post):
        """Variables present but Sample Values empty -> blocked (timesheet_reminder case)."""
        doc = self._new_template_doc(
            template_name="test_tmpl_op1_empty",
            template="Hi {{1}} {{2}}",
            sample_values="",
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_sample_values_trimmed_on_save(self, mock_post):
        """3 variables, 3 values with extra spaces -> saves, values trimmed."""
        mock_post.return_value = {"id": "op1_ok", "status": "PENDING"}
        doc = self._new_template_doc(
            template_name="test_tmpl_op1_trim",
            template="Hi {{1}} {{2}} {{3}}",
            sample_values=" a , b , c ",
        )
        doc.insert(ignore_permissions=True)
        self.assertTrue(mock_post.called)
        self.assertEqual(doc.sample_values, "a,b,c")

    # ------------------------------------------------------------------
    # SRO-2026-10-00227 — media header (DOCUMENT/IMAGE) crash
    # ------------------------------------------------------------------
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_media_header_without_sample_blocks(self, mock_post):
        """DOCUMENT header without a sample -> clear message, no crash, nothing sent."""
        doc = self._new_template_doc(
            template_name="test_tmpl_media_nosample",
            template="Your document is ready",
            header_type="DOCUMENT",
            sample="",
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    def test_sample_not_reuploaded_when_unchanged(self):
        """Editing a media template without touching the sample does not re-upload."""
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import (
            WhatsAppTemplates,
        )

        doc = self._make_template_without_hooks(
            template_name="test_tmpl_media_gate",
            template="Your document is ready",
            category="MARKETING",
            header_type="DOCUMENT",
        )
        frappe.db.set_value(
            "WhatsApp Templates", doc.name,
            {"sample": "/files/doc.pdf", "header_media_handle": "H_OLD"},
        )
        doc.reload()

        with patch.object(WhatsAppTemplates, "get_session_id") as m_session, \
             patch.object(WhatsAppTemplates, "get_media_id") as m_media, \
             patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request") as mock_post:
            mock_post.return_value = {}
            doc.footer = "New footer"  # a Meta field changed, but the sample did not
            doc.save(ignore_permissions=True)
            m_session.assert_not_called()
            m_media.assert_not_called()
            self.assertTrue(mock_post.called)  # update ran, reusing the stored handle

    def test_sample_reuploaded_when_changed(self):
        """Changing the sample re-uploads it and refreshes the stored handle."""
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import (
            WhatsAppTemplates,
        )

        doc = self._make_template_without_hooks(
            template_name="test_tmpl_media_change",
            template="Your document is ready",
            category="MARKETING",
            header_type="DOCUMENT",
        )
        frappe.db.set_value(
            "WhatsApp Templates", doc.name,
            {"sample": "/files/old.pdf", "header_media_handle": "H_OLD"},
        )
        doc.reload()

        def _fake_media(file):
            doc._media_id = "H_NEW"

        with patch.object(WhatsAppTemplates, "get_session_id") as m_session, \
             patch.object(WhatsAppTemplates, "get_media_id", side_effect=_fake_media) as m_media, \
             patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request") as mock_post:
            mock_post.return_value = {}
            doc.sample = "/files/new.pdf"
            doc.save(ignore_permissions=True)
            m_session.assert_called_once()
            m_media.assert_called_once()
        self.assertEqual(doc.header_media_handle, "H_NEW")

    # ------------------------------------------------------------------
    # SRO-2026-10-00228 — call Meta only on real changes + surface the error
    # ------------------------------------------------------------------
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_no_meta_call_on_internal_field_change(self, mock_post):
        """Editing only an internal field (for_doctype) sends nothing to Meta."""
        doc = self._make_template_without_hooks(
            template_name="test_tmpl_internal",
            template="Order update",  # no variables
            category="MARKETING",
        )
        doc.for_doctype = "User"
        doc.save(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_meta_call_on_body_change(self, mock_post):
        """Editing the body (a Meta-stored field) does call Meta."""
        mock_post.return_value = {}
        doc = self._make_template_without_hooks(
            template_name="test_tmpl_bodychg",
            template="Order update",
            category="MARKETING",
        )
        doc.template = "Order update v2"
        doc.save(ignore_permissions=True)
        self.assertTrue(mock_post.called)

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_edit_error_shows_meta_message(self, mock_post):
        """On an edit error, Meta's real message is surfaced (not the raw 400)."""
        from requests.exceptions import HTTPError

        doc = self._make_template_without_hooks(
            template_name="test_tmpl_err",
            template="Order update",
            category="MARKETING",
        )
        resp = MagicMock()
        resp.json.return_value = {
            "error": {"error_user_msg": "Real Meta reason", "error_user_title": "Oops"}
        }
        frappe.flags.integration_request = resp
        mock_post.side_effect = HTTPError("400 Client Error: Bad Request")

        doc.template = "Order update v2"
        with self.assertRaises(frappe.ValidationError) as cm:
            doc.save(ignore_permissions=True)
        self.assertIn("Real Meta reason", str(cm.exception))

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_network_error_shows_readable_message(self, mock_post):
        """A connection error gives a readable message, not 'NoneType ... json'."""
        from requests.exceptions import ConnectionError as ReqConnectionError

        doc = self._make_template_without_hooks(
            template_name="test_tmpl_net",
            template="Order update",
            category="MARKETING",
        )
        frappe.flags.integration_request = None
        mock_post.side_effect = ReqConnectionError("Failed to establish a new connection")

        doc.template = "Order update v2"
        with self.assertRaises(frappe.ValidationError) as cm:
            doc.save(ignore_permissions=True)
        self.assertIn("Could not reach Meta", str(cm.exception))

    # ------------------------------------------------------------------
    # Copilot review follow-ups (buttons comparison, upload gating, blank sample)
    # ------------------------------------------------------------------
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_no_meta_call_on_internal_change_with_buttons(self, mock_post):
        """A template WITH buttons: an internal-only edit still sends nothing to Meta.

        Guards against has_value_changed("buttons") (identity compare on fresh
        child instances) reporting a change on every save.
        """
        mock_post.return_value = {"id": "btn_gate_id", "status": "PENDING"}
        doc = self._new_template_doc(
            template_name="test_tmpl_btn_gate",
            template="Click below",  # no variables
        )
        doc.append("buttons", {"button_type": "Quick Reply", "button_label": "Yes"})
        doc.append("buttons", {
            "button_type": "Visit Website",
            "button_label": "Visit",
            "website_url": "https://example.com",
            "url_type": "Static",
        })
        doc.insert(ignore_permissions=True)
        self.assertTrue(mock_post.called)  # creation hit Meta

        mock_post.reset_mock()
        doc.reload()
        doc.for_doctype = "User"  # internal-only field
        doc.save(ignore_permissions=True)
        mock_post.assert_not_called()  # buttons unchanged -> no Meta edit

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_meta_call_on_button_value_change(self, mock_post):
        """Changing a button value is a real Meta change and does hit Meta."""
        mock_post.return_value = {"id": "btn_chg_id", "status": "PENDING"}
        doc = self._new_template_doc(
            template_name="test_tmpl_btn_chg",
            template="Click below",
        )
        doc.append("buttons", {"button_type": "Quick Reply", "button_label": "Yes"})
        doc.insert(ignore_permissions=True)

        mock_post.reset_mock()
        doc.reload()
        doc.buttons[0].button_label = "Confirm"
        doc.save(ignore_permissions=True)
        self.assertTrue(mock_post.called)

    def test_internal_edit_of_media_template_without_handle_does_not_upload(self):
        """An internal-only edit of a media template with no stored handle uploads nothing.

        Previously `not self.header_media_handle` forced an upload on any save of a
        pre-existing media template; now the upload is tied to a real Meta change.
        """
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import (
            WhatsAppTemplates,
        )

        doc = self._make_template_without_hooks(
            template_name="test_tmpl_media_internal",
            template="Your document is ready",
            category="MARKETING",
            header_type="DOCUMENT",
        )
        # Media template with a sample but NO stored handle yet (pre-existing row).
        frappe.db.set_value(
            "WhatsApp Templates", doc.name,
            {"sample": "/files/doc.pdf", "header_media_handle": ""},
        )
        doc.reload()

        with patch.object(WhatsAppTemplates, "get_session_id") as m_session, \
             patch.object(WhatsAppTemplates, "get_media_id") as m_media, \
             patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request") as mock_post:
            mock_post.return_value = {}
            doc.for_doctype = "User"  # internal-only field
            doc.save(ignore_permissions=True)
            m_session.assert_not_called()
            m_media.assert_not_called()
            mock_post.assert_not_called()

    def test_blank_sample_cleared_for_variable_free_body(self):
        """A whitespace-only Sample Values on a no-variable body is normalised to ''."""
        doc = self._new_template_doc(
            template_name="test_tmpl_ws_sample",
            template="Order update",  # no variables
            sample_values="   ",
        )
        doc.validate_sample_values()
        self.assertEqual(doc.sample_values, "")

    # ------------------------------------------------------------------
    # SRO-2026-10-00230 — validate name / header / buttons + Flow/MPM/Catalog
    # ------------------------------------------------------------------
    def _ensure_test_flow(self):
        """A published WhatsApp Flow fixture with a flow_id (for Flow buttons)."""
        name = "test_tmpl_flow_fixture"
        if not frappe.db.exists("WhatsApp Flow", name):
            flow = frappe.get_doc({
                "doctype": "WhatsApp Flow",
                "flow_name": name,
                "whatsapp_account": "Test WA Tmpl Account",
                "category": "OTHER",
                "status": "Published",
                "flow_id": "flow_id_test_123",
            })
            flow.name = name
            flow.db_insert()
            frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture must be visible to later queries
        return name

    def _sent_buttons(self, mock_post):
        data = json.loads(mock_post.call_args.kwargs["data"])
        for c in data["components"]:
            if c["type"] == "BUTTONS":
                return c["buttons"]
        return []

    # --- case 1: template name ---
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_template_name_with_hyphen_blocks(self, mock_post):
        """A label with a hyphen can't make a valid Meta name -> blocked."""
        doc = self._new_template_doc(
            template_name="test_tmpl_bad-name", template="Order update", sample_values="",
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_template_name_trailing_space_stripped(self, mock_post):
        """A trailing space yields a clean actual_name (not `..._`)."""
        mock_post.return_value = {"id": "nm1", "status": "PENDING"}
        doc = self._new_template_doc(
            template_name="test_tmpl_trail ", template="Order update", sample_values="",
        )
        doc.insert(ignore_permissions=True)
        self.assertEqual(doc.actual_name, "test_tmpl_trail")

    # --- cases 2-4: buttons ---
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_call_phone_without_number_blocks(self, mock_post):
        doc = self._new_template_doc(template_name="test_tmpl_cp", template="Order update")
        doc.append("buttons", {"button_type": "Call Phone", "button_label": "Call"})
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_visit_website_without_url_blocks(self, mock_post):
        doc = self._new_template_doc(template_name="test_tmpl_vw", template="Order update")
        doc.append("buttons", {"button_type": "Visit Website", "button_label": "Open", "url_type": "Static"})
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_dynamic_url_without_variable_blocks(self, mock_post):
        doc = self._new_template_doc(template_name="test_tmpl_dynv", template="Order update")
        doc.append("buttons", {
            "button_type": "Visit Website", "button_label": "Open",
            "url_type": "Dynamic", "website_url": "https://x.com/view", "example_url": "https://x.com/view/1",
        })
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_dynamic_url_without_example_blocks(self, mock_post):
        doc = self._new_template_doc(template_name="test_tmpl_dyne", template="Order update")
        doc.append("buttons", {
            "button_type": "Visit Website", "button_label": "Open",
            "url_type": "Dynamic", "website_url": "https://x.com/{{1}}",
        })
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    # --- case 5: header TEXT with a variable ---
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_text_header_with_variable_needs_sample_blocks(self, mock_post):
        doc = self._new_template_doc(
            template_name="test_tmpl_hdrvar", template="Order update",
            header_type="TEXT", header="Hi {{1}}",
        )
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    # --- case 6: Flow/MPM/Catalog rules ---
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_flow_button_without_flow_blocks(self, mock_post):
        doc = self._new_template_doc(template_name="test_tmpl_flow0", template="Order update")
        doc.append("buttons", {"button_type": "Flow", "button_label": "Open"})
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_two_mpm_buttons_blocks(self, mock_post):
        doc = self._new_template_doc(template_name="test_tmpl_2mpm", template="Order update")
        doc.append("buttons", {"button_type": "Multi-Product Message", "button_label": "A"})
        doc.append("buttons", {"button_type": "Multi-Product Message", "button_label": "B"})
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_flow_and_catalog_mix_blocks(self, mock_post):
        flow = self._ensure_test_flow()
        doc = self._new_template_doc(template_name="test_tmpl_mix", template="Order update")
        doc.append("buttons", {"button_type": "Flow", "button_label": "Open", "flow": flow})
        doc.append("buttons", {"button_type": "Catalog", "button_label": "Shop"})
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    # --- Flow / Catalog create payloads (verified shapes) ---
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_flow_button_create_payload(self, mock_post):
        mock_post.return_value = {"id": "fl1", "status": "PENDING"}
        flow = self._ensure_test_flow()
        doc = self._new_template_doc(template_name="test_tmpl_flowok", template="Order update")
        doc.append("buttons", {
            "button_type": "Flow", "button_label": "Open form",
            "flow": flow, "navigate_screen": "WELCOME",
        })
        doc.insert(ignore_permissions=True)
        btn = self._sent_buttons(mock_post)[0]
        self.assertEqual(btn["type"], "FLOW")
        self.assertEqual(btn["flow_id"], "flow_id_test_123")
        self.assertEqual(btn["flow_action"], "navigate")
        self.assertEqual(btn["navigate_screen"], "WELCOME")

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_catalog_button_create_payload(self, mock_post):
        mock_post.return_value = {"id": "ct1", "status": "PENDING"}
        doc = self._new_template_doc(template_name="test_tmpl_catok", template="Order update")
        doc.append("buttons", {"button_type": "Catalog", "button_label": "View catalog"})
        doc.insert(ignore_permissions=True)
        btn = self._sent_buttons(mock_post)[0]
        self.assertEqual(btn, {"type": "CATALOG", "text": "View catalog"})

    # --- Copilot review follow-ups (findings 1-4) ---
    def _ensure_draft_flow(self):
        """A WhatsApp Flow fixture that has a flow_id but is still Draft."""
        name = "test_tmpl_draft_flow_fixture"
        if not frappe.db.exists("WhatsApp Flow", name):
            flow = frappe.get_doc({
                "doctype": "WhatsApp Flow",
                "flow_name": name,
                "whatsapp_account": "Test WA Tmpl Account",
                "category": "OTHER",
                "status": "Draft",
                "flow_id": "draft_flow_id_1",
            })
            flow.name = name
            flow.db_insert()
            frappe.db.commit()  # nosemgrep: frappe-manual-commit -- fixture visible to later queries
        return name

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_draft_flow_with_id_blocks(self, mock_post):
        """Finding 3: a Flow with a flow_id but status != Published is rejected
        (create_on_whatsapp assigns an id before publication); Meta not called."""
        flow = self._ensure_draft_flow()
        doc = self._new_template_doc(template_name="test_tmpl_draftflow", template="Order update")
        doc.append("buttons", {"button_type": "Flow", "button_label": "Open", "flow": flow})
        with self.assertRaises(frappe.ValidationError):
            doc.insert(ignore_permissions=True)
        mock_post.assert_not_called()

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_flow_data_exchange_omits_navigate_screen(self, mock_post):
        """Finding 4: flow_action=data_exchange must NOT emit navigate_screen
        (Meta only allows it with the navigate action)."""
        mock_post.return_value = {"id": "fldx", "status": "PENDING"}
        flow = self._ensure_test_flow()
        doc = self._new_template_doc(template_name="test_tmpl_flowdx", template="Order update")
        doc.append("buttons", {
            "button_type": "Flow", "button_label": "Open form",
            "flow": flow, "flow_action": "data_exchange", "navigate_screen": "WELCOME",
        })
        doc.insert(ignore_permissions=True)
        btn = self._sent_buttons(mock_post)[0]
        self.assertEqual(btn["flow_action"], "data_exchange")
        self.assertNotIn("navigate_screen", btn)

    @patch("frappe.model.document.Document.get_password", return_value="mock_token")
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_request")
    def test_fetch_resolves_flow_link_and_keeps_navigation(self, mock_request, mock_get_password):
        """Finding 1: fetch() must map Meta's flow_id back to the local WhatsApp Flow
        and keep flow_action / navigate_screen, not clear the Flow link."""
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import fetch
        flow = self._ensure_test_flow()  # Published, flow_id flow_id_test_123
        tmpl = {
            "name": "test_tmpl_fetchflow", "status": "APPROVED", "language": "en",
            "category": "UTILITY", "id": "fetched_flow_tmpl_id",
            "components": [
                {"type": "BODY", "text": "Hi {{1}}"},
                {"type": "BUTTONS", "buttons": [{
                    "type": "FLOW", "text": "Open form", "flow_id": "flow_id_test_123",
                    "flow_action": "NAVIGATE", "navigate_screen": "WELCOME",
                }]},
            ],
        }
        self._serve_meta_pages(mock_request, {
            self._templates_url("Test WA Tmpl Account"): {"data": [tmpl]},
        })
        fetch()
        name = frappe.db.get_value("WhatsApp Templates", {"actual_name": "test_tmpl_fetchflow"}, "name")
        self.assertTrue(name)
        rows = frappe.get_all(
            "WhatsApp Button", filters={"parent": name},
            fields=["button_type", "flow", "flow_action", "navigate_screen"],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].button_type, "Flow")
        self.assertEqual(rows[0].flow, flow)
        self.assertEqual(rows[0].flow_action, "navigate")  # Meta's NAVIGATE lowercased
        self.assertEqual(rows[0].navigate_screen, "WELCOME")

    @patch("frappe.model.document.Document.get_password", return_value="mock_token")
    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_request")
    def test_fetch_imports_text_header_example(self, mock_request, mock_get_password):
        """Finding 2: a fetched TEXT header with a {{n}} must import its example into
        `sample`, else the template fails validate_header on every later save."""
        from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates import fetch
        tmpl = {
            "name": "test_tmpl_fetchhdr", "status": "APPROVED", "language": "en",
            "category": "UTILITY", "id": "fetched_hdr_tmpl_id",
            "components": [
                {"type": "HEADER", "format": "TEXT", "text": "Hi {{1}}",
                 "example": {"header_text": ["Ravi"]}},
                {"type": "BODY", "text": "Your order is ready"},
            ],
        }
        self._serve_meta_pages(mock_request, {
            self._templates_url("Test WA Tmpl Account"): {"data": [tmpl]},
        })
        fetch()
        name = frappe.db.get_value("WhatsApp Templates", {"actual_name": "test_tmpl_fetchhdr"}, "name")
        self.assertEqual(frappe.db.get_value("WhatsApp Templates", name, "sample"), "Ravi")

    @patch("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.make_post_request")
    def test_unchanged_text_header_without_sample_not_blocked(self, mock_post):
        """Finding 2: an older imported template whose TEXT header has a {{n}} but no
        sample must stay editable (footer-only change) without being blocked."""
        mock_post.return_value = {"id": "oldhdr", "status": "PENDING"}
        doc = self._make_template_without_hooks(
            template_name="test_tmpl_oldhdr", template="Your order is ready",
            category="MARKETING", header_type="TEXT", header="Hi {{1}}",
        )
        doc.footer = "New footer"
        doc.save(ignore_permissions=True)  # header unchanged -> validate_header must not block
        self.assertEqual(doc.footer, "New footer")
