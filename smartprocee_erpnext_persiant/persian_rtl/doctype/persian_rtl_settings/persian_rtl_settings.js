// Persian RTL Settings.
//
// The form itself is the standard Frappe Single form. This file only adds one
// read-only section, "مدیریت سازگاری راست‌به‌چپ", which lists every installed app
// with the RTL state the runtime would give it. The list is discovered on the
// server, so a newly installed app shows up without a client change.

frappe.ui.form.on("Persian RTL Settings", {
	refresh(frm) {
		render_compat_section(frm);
		mark_unsupported_font_option(frm);
		frm.add_custom_button(__("بررسی سازگاری"), () => open_compatibility_report(frm));
	},
});

// An adapter that cannot take the system font shows only a read-only label in
// place of the option, both in the list cell and in the inline editor. The
// grid builds the inline editor from the row's own docfield copy, so that copy
// becomes an HTML field; the stored value stays untouched and the server keeps
// forcing it to 0.
function mark_unsupported_font_option(frm) {
	const grid = frm.fields_dict.adapters.grid;
	grid.update_docfield_property("use_system_font", "formatter", (value, df, options, doc) => {
		if (doc && !cint(doc.supports_system_font)) {
			return unsupported_font_label();
		}
		return `<input type="checkbox" disabled class="disabled-${cint(value) ? "selected" : "deselected"}">`;
	});
	for (const row of grid.grid_rows || []) {
		if (cint(row.doc.supports_system_font)) {
			continue;
		}
		const df = row.docfields.find((field) => field.fieldname === "use_system_font");
		Object.assign(df, { fieldtype: "HTML", options: unsupported_font_label(), read_only: 1 });
	}
	grid.refresh();
}

function unsupported_font_label() {
	return `<span class="text-muted small">${__("پشتیبانی نمی‌شود")}</span>`;
}

function render_compat_section(frm) {
	frappe
		.call({
			method: "smartprocee_erpnext_persiant.persian_rtl.diagnostics.compat_report",
			type: "GET",
		})
		.then((response) => {
			const data = response.message || {};
			const html = `<div id="ptm-compat">${section_html(data)}</div>`;
			// A form refresh rebuilds the dashboard; drop the previous copy first so
			// the section is never rendered twice.
			$(frm.dashboard.wrapper).find("#ptm-compat").closest(".form-dashboard-section").remove();
			frm.dashboard.add_section(html, __("مدیریت سازگاری راست‌به‌چپ"));
		});
}

function section_html(data) {
	const rows = (data.apps || []).map(
		(row) => `<tr>
			<td>${frappe.utils.escape_html(row.app)}</td>
			<td>${frappe.utils.escape_html(row.version || "-")}</td>
			<td>${frappe.utils.escape_html(row.interface || "-")}</td>
			<td title="${frappe.utils.escape_html(row.reason_label || row.reason || "")}">${frappe.utils.escape_html(row.state_label || row.state || "-")}</td>
			<td>${frappe.utils.escape_html(row.adapter_id || "—")}</td>
			<td>${row.enabled ? __("بله") : __("خیر")}</td>
		</tr>`
	);
	const warnings = (data.warnings || []).map(
		(row) => `<li><b>${frappe.utils.escape_html(row.adapter_id)}</b>: ${frappe.utils.escape_html(row.message)}</li>`
	);
	return `<table class="table table-bordered" style="margin-bottom: 8px;">
			<thead><tr>
				<th>${__("برنامه")}</th><th>${__("نسخه")}</th><th>${__("نوع رابط")}</th>
				<th>${__("وضعیت RTL")}</th><th>${__("آداپتور")}</th><th>${__("فعال")}</th>
			</tr></thead>
			<tbody>${rows.join("")}</tbody>
		</table>
		${warnings.length ? `<hr><b>${__("هشدارها")}</b><ul>${warnings.join("")}</ul>` : ""}`;
}

function open_compatibility_report(frm) {
	frappe.call({
		method: "smartprocee_erpnext_persiant.persian_rtl.diagnostics.report",
		freeze: true,
		freeze_message: __("در حال بررسی"),
	}).then((response) => {
		const data = response.message || {};
		frappe.msgprint({
			title: __("گزارش سازگاری راست‌به‌چپ"),
			indicator: (data.warnings || []).some((row) => row.level === "error") ? "red" : "green",
			message: adapter_report_html(data),
			wide: true,
		});
	});
}

function adapter_report_html(data) {
	const rows = (data.rows || []).map((row) => {
		const version = row.version ? `${row.target_app} ${row.version}` : row.target_app;
		const step = row.eligible ? __("فعال") : frappe.utils.escape_html(row.reason || "-");
		return `<tr>
			<td>${frappe.utils.escape_html(row.title)}</td>
			<td>${frappe.utils.escape_html(version)}</td>
			<td>${frappe.utils.escape_html(row.state)}</td>
			<td>${frappe.utils.escape_html(step)}</td>
			<td>${frappe.utils.escape_html((row.routes || []).join("، "))}</td>
		</tr>`;
	});
	const warnings = (data.warnings || []).map(
		(row) => `<li><b>${frappe.utils.escape_html(row.adapter_id)}</b>: ${frappe.utils.escape_html(row.message)}</li>`
	);
	return `<table class="table table-bordered">
			<thead><tr>
				<th>${__("آداپتور")}</th><th>${__("نسخه")}</th>
				<th>${__("وضعیت")}</th><th>${__("تصمیم")}</th><th>${__("مسیرها")}</th>
			</tr></thead>
			<tbody>${rows.join("")}</tbody>
		</table>
		${warnings.length ? `<hr><b>${__("هشدارها")}</b><ul>${warnings.join("")}</ul>` : ""}`;
}
