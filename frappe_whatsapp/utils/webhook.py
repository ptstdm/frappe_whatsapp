"""Webhook."""
import frappe
import json
import requests
from frappe.utils.password import get_decrypted_password
from werkzeug.wrappers import Response
import frappe.utils
from frappe.utils.background_jobs import get_queues_timeout


@frappe.whitelist(allow_guest=True)
def webhook():
	"""Meta webhook."""
	if frappe.request.method == "GET":
		return get()
	return post()


def get():
	"""Get."""
	hub_challenge = frappe.form_dict.get("hub.challenge")
	webhook_verify_token = get_decrypted_password("WhatsApp Settings", "WhatsApp Settings", "webhook_verify_token")

	if frappe.form_dict.get("hub.verify_token") != webhook_verify_token:
		frappe.throw("Verify token does not match")

	return Response(hub_challenge, status=200)

def post():
	"""Post."""
	data = frappe.local.form_dict
	frappe.get_doc({
		"doctype": "WhatsApp Notification Log",
		"template": "Webhook",
		"meta_data": json.dumps(data)
	}).insert(ignore_permissions=True)

	messages = []
	try:
		messages = data["entry"][0]["changes"][0]["value"].get("messages", [])
	except KeyError:
		messages = data["entry"]["changes"][0]["value"].get("messages", [])
	sender_profile_name = next(
		(
			contact.get("profile", {}).get("name")
			for entry in data.get("entry", [])
			for change in entry.get("changes", [])
			for contact in change.get("value", {}).get("contacts", [])
		),
		None,
	)


	if messages:
		for message in messages:
			message_type = message['type']
			is_reply = True if message.get('context') and 'forwarded' not in message.get('context') else False
			reply_to_message_id = message['context']['id'] if is_reply else None
			if message_type == 'text':
				frappe.get_doc({
					"doctype": "WhatsApp Message",
					"type": "Incoming",
					"from": message['from'],
					"message": message['text']['body'],
					"message_id": message['id'],
					"reply_to_message_id": reply_to_message_id,
					"is_reply": is_reply,
					"content_type":message_type,
					"profile_name":sender_profile_name
				}).insert(ignore_permissions=True)
			elif message_type == 'reaction':
				frappe.get_doc({
					"doctype": "WhatsApp Message",
					"type": "Incoming",
					"from": message['from'],
					"message": message['reaction']['emoji'],
					"reply_to_message_id": message['reaction']['message_id'],
					"message_id": message['id'],
					"content_type": "reaction",
					"profile_name":sender_profile_name
				}).insert(ignore_permissions=True)
			elif message_type == 'interactive':
				frappe.get_doc({
					"doctype": "WhatsApp Message",
					"type": "Incoming",
					"from": message['from'],
					"message": message['interactive']['nfm_reply']['response_json'],
					"message_id": message['id'],
					"content_type": "flow",
					"profile_name":sender_profile_name
				}).insert(ignore_permissions=True)
			elif message_type in ["image", "audio", "video", "document"]:
				settings = frappe.get_doc(
							"WhatsApp Settings", "WhatsApp Settings",
						)
				token = settings.get_password("token")
				url = f"{settings.url}/{settings.version}/"


				media_id = message[message_type]["id"]
				headers = {
					'Authorization': 'Bearer ' + token

				}
				response = requests.get(f'{url}{media_id}/', headers=headers)

				if response.status_code == 200:
					media_data = response.json()
					media_url = media_data.get("url")
					mime_type = media_data.get("mime_type")
					file_extension = mime_type.split('/')[1]

					media_response = requests.get(media_url, headers=headers)
					if media_response.status_code == 200:

						file_data = media_response.content
						file_name = f"{frappe.generate_hash(length=10)}.{file_extension}"

						message_doc = frappe.get_doc({
							"doctype": "WhatsApp Message",
							"type": "Incoming",
							"from": message['from'],
							"message_id": message['id'],
							"reply_to_message_id": reply_to_message_id,
							"is_reply": is_reply,
							"message": message[message_type].get("caption",f"/files/{file_name}"),
							"content_type" : message_type,
							"profile_name":sender_profile_name
						}).insert(ignore_permissions=True)

						file = frappe.get_doc(
							{
								"doctype": "File",
								"file_name": file_name,
								"attached_to_doctype": "WhatsApp Message",
								"attached_to_name": message_doc.name,
								"content": file_data,
								"attached_to_field": "attach"
							}
						).save(ignore_permissions=True)


						message_doc.attach = file.file_url
						message_doc.save()
			elif message_type == "button":
				frappe.get_doc({
					"doctype": "WhatsApp Message",
					"type": "Incoming",
					"from": message['from'],
					"message": message['button']['text'],
					"message_id": message['id'],
					"reply_to_message_id": reply_to_message_id,
					"is_reply": is_reply,
					"content_type": message_type,
					"profile_name":sender_profile_name
				}).insert(ignore_permissions=True)
			elif message_type == "unsupported":
				# Handle unsupported messages - save for reference and debugging
				error_details = message.get('errors', [])
				
				frappe.get_doc({
					"doctype": "WhatsApp Message",
					"type": "Incoming", 
					"from": message['from'],
					"message": json.dumps(error_details),
					"message_id": message['id'],
					"reply_to_message_id": reply_to_message_id,
					"content_type": message_type,
					"profile_name": sender_profile_name
				}).insert(ignore_permissions=True)
			else:
				frappe.get_doc({
					"doctype": "WhatsApp Message",
					"type": "Incoming",
					"from": message['from'],
					"message_id": message['id'],
					"message": message[message_type].get(message_type),
					"content_type" : message_type,
					"profile_name":sender_profile_name
				}).insert(ignore_permissions=True)

	else:
		changes = None
		try:
			changes = data["entry"][0]["changes"][0]
		except KeyError:
			changes = data["entry"]["changes"][0]
		update_status(changes)
	return

