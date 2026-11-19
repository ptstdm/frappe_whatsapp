// Copyright (c) 2022, Shridhar Patil and contributors
// For license information, please see license.txt

frappe.ui.form.on('WhatsApp Templates', {
	validate: function (frm) {
		const example = "Ravi,10 AM,04 Oct 2026 07:24 PM";

		// a media header needs a sample file.
		if (["IMAGE", "DOCUMENT"].includes(frm.doc.header_type) && !frm.doc.sample) {
			frappe.throw(__("Header Type {0} needs a sample file for Meta review. Attach one in Sample.", [frm.doc.header_type]));
		}

		// Template Label must make a valid Meta name (new docs).
		if (frm.is_new()) {
			const actual = (frm.doc.template_name || "").trim().toLowerCase().replace(/ /g, "_");
			if (!actual || !/^[a-z0-9_]+$/.test(actual)) {
				frappe.throw(__("Template Label can use only letters, numbers and spaces. Remove any other characters (e.g. hyphens)."));
			}
		}

		// TEXT header with a variable needs a Sample. Only enforce
		if (frm.is_new() && frm.doc.header_type === "TEXT" && /\{\{\s*\d+\s*\}\}/.test(frm.doc.header || "") && !frm.doc.sample) {
			frappe.throw(__("The Header text contains a variable, so a Sample value is required."));
		}

		(frm.doc.buttons || []).forEach((btn, i) => {
			const n = i + 1;
			if (btn.button_type === "Call Phone" && !btn.phone_number) {
				frappe.throw(__("Button {0} (Call Phone): Phone Number is required.", [n]));
			}
			if (btn.button_type === "Visit Website") {
				if (!btn.website_url) {
					frappe.throw(__("Button {0} (Visit Website): Website URL is required.", [n]));
				}
				if (btn.url_type === "Dynamic") {
					if (!/\{\{\s*\d+\s*\}\}/.test(btn.website_url || "")) {
						frappe.throw(__("Button {0} (Visit Website, Dynamic): the URL must contain a variable placeholder.", [n]));
					}
					if (!btn.example_url) {
						frappe.throw(__("Button {0} (Visit Website, Dynamic): an Example URL is required.", [n]));
					}
				}
			}
			if (btn.button_type === "Flow" && !btn.flow) {
				frappe.throw(__("Button {0} (Flow): select a WhatsApp Flow.", [n]));
			}
		});

		
		const body = frm.doc.template || "";
		const nums = (body.match(/\{\{\s*\d+\s*\}\}/g) || []).map(m => parseInt(m.replace(/\D/g, ""), 10));
		const distinct = Array.from(new Set(nums)).sort((a, b) => a - b);
		const n = distinct.length;

		for (let i = 0; i < n; i++) {
			if (distinct[i] !== i + 1) {
				frappe.throw(__("Template variables must be numbered sequentially starting at {{1}} with no gaps."));
			}
		}

		const raw = frm.doc.sample_values || "";
		if (n === 0) {
			if (raw.trim()) {
				frappe.throw(__("The template body has no variables, so Sample Values must be empty."));
			}
			frm.doc.sample_values = "";
			return;
		}
		if (/[\r\n]/.test(raw)) {
			frappe.throw(__("Sample Values must be on a single line. Write one value per variable, separated by commas. Example: ") + example);
		}
		const values = raw.split(",").map(v => v.trim());
		if (!raw.trim() || values.length !== n || values.some(v => v === "")) {
			const got = raw.trim() ? values.length : 0;
			frappe.throw(__("The template has {0} variable(s) but Sample Values has {1}. Write one value per variable on one line, separated by commas (no comma inside a value). Example: {2}", [n, got, example]));
		}
	}
});
