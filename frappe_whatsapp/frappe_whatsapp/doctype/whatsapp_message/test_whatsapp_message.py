"""test Whatsapp messages."""
# Copyright (c) 2022, Shridhar Patil and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp.utils import webhook


class TestWhatsAppMessage(FrappeTestCase):
    """Test whatsapp messages."""

    pass


class TestApplyWhatsappMessageStatus(FrappeTestCase):
    """apply_whatsapp_message_status retries through transient 1020/1213 and is non-fatal.

    Fully mocked — the WhatsApp Message row + frappe.db calls are patched, so no DB / no site state.
    """

    def _run(self, set_value_side_effect=None, name="WA-MSG-1", conversation=None):
        with (
            patch.object(webhook.frappe.db, "get_value", return_value=name) as m_get,
            patch.object(webhook.frappe.db, "set_value", side_effect=set_value_side_effect) as m_set,
            patch.object(webhook.frappe.db, "commit") as m_commit,
            patch.object(webhook.frappe.db, "rollback") as m_rb,
            patch.object(webhook.time, "sleep"),
            patch.object(webhook.frappe, "log_error") as m_log,
        ):
            webhook.apply_whatsapp_message_status("wamid.X", "delivered", conversation=conversation)
        return m_get, m_set, m_commit, m_rb, m_log

    def test_retries_through_conflict_then_succeeds(self):
        """Two 1020s then success → set_value retried, committed once, nothing logged."""
        calls = {"n": 0}

        def se(*a, **k):
            calls["n"] += 1
            if calls["n"] < 3:
                raise frappe.QueryDeadlockError("1020 record has changed")

        _m_get, m_set, m_commit, m_rb, m_log = self._run(set_value_side_effect=se)
        self.assertEqual(m_set.call_count, 3, "set_value retried until it succeeds")
        self.assertEqual(m_commit.call_count, 1, "commit once, after the successful UPDATE")
        self.assertEqual(m_rb.call_count, 3, "one up-front rollback + before each of the 2 retries (fresh snapshot)")
        m_log.assert_not_called()

    def test_exhaustion_logs_once_and_does_not_raise(self):
        """Persistent conflict → exhausts attempts, logs once, never raises (non-fatal job)."""

        def se(*a, **k):
            raise frappe.QueryTimeoutError("1205 lock wait timeout")

        _m_get, m_set, m_commit, m_rb, m_log = self._run(set_value_side_effect=se)  # must not raise
        self.assertEqual(m_set.call_count, webhook._STATUS_RETRY_ATTEMPTS, "one set_value per attempt")
        self.assertEqual(
            m_rb.call_count,
            webhook._STATUS_RETRY_ATTEMPTS + 1,
            "one up-front rollback + one per attempt",
        )
        m_commit.assert_not_called()
        self.assertEqual(m_log.call_count, 1, "logs once, on exhaustion")

    def test_missing_message_is_noop(self):
        """A status for a message we do not store no-ops — no UPDATE, no error."""
        with (
            patch.object(webhook.frappe.db, "get_value", return_value=None),
            patch.object(webhook.frappe.db, "set_value") as m_set,
            patch.object(webhook.frappe.db, "commit") as m_commit,
            patch.object(webhook.frappe.db, "rollback") as m_rb,
            patch.object(webhook.frappe, "log_error") as m_log,
        ):
            webhook.apply_whatsapp_message_status("wamid.unknown", "read")
        m_set.assert_not_called()
        m_commit.assert_not_called()
        m_log.assert_not_called()
        self.assertEqual(m_rb.call_count, 2, "up-front rollback + no-op-path rollback")

    def test_conversation_id_included_when_present(self):
        _m_get, m_set, _m_commit, _m_rb, _m_log = self._run(conversation="CONV-9")
        values = m_set.call_args[0][2]  # set_value(doctype, name, values)
        self.assertEqual(values.get("status"), "delivered")
        self.assertEqual(values.get("conversation_id"), "CONV-9")

    def test_conversation_id_omitted_when_absent(self):
        _m_get, m_set, _m_commit, _m_rb, _m_log = self._run(conversation=None)
        values = m_set.call_args[0][2]
        self.assertEqual(values.get("status"), "delivered")
        self.assertNotIn("conversation_id", values)
