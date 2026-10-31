// Copyright (c) 2022, Shridhar Patil and contributors
// For license information, please see license.txt

frappe.ui.form.on('WhatsApp Templates', {
	refresh: function(frm) {
		// Meta's edit limit note, built on the server in the user's time zone.
		const lock = frm.doc.__onload && frm.doc.__onload.meta_edit_lock;
		if (frm.is_new() || !lock) return;

		frm.set_intro(lock.message, lock.color);
		if (lock.indicator) {
			frm.page.set_indicator(lock.indicator, lock.color);
		}
	}
});
