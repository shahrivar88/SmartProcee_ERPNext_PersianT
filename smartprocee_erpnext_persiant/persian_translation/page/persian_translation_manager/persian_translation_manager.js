frappe.pages["persian-translation-manager"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "مدیریت ترجمه فارسی",
		single_column: true,
	});
	frappe.persian_translation_manager = new PersianTranslationManager(page);
};

const PAGE_LENGTHS = [20, 50, 100];
const VIEW_SETTINGS = "persian-translation-manager";
const COLUMN_IDS = ["app", "origin", "source_text", "context", "current_translation", "new_translation"];
const MIN_COLUMN_WIDTH = 40;
const MAX_COLUMN_WIDTH = 1600;

class PersianTranslationManager {
	constructor(page) {
		this.page = page;
		this.method =
			"smartprocee_erpnext_persiant.persian_translation.page.persian_translation_manager.persian_translation_manager";
		this.start = 0;
		this.page_length = 50;
		this.total = 0;
		this.rows = [];
		this.column_widths = {};
		this._widths_json = "{}";
		this.ready = false;
		this.make();
		this.ready = true;
		this.load_column_widths().then(
			() => this.load(),
			() => this.load()
		);
	}

	make() {
		this.page.set_primary_action("ذخیره", () => this.save());
		this.page.add_inner_button("اسکن متون", () => this.scan(), "عملیات");
		this.page.add_inner_button("خروجی اکسل", () => this.export_excel(), "عملیات");
		this.page.add_inner_button("ورود از اکسل", () => this.import_excel(), "عملیات");
		this.page.add_inner_button("انتشار ترجمه‌ها در بسته فارسی", () => this.publish(), "عملیات");

		this.search_field = this.page.add_field({
			label: "جستجو",
			fieldname: "search",
			fieldtype: "Data",
			placeholder: "متن انگلیسی یا ترجمه فارسی",
		});
		this.app_field = this.page.add_field({
			label: "برنامه",
			fieldname: "app",
			fieldtype: "Select",
			options: [{ label: "همه برنامه‌ها", value: "" }],
			change: () => this.on_filter_change(),
		});
		this.status_field = this.page.add_field({
			label: "وضعیت",
			fieldname: "status",
			fieldtype: "Select",
			options: [
				{ label: "همه", value: "all" },
				{ label: "ترجمه‌شده", value: "translated" },
				{ label: "ترجمه‌نشده", value: "untranslated" },
				{ label: "تغییرکرده", value: "changed" },
			],
			default: "all",
			change: () => this.on_filter_change(),
		});
		this.page_length_field = this.page.add_field({
			label: "تعداد در هر صفحه",
			fieldname: "page_length",
			fieldtype: "Select",
			options: PAGE_LENGTHS.map((value) => ({ label: String(value), value: String(value) })),
			default: "50",
			change: () => this.on_filter_change(),
		});
		this.page_length_field.set_value("50");
		this.status_field.set_value("all");

		this.search_field.$input.on(
			"input",
			frappe.utils.debounce(() => this.on_filter_change(), 400)
		);

		this.$body = $('<div class="persian-translation-manager"></div>').appendTo(this.page.main);
		this.$status = $('<div class="text-muted ptm-status-line"></div>').appendTo(this.$body);
		this.$grid = $('<div class="ptm-grid"></div>').appendTo(this.$body);
		this.$pager = $('<div class="ptm-pager"></div>').appendTo(this.$body);
		this.ensure_style();
		this.bind_column_width_persistence();
	}

	load_column_widths() {
		return frappe.model.user_settings.get(VIEW_SETTINGS).then((settings) => {
			this.column_widths = this.clean_widths((settings || {}).column_widths);
			this._widths_json = JSON.stringify(this.column_widths);
		});
	}

	clean_widths(widths) {
		const cleaned = {};
		COLUMN_IDS.forEach((column_id) => {
			const width = cint(widths && widths[column_id]);
			if (width >= MIN_COLUMN_WIDTH && width <= MAX_COLUMN_WIDTH) {
				cleaned[column_id] = width;
			}
		});
		return cleaned;
	}