def update_status(data):
	"""Update status hook."""
	if data.get("field") == "message_template_status_update":
		update_template_status(data['value'])

	elif data.get("field") == "messages":
		update_message_status(data['value'])

def update_template_status(data):
	"""Update template status."""
	frappe.db.sql(
		"""UPDATE `tabWhatsApp Templates`
		SET status = %(event)s
		WHERE id = %(message_template_id)s""",
		data
	)

def update_message_status(data):
	"""Enqueue the WhatsApp delivery-status update off the request path.

	Meta delivers sent/delivered/read (+ retries) as separate webhooks for the same message; writing it
	inline via doc.save() raced the optimistic-lock SELECT ... FOR UPDATE under concurrent callbacks and
	produced MariaDB 1020 ("Record has changed since last read"). We enqueue a direct-UPDATE job (after the
	request commits) so the webhook returns 200 to Meta immediately and the write can't raise 1020.
	"""
	statuses = data.get("statuses")
	if not statuses:
		return
	status_info = statuses[0]
	frappe.enqueue(
		"frappe_whatsapp.utils.webhook.apply_whatsapp_message_status",
		queue=_whatsapp_status_queue(),
		enqueue_after_commit=True,
		message_id=status_info["id"],
		status=status_info["status"],
		conversation=status_info.get("conversation", {}).get("id"),
	)


def _whatsapp_status_queue():
	"""Prefer a dedicated 'whatsapp' queue, falling back to 'short' until that queue is provisioned in
	common_site_config['workers']. frappe.enqueue validates the queue name and raises for an unconfigured
	one, so we choose a valid queue ourselves. get_queues_timeout() only reads the in-memory site conf, so
	it is cheap to call per webhook.
	"""
	return "whatsapp" if "whatsapp" in get_queues_timeout() else "short"


def apply_whatsapp_message_status(message_id, status, conversation=None):
	"""Background job: apply a WhatsApp delivery-status update under READ COMMITTED.

	MariaDB snapshot isolation (innodb_snapshot_isolation=ON) raises ER_CHECKREAD (1020) on a plain UPDATE
	when another connection committed a change to this WhatsApp Message row after this transaction's read
	view -- e.g. the outbound-send flow finalising the message, or a chat "mark as read". Running the write
	under READ COMMITTED turns that conflict detection off (last-writer-wins, which is fine for a status
	field), so the UPDATE just applies. A transaction's isolation is fixed when it starts and Frappe keeps a
	transaction continuously open, so SET SESSION (which only affects the *next* transaction) is followed by
	a commit to roll onto a fresh RC transaction; REPEATABLE READ is restored in `finally` because this job
	may share a worker with others. Non-fatal + idempotent: a status for a message we do not store no-ops,
	and re-delivered callbacks just re-apply.
	"""
	try:
		# Run the write under READ COMMITTED so snapshot isolation does not raise 1020 (see docstring). SET
		# SESSION is allowed mid-transaction; the commit then rolls us onto a fresh transaction under RC.
		frappe.db.sql("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
		frappe.db.commit()

		name = frappe.db.get_value("WhatsApp Message", {"message_id": message_id})
		if not name:
			# Status for a message not stored here (e.g. sent from another system) — nothing to update.
			return
		values = {"status": status}
		if conversation:
			values["conversation_id"] = conversation
		frappe.db.set_value("WhatsApp Message", name, values)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			title="apply_whatsapp_message_status failed",
			message=f"message_id={message_id}, status={status}\n{frappe.get_traceback()}",
		)
	finally:
		# This job may run on the shared `short` worker until a dedicated `whatsapp` worker exists; restore
		# the connection's default isolation so other jobs on it are not left on READ COMMITTED.
		frappe.db.sql("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
		frappe.db.commit()