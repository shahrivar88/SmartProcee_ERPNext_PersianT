/* Display-only Persian labels for Account names. Stored values stay English. */
frappe.provide("frappe.treeview_settings");
frappe.provide("frappe.listview_settings");

function persianizer_fa() {
	return String((frappe.boot && frappe.boot.lang) || "").indexOf("fa") === 0;
}

function persianizer_account_label(value) {
	if (!value || !persianizer_fa()) {
		return value;
	}
	const translated = __(value);
	return translated || value;
}

frappe.ui.form.on("Account", {
	refresh(frm) {
		const label = persianizer_account_label(frm.doc.account_name);
		if (label && label !== frm.docname) {
			frm.page.set_title(label);
		}
	},
});

(function () {
	const settings = frappe.listview_settings.Account || {};
	const previous = settings.formatter;
	settings.formatter = function (value, df, data, column) {
		if (persianizer_fa() && df && df.fieldname === "account_name") {
			return persianizer_account_label(value);
		}
		return previous ? previous(value, df, data, column) : value;
	};
	frappe.listview_settings.Account = settings;
})();

(function () {
	const settings = frappe.treeview_settings.Account || {};
	const previous = settings.onrender;
	settings.onrender = function (node) {
		if (previous) {
			previous.call(this, node);
		}
		if (!persianizer_fa() || !node || !node.data) {
			return;
		}
		const source = node.data.account_name || node.data.title;
		const label = persianizer_account_label(source);
		if (!label || label === source) {
			return;
		}
		const $label = $(node.parent).find("> .tree-link .tree-label, > .tree-link a").first();
		if ($label.length) {
			$label.text(label);
		}
	};
	frappe.treeview_settings.Account = settings;
})();