	bind_column_width_persistence() {
		$(document).off("mouseup.ptm-column-width");
		$(document).on("mouseup.ptm-column-width", () => {
			if (!this._resizing_column) {
				return;
			}
			this._resizing_column = false;
			this.remember_column_widths();
		});
		this.$grid.on("mousedown", ".dt-cell__resize-handle", () => {
			this._resizing_column = true;
		});
		this.$grid.on("dblclick", ".dt-cell__resize-handle", () => {
			setTimeout(() => this.remember_column_widths(), 0);
		});
	}

	remember_column_widths() {
		if (!this.datatable || !this.datatable.datamanager) {
			return;
		}
		const widths = {};
		this.datatable.datamanager.getColumns().forEach((column) => {
			if (!COLUMN_IDS.includes(column.id)) {
				return;
			}
			const width = Math.round(Number(column.width));
			if (width >= MIN_COLUMN_WIDTH && width <= MAX_COLUMN_WIDTH) {
				widths[column.id] = width;
			}
		});
		const serialized = JSON.stringify(widths);
		if (!Object.keys(widths).length || serialized === this._widths_json) {
			return;
		}
		this.column_widths = widths;
		this._widths_json = serialized;
		if (this.datatable && this.datatable.options) {
			this.datatable.options.layout = "fixed";
		}
		frappe.call({
			method: this.method + ".save_column_widths",
			args: { column_widths: widths },
		});
	}

	reapply_column_widths() {
		if (!this.datatable || !this.datatable.columnmanager) {
			return;
		}
		this.datatable.datamanager.getColumns().forEach((column) => {
			if (!COLUMN_IDS.includes(column.id)) {
				return;
			}
			this.datatable.columnmanager.setColumnHeaderWidth(column.colIndex);
			this.datatable.columnmanager.setColumnWidth(column.colIndex);
		});
	}

	ensure_style() {
		const css = `
				.persian-translation-manager { margin-top: var(--margin-sm); }
				.persian-translation-manager .ptm-status-line { margin-bottom: var(--margin-sm); }
				.persian-translation-manager .ptm-grid { min-height: 240px; }
				.persian-translation-manager .dt-scrollable {
					border: 1px solid var(--border-color);
					border-radius: var(--border-radius-md);
					background: var(--card-bg);
				}
				.persian-translation-manager .dt-cell__content {
					white-space: normal;
					line-height: 1.5;
				}
				.persian-translation-manager .dt-cell--header .dt-cell__content {
					text-align: center !important;
				}
				.persian-translation-manager .dt-scrollable .dt-cell--col-0 .dt-cell__content,
				.persian-translation-manager .dt-scrollable .dt-cell--col-1 .dt-cell__content,
				.persian-translation-manager .dt-scrollable .dt-cell--col-2 .dt-cell__content,
				.persian-translation-manager .dt-scrollable .dt-cell--col-3 .dt-cell__content {
					direction: ltr;
					text-align: left;
				}
				.persian-translation-manager .dt-scrollable .dt-cell--col-4 .dt-cell__content,
				.persian-translation-manager .dt-scrollable .dt-cell--col-5 .dt-cell__content {
					direction: rtl;
					text-align: right;
					font-size: var(--text-sm);
				}
				.persian-translation-manager .ptm-editor {
					width: 100%;
					min-height: 64px;
					resize: vertical;
					direction: rtl;
					text-align: right;
					font-size: var(--text-sm);
				}
				.persian-translation-manager .list-paging-area { margin-top: var(--margin-sm); }
				`;
		const existing = document.getElementById("ptm-style");
		if (existing) {
			existing.textContent = css;
			return;
		}
		$("<style id='ptm-style'></style>").text(css).appendTo(document.head);
	}

	on_filter_change() {
		if (!this.ready || this._refreshing_apps) {
			return;
		}
		this.page_length = cint(this.page_length_field.get_value()) || 50;
		this.start = 0;
		this.load();
	}

	filters() {
		return {
			search: this.search_field.get_value() || "",
			app: this.app_field.get_value() || "",
			status: this.status_field.get_value() || "all",
			start: this.start,
			page_length: cint(this.page_length_field.get_value()) || this.page_length,
		};
	}

