import frappe
from frappe.utils.password import get_decrypted_password

def execute():
    if not frappe.db.table_exists("WhatsApp Account"):
        return

    wa_setting = frappe.get_single("WhatsApp Settings")
    
    phone_id = frappe.db.get_single_value("WhatsApp Settings", "phone_id")
    token = get_decrypted_password("WhatsApp Settings", "WhatsApp Settings", "token")
    business_id = frappe.db.get_single_value("WhatsApp Settings", "business_id")
    app_id = frappe.db.get_single_value("WhatsApp Settings", "app_id")
    url = frappe.db.get_single_value("WhatsApp Settings", "url")
    version = frappe.db.get_single_value("WhatsApp Settings", "version")
    webhook_verify_token = get_decrypted_password("WhatsApp Settings", "WhatsApp Settings", "webhook_verify_token")
    enabled = frappe.db.get_single_value("WhatsApp Settings", "enabled")

    if not phone_id or not token:
        return

    if frappe.db.exists("WhatsApp Account", {"phone_id": phone_id}):
        return


    account = wa_setting.append("whatsapp_accounts", {
        "account_name": "Default WhatsApp Account",
        "phone_id": phone_id,
        "business_id": business_id,
        "app_id": app_id,
        "token": token,
        "url": url,
        "version": version,
        "webhook_verify_token": webhook_verify_token,
        "is_default_incoming": 1,
        "is_default_outgoing": 1,
        "status": "Active" if enabled == 1 else "Inactive"
    })
    wa_setting.save(ignore_permissions=True)

    update_whatsapp_templates(account.name)

    frappe.db.commit()


def update_whatsapp_templates(account_name: str):
    templates = frappe.get_all(
        "WhatsApp Templates",
        filters={"whatsapp_account":  ["is", "not set"]},
        fields=["name"]
    )
    for template in templates:
        frappe.db.set_value("WhatsApp Templates", template["name"], "whatsapp_account", account_name)