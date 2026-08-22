"""Low-level, dependency-free WhatsApp send primitives.

These live in frappe_whatsapp — the base app every WhatsApp surface hard-depends on —
so both the leanerp_whatsapp Conversation tab and the leanerp_whatsapp_chat chat page
can share one implementation of "create an outgoing WhatsApp Message" without either
app depending on the other.

IMPORTANT: these are **internal helpers, not whitelisted endpoints**. They perform no
authorization — the caller is responsible for gating (record permission, agent
assignment, etc.) *before* calling. Exposing them directly would let any caller send
to any number, bypassing every surface's gate.
"""

import re

import frappe
from frappe.utils import add_to_date, cint, now_datetime


def _phone_match_key(number):
    """Canonical match key for the ``from_normalized`` column.

    leanerp owns the normalizer (national significant number) AND is the app that
    writes ``from_normalized``, so when it is installed the two always agree. Without
    leanerp the column doesn't exist either (it ships via leanerp_whatsapp, which
    requires leanerp) — the legacy last-10-digits slice then feeds the LIKE fallback.
    """
    try:
        from leanerp.utils.helper import normalize_phone

        return normalize_phone(number)
    except ImportError:
        digits = re.sub(r"\D", "", str(number or ""))
        if not digits:
            return None
        return digits[-10:]


def send_text(to, message, reference_doctype=None, reference_name=None):
    """Create an outgoing free-text WhatsApp Message (frappe_whatsapp sends on insert).

    Returns the inserted document. Gating is the caller's responsibility.
    """
    doc = frappe.get_doc(
        {
            "doctype": "WhatsApp Message",
            "to": to,
            "type": "Outgoing",
            "message_type": "Manual",
            "content_type": "text",
            "message": message,
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def send_template(to, template, params=None, reference_doctype=None, reference_name=None):
    """Create an outgoing template WhatsApp Message.

    ``params`` is a JSON string of ordered body values ({"1": "...", "2": "..."}).
    frappe_whatsapp's before_insert -> send_template() delivers it via the body_param
    branch. Gating (incl. the APPROVED-template check) is the caller's responsibility.
    """
    doc = frappe.get_doc(
        {
            "doctype": "WhatsApp Message",
            "to": to,
            "type": "Outgoing",
            "message_type": "Template",
            "content_type": "text",
            "template": template,
            # body_param must be a JSON *string* (WhatsAppMessage.send_template does
            # json.loads on it). Accept a JSON string as-is; coerce dict/list/None.
            "body_param": (params or "{}") if isinstance(params, str) else frappe.as_json(params or {}),
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc


def reply_window_open(to, hours):
    """True if an inbound WhatsApp Message from ``to`` arrived within the last ``hours``.

    The window *length* is caller-supplied (each surface sources its own setting), but
    the query itself is generic and belongs with the WhatsApp Message table. Prefers the
    indexed ``from_normalized`` column (equality) over a leading-wildcard LIKE full scan.
    """
    key = _phone_match_key(to)
    if not key:
        return False
    cutoff = add_to_date(now_datetime(), hours=-cint(hours))
    if frappe.db.has_column("WhatsApp Message", "from_normalized"):
        from_filter = {"from_normalized": key}
    else:
        from_filter = {"from": ["like", f"%{key}"]}
    # type="Incoming" makes "inbound" explicit — an outgoing row that happens to carry
    # the contact in `from` must never be read as the customer having replied.
    return bool(
        frappe.get_all(
            "WhatsApp Message",
            filters={**from_filter, "type": "Incoming", "creation": [">", cutoff]},
            limit=1,
        )
    )