	refresh_apps(apps) {
		const options = [{ label: "همه برنامه‌ها", value: "" }].concat(
			(apps || []).map((app) => ({ label: app, value: app }))
		);
		const previous = this.app_field.df.options || [];
		const same =
			previous.length === options.length &&
			previous.every((item, index) => (item.value || "") === (options[index].value || ""));
		if (same) {
			return;
		}
		const current = this.app_field.get_value() || "";
		this._refreshing_apps = true;
		this.app_field.df.options = options;
		this.app_field.refresh();
		this.app_field.set_value(current);
		setTimeout(() => {
			this._refreshing_apps = false;
		}, 0);
	}

	load() {
		const token = (this._token = (this._token || 0) + 1);
		frappe.call({
			method: this.method + ".get_rows",
			args: this.filters(),
			callback: (response) => {
				if (token !== this._token) {
					return;
				}
				const data = response.message || {};
				this.rows = data.rows || [];
				this.total = data.total || 0;
				this.page_length = cint(this.page_length_field.get_value()) || this.page_length;
				this.refresh_apps(data.apps || []);
				this.render(data.scan || {});
			},
		});
	}

	columns() {
		const text = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
		const width = (column_id, fallback) => this.column_widths[column_id] || fallback;
		return [
			{ id: "app", name: "برنامه", width: width("app", 110), editable: false, resizable: true, format: text },
			{
				id: "origin",
				name: "ماژول / مسیر",
				width: width("origin", 160),
				editable: false,
				resizable: true,
				format: text,
			},
			{
				id: "source_text",
				name: "متن اصلی انگلیسی",
				width: width("source_text", 200),
				editable: false,
				resizable: true,
				format: text,
			},
			{
				id: "context",
				name: "زمینه (Context)",
				width: width("context", 140),
				editable: false,
				resizable: true,
				format: text,
			},
			{
				id: "current_translation",
				name: "ترجمه فعلی فارسی",
				width: width("current_translation", 180),
				editable: false,
				resizable: true,
				format: text,
			},
			{
				id: "new_translation",
				name: "ترجمه جدید",
				width: width("new_translation", 200),
				editable: true,
				resizable: true,
				format: text,
			},
		];
	}

	render(scan) {
		const scan_text = scan.message
			? `وضعیت اسکن: ${scan.message}`
			: "برای به‌روزرسانی فهرست، اسکن متون را اجرا کنید.";
		this.$status.text(`${scan_text} · ${this.total} متن`);
		this.render_pager();
		if (this.datatable) {
			this.datatable.destroy();
			this.datatable = null;
		}
		this.$grid.empty();
		if (!this.rows.length) {
			this.$grid.append(
				$("<div class='text-muted' style='padding: 12px;'></div>").text("ردیفی برای نمایش نیست.")
			);
			return;
		}
		const data = this.rows.map((row) => ({
			app: row.app || "",
			origin: [row.module, row.source_path].filter(Boolean).join(" — "),
			source_text: row.source_text || "",
			context: row.context || "",
			current_translation: row.current_translation || "",
			new_translation: row.current_translation || "",
		}));
		this.datatable = new frappe.DataTable(this.$grid.get(0), {
			columns: this.columns(),
			data,
			layout: Object.keys(this.column_widths).length ? "fixed" : "ratio",
			serialNoColumn: false,
			checkboxColumn: false,
			inlineFilters: false,
			clusterize: false,
			dynamicRowHeight: true,
			cellHeight: 44,
			minimumColumnWidth: MIN_COLUMN_WIDTH,
			disableReorderColumn: true,
			pasteFromClipboard: false,
			noDataMessage: "ردیفی برای نمایش نیست.",
			direction: document.dir === "rtl" ? "rtl" : "ltr",
			translations: frappe.utils.datatable.get_translations(),
			events: {
				onSortColumn: () => this.reapply_column_widths(),
			},
			getEditor: (colIndex, rowIndex, value, parent) =>
				this.translation_editor(value, parent, colIndex, rowIndex),
		});
	}

	translation_editor(value, parent, colIndex, rowIndex) {
		const input = document.createElement("textarea");
		input.className = "form-control ptm-editor";
		input.value = value || "";
		parent.appendChild(input);
		input.addEventListener("blur", () => {
			this.write_cell(colIndex, rowIndex, input.value);
		});
		return {
			initValue(next) {
				input.value = next || "";
				input.focus();
			},
			setValue(next) {
				input.value = next || "";
			},
			getValue() {
				return input.value;
			},
		};
	}

	write_cell(colIndex, rowIndex, value) {
		const manager = this.datatable && this.datatable.cellmanager;
		if (!manager || colIndex == null || rowIndex == null) {
			return;
		}
		manager.updateCell(colIndex, rowIndex, value, true);
		const record = this.datatable.datamanager.data[rowIndex];
		if (record) {
			record.new_translation = value;
		}
	}

	commit_open_editor() {
		const manager = this.datatable && this.datatable.cellmanager;
		if (!manager || !manager.$editingCell || !manager.currentCellEditor) {
			return;
		}
		const meta = manager.$editingCell.dataset || {};
		const value = manager.currentCellEditor.getValue();
		if (value && typeof value.then === "function") {
			return;
		}
		this.write_cell(meta.colIndex, meta.rowIndex, value);
		manager.deactivateEditing(false);
	}

	new_translation_at(index) {
		if (!this.datatable) {
			return "";
		}
		const columns = this.datatable.datamanager.getColumns();
		const colIndex = columns.findIndex((column) => column.id === "new_translation");
		const row = this.datatable.datamanager.getRow(index);
		const cell = row && row[colIndex];
		if (cell == null) {
			return "";
		}
		if (typeof cell === "string") {
			return cell;
		}
		return cell.content == null ? "" : String(cell.content);
	}

	render_pager() {
		const page_length = cint(this.page_length_field.get_value()) || this.page_length;
		const page_number = Math.floor(this.start / page_length) + 1;
		const pages = Math.max(Math.ceil(this.total / page_length), 1);
		this.$pager.empty();
		const area = $(`
			<div class="list-paging-area level">
				<div class="level-left text-muted ptm-page-text"></div>
				<div class="level-right">
					<div class="btn-group">
						<button type="button" class="btn btn-default btn-sm ptm-prev">قبلی</button>
						<button type="button" class="btn btn-default btn-sm ptm-next">بعدی</button>
					</div>
				</div>
			</div>
		`);
		area.find(".ptm-page-text").text(`صفحه ${page_number} از ${pages}`);
		const prev = area.find(".ptm-prev");
		const next = area.find(".ptm-next");
		prev.prop("disabled", this.start <= 0);
		next.prop("disabled", this.start + page_length >= this.total);
		prev.on("click", () => {
			this.start = Math.max(this.start - page_length, 0);
			this.load();
		});
		next.on("click", () => {
			this.start += page_length;
			this.load();
		});
		this.$pager.append(area);
	}

	save() {
		this.commit_open_editor();
		const rows = [];
		let blanks = 0;
		this.rows.forEach((row, index) => {
			const value = (this.new_translation_at(index) || "").trim();
			const current = (row.current_translation || "").trim();
			if (!value) {
				if (current) {
					blanks += 1;
				}
				return;
			}
			if (value === current) {
				return;
			}
			rows.push({
				source_text: row.source_text,
				context: row.context || "",
				translated_text: value,
			});
		});
		if (blanks) {
			frappe.show_alert({
				message: "خانه‌های خالی، ترجمه فعلی را حذف نمی‌کنند.",
				indicator: "orange",
			});
		}
		if (!rows.length) {
			frappe.show_alert({ message: "تغییری برای ذخیره نیست.", indicator: "blue" });
			return;
		}
		frappe.call({
			method: this.method + ".save_translations",
			args: { rows },
			freeze: true,
			callback: (response) => {
				const saved = (response.message || {}).saved || 0;
				frappe.show_alert({ message: `${saved} ترجمه ذخیره شد.`, indicator: "green" });
				this.load();
			},
		});
	}

	scan() {
		frappe.call({
			method: this.method + ".start_scan",
			callback: () => {
				frappe.show_alert({ message: "اسکن در پس‌زمینه شروع شد.", indicator: "blue" });
				this.poll_scan();
			},
		});
	}

	poll_scan() {
		frappe.call({
			method: this.method + ".scan_status",
			callback: (response) => {
				const status = response.message || {};
				if (status.status === "running" || status.status === "queued") {
					setTimeout(() => this.poll_scan(), 2000);
					return;
				}
				if (status.message) {
					frappe.show_alert({
						message: status.message,
						indicator: status.status === "error" ? "red" : "green",
					});
				}
				this.start = 0;
				this.load();
			},
		});
	}

	export_excel() {
		const { start, page_length, ...args } = this.filters();
		const params = new URLSearchParams();
		Object.keys(args).forEach((key) => {
			if (args[key] !== undefined && args[key] !== null && args[key] !== "") {
				params.set(key, args[key]);
			}
		});
		window.open(frappe.urllib.get_full_url("/api/method/" + this.method + ".export_excel?" + params.toString()));
	}

	import_excel() {
		new frappe.ui.FileUploader({
			allow_multiple: false,
			restrictions: { allowed_file_types: [".xlsx"] },
			on_success: (file) => {
				frappe.call({
					method: this.method + ".preview_import",
					args: { file_url: file.file_url },
					freeze: true,
					callback: (response) => this.confirm_import(file.file_url, response.message || {}),
				});
			},
		});
	}

	confirm_import(file_url, summary) {
		const message = [
			`تعداد ردیف‌های فایل: ${summary.file_rows || 0}`,
			`بدون تغییر: ${summary.unchanged || 0}`,
			`ترجمه جدید: ${summary.new || 0}`,
			`ترجمه تغییر یافته: ${summary.changed || 0}`,
			`خطادار: ${summary.error_count || 0}`,
		].join("<br>");
		const error_text = (summary.errors || [])
			.slice(0, 8)
			.map((error) => `ردیف ${error.row}: ${error.message}`)
			.join("<br>");
		frappe.confirm(
			message +
				(error_text ? "<br><br>" + error_text : "") +
				"<br><br>فقط ردیف‌های معتبرِ جدید یا تغییر یافته اعمال می‌شوند.",
			() => {
				frappe.call({
					method: this.method + ".apply_import",
					args: { file_url },
					freeze: true,
					callback: (response) => {
						const saved = (response.message || {}).saved || 0;
						frappe.show_alert({ message: `${saved} ترجمه از اکسل اعمال شد.`, indicator: "green" });
						this.load();
					},
				});
			}
		);
	}

	publish() {
		frappe.confirm(
			"فقط ترجمه‌هایی که متن اصلی‌شان متعلق به Frappe یا ERPNext است در فایل fa.csv همین برنامه ادغام می‌شوند. ترجمهٔ برنامه‌های سفارشی و شخص ثالث فقط در همین سایت باقی می‌ماند. ردیف‌های قبلی کاتالوگ حذف نمی‌شوند.",
			() => {
				frappe.call({
					method: this.method + ".publish_catalogue",
					freeze: true,
					callback: (response) => {
						frappe.msgprint({
							title: "نتیجهٔ انتشار",
							message: publish_report(response.message || {}),
							indicator: (response.message || {}).withheld ? "orange" : "green",
						});
						this.load();
					},
				});
			}
		);
	}
}

function publish_report(result) {
	let html = `<p>به‌روزرسانی: ${result.updated || 0}، افزوده‌شده: ${result.appended || 0}</p>`;
	if (!result.withheld) return html;
	html += `<p>${frappe.utils.escape_html(result.withheld_message || "")}</p><ul>`;
	for (const row of result.withheld_sample || []) {
		const context = row.context ? ` <small>(${frappe.utils.escape_html(row.context)})</small>` : "";
		html += `<li dir="ltr">${frappe.utils.escape_html(row.source_text)}${context}</li>`;
	}
	return html + "</ul>";
}

function cint(value) {
	return parseInt(value || 0, 10) || 0;
}
