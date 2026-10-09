const PAGE_NAME = "persian-translation-manager";

frappe.pages[PAGE_NAME].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "مدیریت ترجمه فارسی",
		single_column: true,
	});
	frappe.persian_translation_manager = new PersianTranslationManager(page);
};

frappe.pages[PAGE_NAME].on_page_show = function () {
	if (frappe.persian_translation_manager) {
		frappe.persian_translation_manager.resume_deferred();
	}
};

/* Frappe keeps a visited page alive after the user leaves it, so a poll timer or
   a late callback would otherwise call this page's endpoints from Sales Invoice,
   Stock or any other route. Every such server call checks this first. */
function on_manager_page() {
	return frappe.get_route()[0] === PAGE_NAME;
}

const PAGE_LENGTHS = [20, 50, 100];
const VIEW_SETTINGS = "persian-translation-manager";
// The order here is the column order on screen, and the styling below is built
// from it, so a column can be moved without hunting for CSS indices.
const COLUMN_IDS = ["app", "kind", "location", "source_text", "translation", "status"];
const LTR_COLUMNS = ["app", "source_text"];
const MIXED_COLUMNS = ["location"];
const RTL_COLUMNS = ["kind", "translation"];
const CENTER_COLUMNS = ["status"];
const SORTABLE_COLUMNS = ["app", "kind", "location", "source_text", "translation", "status"];
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
		this.sort_by = "";
		this.sort_order = "";
		this.column_widths = {};
		this._widths_json = "{}";
		// Filter controls report changes while they are being built; nothing loads
		// until the one initial request below.
		this.ready = false;
		this.make();
		this.load_column_widths().then(
			() => this.initial_load(),
			() => this.initial_load()
		);
	}

	initial_load() {
		this.ready = true;
		this.load();
	}

	make() {
		this.page.set_primary_action("ذخیره", () => this.save());
		this.page.add_inner_button("اسکن متون", () => this.scan(), "عملیات");
		this.page.add_inner_button("خروجی اکسل", () => this.export_excel(), "عملیات");
		this.page.add_inner_button("ورود از اکسل", () => this.import_excel(), "عملیات");
		this.page.add_inner_button("صف عملیات", () => this.open_operations(), "عملیات");
		this.page.add_inner_button("نسخه‌های پشتیبان", () => this.open_snapshots(), "عملیات");
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
		this.kind_field = this.page.add_field({
			label: "نوع",
			fieldname: "kind",
			fieldtype: "Select",
			options: [{ label: "همه نوع‌ها", value: "" }],
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
		const rules = (column_ids, body) =>
			column_ids
				.map((column_id) => COLUMN_IDS.indexOf(column_id))
				.filter((index) => index >= 0)
				.map(
					(index) =>
						`.persian-translation-manager .dt-scrollable .dt-cell--col-${index} .dt-cell__content { ${body} }`
				)
				.join("\n");
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
				/* English source text and app names read left to right. */
				${rules(LTR_COLUMNS, "direction: ltr; text-align: left;")}
				/* A place can be an English document name or a Persian menu label. */
				${rules(MIXED_COLUMNS, "unicode-bidi: plaintext; text-align: start;")}
				${rules(RTL_COLUMNS, "direction: rtl; text-align: right; font-size: var(--text-sm);")}
				${rules(CENTER_COLUMNS, "text-align: center;")}
				.persian-translation-manager .ptm-status {
					font-size: var(--text-sm);
					white-space: nowrap;
				}
				.persian-translation-manager .ptm-status--draft,
				.persian-translation-manager .ptm-status--changed {
					color: var(--orange-600, #ea580c);
					font-weight: 600;
				}
				.persian-translation-manager .ptm-status--untranslated { color: var(--text-muted); }
				.persian-translation-manager .ptm-editor {
					width: 100%;
					min-height: 64px;
					resize: vertical;
					direction: rtl;
					text-align: right;
					font-size: var(--text-sm);
				}
				.persian-translation-manager .list-paging-area { margin-top: var(--margin-sm); }
				.ptm-report { max-height: 60vh; overflow-y: auto; padding-inline-end: var(--padding-sm); }
				.ptm-report .ptm-section { margin-block-start: var(--margin-md); }
				.ptm-report .ptm-section-head {
					font-weight: 600;
					border-block-end: 1px solid var(--border-color);
					padding-block-end: var(--padding-xs);
					margin-block-end: var(--padding-sm);
				}
				.ptm-report .ptm-group {
					border: 1px solid var(--border-color);
					border-radius: var(--border-radius-md);
					padding: var(--padding-sm);
					margin-block-end: var(--padding-sm);
					background: var(--card-bg);
				}
				.ptm-report .ptm-group-label {
					font-family: var(--font-monospace, monospace);
					font-size: var(--text-sm);
					direction: ltr;
					text-align: start;
					word-break: break-word;
				}
				.ptm-report .ptm-note { color: var(--text-muted); font-size: var(--text-sm); }
				.ptm-report .ptm-choices label { display: block; margin-block: 2px; }
				.ptm-report details summary { cursor: pointer; font-size: var(--text-sm); }
				.ptm-report .ptm-targets { max-height: 140px; overflow-y: auto; }
				.ptm-report .ptm-targets label { display: block; font-size: var(--text-sm); }
				.ptm-report .ptm-row-actions {
					display: flex;
					align-items: center;
					gap: var(--padding-sm);
					margin-block-start: var(--padding-xs);
					flex-wrap: wrap;
				}
				.ptm-report .ptm-empty { color: var(--text-muted); }
				/* The operations queue, the snapshot list and a running job reuse the
				   report card look, so one visual language covers every background job. */
				.ptm-ops .ptm-group,
				.ptm-snap .ptm-group,
				.ptm-run .ptm-group {
					border: 1px solid var(--border-color);
					border-radius: var(--border-radius-md);
					padding: var(--padding-sm);
					margin-block-end: var(--padding-sm);
					background: var(--card-bg);
				}
				.ptm-ops .ptm-group-label,
				.ptm-snap .ptm-group-label {
					font-weight: 600;
				}
				.ptm-ops .ptm-note,
				.ptm-snap .ptm-note,
				.ptm-run .ptm-note { color: var(--text-muted); font-size: var(--text-sm); }
				.ptm-ops .ptm-row-actions,
				.ptm-snap .ptm-row-actions,
				.ptm-run .ptm-row-actions {
					display: flex;
					align-items: center;
					gap: var(--padding-sm);
					margin-block-start: var(--padding-xs);
					flex-wrap: wrap;
				}
				.ptm-ops, .ptm-snap { max-height: 60vh; overflow-y: auto; }
				.ptm-run-status { margin-block-end: var(--padding-xs); }
				.ptm-run-counters {
					display: flex;
					flex-wrap: wrap;
					gap: var(--padding-sm);
					margin-block-end: var(--padding-sm);
				}
				.ptm-badge {
					font-size: var(--text-sm);
					background: var(--control-bg);
					border-radius: var(--border-radius);
					padding: 2px var(--padding-xs);
				}
				.ptm-run .ptm-report { max-height: 40vh; }
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
		// A control can report a "change" that leaves every filter as it was.
		if (JSON.stringify(this.filters()) === this._requested) {
			return;
		}
		this.load();
	}

	filters() {
		return {
			search: this.search_field.get_value() || "",
			app: this.app_field.get_value() || "",
			kind: this.kind_field ? this.kind_field.get_value() || "" : "",
			status: this.status_field.get_value() || "all",
			sort_by: this.sort_by || "",
			sort_order: this.sort_order || "",
			start: this.start,
			page_length: cint(this.page_length_field.get_value()) || this.page_length,
		};
	}

	refresh_apps(apps, kinds) {
		this.refresh_select(this.app_field, "همه برنامه‌ها", apps);
		this.refresh_select(this.kind_field, "همه نوع‌ها", kinds);
	}

	refresh_select(field, all_label, values) {
		if (!field) {
			return;
		}
		const options = [{ label: all_label, value: "" }].concat(
			(values || []).map((value) => ({ label: value, value: value }))
		);
		const previous = field.df.options || [];
		const same =
			previous.length === options.length &&
			previous.every((item, index) => (item.value || "") === (options[index].value || ""));
		if (same) {
			return;
		}
		const current = field.get_value() || "";
		this._refreshing_apps = true;
		field.df.options = options;
		field.refresh();
		field.set_value(current);
		setTimeout(() => {
			this._refreshing_apps = false;
		}, 0);
	}

	/* Runs whatever was deferred while the user was on another route. */
	resume_deferred() {
		if (this.scan_pending) {
			this.poll_scan();
		} else if (this.stale) {
			this.load();
		}
	}

	load() {
		if (!on_manager_page()) {
			this.stale = true;
			return;
		}
		this.stale = false;
		const token = (this._token = (this._token || 0) + 1);
		const args = this.filters();
		this._requested = JSON.stringify(args);
		frappe.call({
			method: this.method + ".get_rows",
			args,
			error: () => {
				if (token === this._token) {
					this._requested = null;
				}
			},
			callback: (response) => {
				if (token !== this._token) {
					return;
				}
				const data = response.message || {};
				this.rows = data.rows || [];
				this.total = data.total || 0;
				this.page_length = cint(this.page_length_field.get_value()) || this.page_length;
				this.refresh_apps(data.apps || [], data.kinds || []);
				this.render(data.scan || {});
			},
		});
	}

	columns() {
		const text = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
		const width = (column_id, fallback) => this.column_widths[column_id] || fallback;
		const sortable = (column_id) => SORTABLE_COLUMNS.includes(column_id);
		return [
			{
				id: "app",
				name: "برنامه",
				width: width("app", 100),
				editable: false,
				resizable: true,
				sortable: sortable("app"),
				format: text,
			},
			{
				id: "kind",
				name: "نوع",
				width: width("kind", 110),
				editable: false,
				resizable: true,
				sortable: sortable("kind"),
				format: text,
			},
			{
				id: "location",
				name: "محل استفاده",
				width: width("location", 190),
				editable: false,
				resizable: true,
				sortable: sortable("location"),
				format: (value, row) => this.location_cell(value, row),
			},
			{
				id: "source_text",
				name: "متن اصلی",
				width: width("source_text", 220),
				editable: false,
				resizable: true,
				sortable: sortable("source_text"),
				format: text,
			},
			{
				id: "translation",
				name: "ترجمه فارسی",
				width: width("translation", 240),
				editable: true,
				resizable: true,
				sortable: sortable("translation"),
				format: text,
			},
			{
				id: "status",
				name: "وضعیت",
				width: width("status", 100),
				editable: false,
				resizable: true,
				sortable: sortable("status"),
				format: (value) => status_html(value),
			},
		];
	}

	location_cell(value, row) {
		const label = frappe.utils.escape_html(value || "");
		if (!label) {
			return frappe.utils.escape_html("نامشخص");
		}
		const extra = cint(row && row.other_locations);
		return extra ? `${label} <small class="text-muted">+${extra}</small>` : label;
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
			kind: row.kind || "",
			location: row.location || "",
			other_locations: row.other_locations || 0,
			source_text: row.source_text || "",
			translation: row.current_translation || "",
			status: row.status || "untranslated",
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
				/* frappe-datatable fires `onSortColumn` with the column object
				   (`columnmanager.sortColumn`), not with `(colIndex, sortOrder)`.
				   Reading it as an index found no column and returned early, so the
				   click only re-ordered the rows on screen. */
				onSortColumn: (column) => this.on_sort(column),
			},
			getEditor: (colIndex, rowIndex, value, parent) =>
				this.translation_editor(value, parent, colIndex, rowIndex),
		});
		this.apply_sort_indicator();
	}

	on_sort(column) {
		this.reapply_column_widths();
		const column_id = (column && column.id) || "";
		if (!SORTABLE_COLUMNS.includes(column_id)) {
			return;
		}
		/* The click has already re-ordered the rows on screen. The reload below
		   replaces that local order with the server's global order, and
		   `apply_sort_indicator` then shows the arrow for what the server did. */
		this.sort_by = column_id;
		this.sort_order = String((column && column.sortOrder) || "asc").toLowerCase() === "desc" ? "desc" : "asc";
		this.start = 0;
		this.load();
	}

	/* The arrow belongs to the DataTable, but the order belongs to the server.
	   Setting only the arrow -- never letting the table sort its own page --
	   keeps the two honest: what is on screen is the global order for this
	   column, and the header says which one it is. */
	apply_sort_indicator() {
		if (!this.datatable || !this.sort_by) {
			return;
		}
		const columns = this.datatable.datamanager.getColumns();
		const index = columns.findIndex((column) => column.id === this.sort_by);
		if (index < 0) {
			return;
		}
		columns.forEach((column) => {
			column.sortOrder = "none";
		});
		columns[index].sortOrder = this.sort_order === "desc" ? "desc" : "asc";
		this.datatable.columnmanager.refreshHeader();
		this.reapply_column_widths();
	}

	status_of(index) {
		const row = this.rows[index] || {};
		const current = (row.current_translation || "").trim();
		const source = (row.source_text || "").trim();
		const draft = (this.translation_at(index) || "").trim();
		if (draft && draft !== current) {
			return "draft";
		}
		if (row.changed) {
			return "changed";
		}
		return current && current !== source ? "translated" : "untranslated";
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
			record.translation = value;
			this.refresh_status_cell(rowIndex);
		}
	}

	refresh_status_cell(rowIndex) {
		const columns = this.datatable.datamanager.getColumns() || [];
		const colIndex = columns.findIndex((column) => column.id === "status");
		const cellmanager = this.datatable.cellmanager;
		if (colIndex < 0 || !cellmanager) {
			return;
		}
		cellmanager.updateCell(colIndex, rowIndex, status_html(this.status_of(rowIndex)), true);
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

	translation_at(index) {
		if (!this.datatable) {
			return "";
		}
		const columns = this.datatable.datamanager.getColumns();
		const colIndex = columns.findIndex((column) => column.id === "translation");
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
			const value = (this.translation_at(index) || "").trim();
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
				const result = response.message || {};
				frappe.show_alert({ message: `${result.saved || 0} ترجمه ذخیره شد.`, indicator: "green" });
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

	open_operations() {
		if (!this.operations) {
			this.operations = new PersianTranslationOperations(this);
		}
		this.operations.open();
	}

	open_snapshots() {
		if (!this.snapshots) {
			this.snapshots = new PersianTranslationSnapshots(this);
		}
		this.snapshots.open();
	}

	/* Every long job is a background operation, so the browser only watches a
	   record. These three helpers are the only place that starts or continues one. */

	watch(title, operation, on_finish) {
		if (!operation || !operation.name) {
			frappe.msgprint("عملیات ساخته نشد.");
			return null;
		}
		return new PersianTranslationRun(this, title, operation.name, { on_finish }).show();
	}

	queue(method, args, title, on_finish) {
		frappe.call({
			method: this.method + "." + method,
			args,
			freeze: true,
			callback: (response) => this.watch(title, response.message || {}, on_finish),
		});
	}

	resume(operation, on_finish) {
		frappe.call({
			method: this.method + ".operation_resume",
			args: { name: operation.name },
			freeze: true,
			callback: (response) => this.watch(operation_title(operation), response.message || {}, on_finish),
		});
	}

	show_report(operation, run) {
		const detail = operation.detail || {};
		if (operation.kind === "snapshot_preview" || operation.kind === "snapshot_restore") {
			run.render_html(restore_report_html(operation, detail.preview || {}));
		} else if (operation.kind === "import_preview") {
			run.render_html(import_preview_html(operation, detail.report || {}));
		} else {
			run.render_html(import_result_html(operation));
		}
	}

	poll_scan() {
		if (!on_manager_page()) {
			this.scan_pending = true;
			return;
		}
		this.scan_pending = false;
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
				/* The preview reads and classifies the whole workbook, so it runs in the
				   worker and this request returns as soon as the operation exists. */
				this.queue(
					"preview_import",
					{ file_url: file.file_url },
					"پیش‌نمایش ورود از اکسل",
					(operation, run) => this.preview_import_finished(file.file_url, operation, run)
				);
			},
		});
	}

	preview_import_finished(file_url, operation, run) {
		this.show_report(operation, run);
		if (operation_has_errors(operation)) {
			run.button("دانلود ردیف‌های اعمال‌نشده (اکسل)", false, () =>
				open_operation_errors(this.method, operation.name)
			);
		}
		if (operation.status !== "Completed") {
			run.note("پیش‌نمایش کامل نشد، پس چیزی روی سایت اعمال نشد.");
			return;
		}
		run.button("اعمال روی سایت", true, () => {
			run.close();
			this.queue("apply_import", { file_url }, "اعمال فایل اکسل", (applied, apply_run) =>
				this.apply_import_finished(applied, apply_run)
			);
		});
	}

	apply_import_finished(operation, run) {
		this.show_report(operation, run);
		if (operation_has_errors(operation)) {
			run.button("دانلود ردیف‌های اعمال‌نشده (اکسل)", false, () =>
				open_operation_errors(this.method, operation.name)
			);
		}
		if (operation.status === "Completed" || operation.status === "Partial") {
			frappe.show_alert({
				message: `${cint(operation.applied)} ترجمه از اکسل اعمال شد.`,
				indicator: operation.status === "Completed" ? "green" : "orange",
			});
			this.load();
		}
		if (operation.status === "Partial" || operation.status === "Cancelled" || operation.status === "Failed") {
			run.note("عملیات کامل نشد. تا آخرین ردیفِ ثبت‌شده ادامه دهید یا فایل را برگردانید.");
			run.button("ادامه از آخرین ردیف ثبت‌شده", true, () =>
				this.resume(operation, (resumed, resume_run) => this.apply_import_finished(resumed, resume_run))
			);
		}
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

const OPERATION_STATUS_LABELS = {
	Queued: "در صف",
	Running: "در حال اجرا",
	Completed: "کامل",
	Partial: "ناتمام",
	Failed: "ناموفق",
	Cancelled: "متوقف",
};

const OPERATION_KIND_LABELS = {
	import_preview: "پیش‌نمایش ورود از اکسل",
	import_apply: "اعمال فایل اکسل",
	snapshot_preview: "پیش‌نمایش بازگردانی",
	snapshot_restore: "بازگردانی نسخهٔ پشتیبان",
};

const SNAPSHOT_KIND_LABELS = {
	install_baseline: "وضعیت پایه هنگام نصب",
	adopted_state: "وضعیت شروع مدیریت سایت",
	pre_apply: "پیش از اعمال فایل اکسل",
	pre_font: "پیش از تغییر فونت",
	pre_rtl: "پیش از تغییر چیدمان",
	pre_restore: "پیش از بازگردانی",
	manual: "نسخهٔ دستی",
};

const SETTLED_STATUSES = ["Completed", "Partial", "Failed", "Cancelled"];
const PREVIEW_KINDS = ["import_preview", "snapshot_preview"];

function operation_title(operation) {
	return OPERATION_KIND_LABELS[operation.kind] || "عملیات ترجمه";
}

function is_running(status) {
	return status === "Queued" || status === "Running";
}

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function open_download(method, endpoint, args) {
	const params = new URLSearchParams(args);
	window.open(frappe.urllib.get_full_url(`/api/method/${method}.${endpoint}?${params.toString()}`));
}

/* A wrapped workbook of the rows this operation refused is the only diagnostic
   that survives the dialog, so it is always offered when there is one row. */
function operation_has_errors(operation) {
	return Boolean(cint(operation.rejected) || cint(operation.failed) || cint(operation.error_count));
}

function open_operation_errors(method, name) {
	open_download(method, "operation_errors", { name });
}

/* Watch one operation record until it settles. The record is the report, so a
   closed tab loses nothing and a reopened dialog re-reads the same state.
   Leaving the page ends the watch: Frappe hides the dialog on a route change, and
   the operation stays readable from "صف عملیات". */
function watch_operation(method, name, handlers) {
	let stopped = false;
	const tick = () => {
		if (stopped || !on_manager_page()) {
			return;
		}
		frappe.call({
			method: method + ".operation_status",
			args: { name },
			callback: (response) => {
				const operation = response.message || {};
				handlers.on_update(operation);
				if (is_running(operation.status)) {
					setTimeout(tick, 1500);
					return;
				}
				handlers.on_finish(operation);
			},
		});
	};
	tick();
	return () => {
		stopped = true;
	};
}

class PersianTranslationRun {
	constructor(manager, title, name, { on_finish }) {
		this.manager = manager;
		this.dialog = new frappe.ui.Dialog({
			title,
			size: "large",
			primary_action_label: "بستن",
			primary_action: () => this.close(),
		});
		this.$body = $(`<div class="ptm-run"></div>`).appendTo(this.dialog.body);
		this.$status = $(`<div class="ptm-run-status text-muted"></div>`).appendTo(this.$body);
		this.$counters = $(`<div class="ptm-run-counters"></div>`).appendTo(this.$body);
		this.$report = $(`<div class="ptm-report"></div>`).appendTo(this.$body);
		this.$actions = $(`<div class="ptm-row-actions"></div>`).appendTo(this.$body);
		this.$note = $(`<div class="ptm-note"></div>`).appendTo(this.$body);
		this.watch = watch_operation(manager.method, name, {
			on_update: (operation) => this.update(operation),
			on_finish: (operation) => {
				this.update(operation);
				on_finish(operation, this);
			},
		});
	}

	show() {
		this.dialog.show();
		return this;
	}

	close() {
		this.watch();
		this.dialog.hide();
	}

	update(operation) {
		const status = OPERATION_STATUS_LABELS[operation.status] || operation.status || "";
		this.$status.text(`${operation_title(operation)} — ${status}`);
		this.$counters.empty();
		if (cint(operation.planned)) {
			$(`<span class="ptm-badge"></span>`)
				.text(`پیشرفت: ${cint(operation.processed)} از ${cint(operation.planned)}`)
				.appendTo(this.$counters);
		}
		[
			["اعمال‌شده", cint(operation.applied)],
			["بی‌تغییر", cint(operation.unchanged)],
			["ردشده", cint(operation.rejected) || cint(operation.error_count)],
			["ناموفق", cint(operation.failed)],
		]
			.filter(([, value]) => value)
			.forEach(([label, value]) =>
				$(`<span class="ptm-badge"></span>`).text(`${label}: ${value}`).appendTo(this.$counters)
			);
		if (operation.summary) {
			this.$status.text(`${operation_title(operation)} — ${status} · ${operation.summary}`);
		}
	}

	render_html(html) {
		this.$report.empty().append(html);
	}

	note(text) {
		this.$note.text(text);
	}

	button(label, primary, handler) {
		$(`<button class="btn btn-sm ${primary ? "btn-primary" : "btn-default"}"></button>`)
			.text(label)
			.on("click", handler)
			.appendTo(this.$actions);
	}
}

function import_preview_html(operation, report) {
	const parts = [
		`ردیف‌های فایل: ${cint(report.file_rows) || cint(operation.total_rows)}`,
		`ترجمهٔ تازه: ${cint(report.new)}`,
		`تغییر: ${cint(report.changed)}`,
		`بی‌تغییر: ${cint(report.unchanged)}`,
		`ردشده: ${cint(operation.rejected) || cint(operation.error_count)}`,
	];
	let html = `<p>${parts.join(" · ")}</p>`;
	const errors = (operation.errors || []).slice(0, 8);
	if (errors.length) {
		html += `<ul>${errors
			.map(
				(error) =>
					`<li dir="auto">ردیف ${cint(error.excel_row)}${
						error.sheet ? ` (${esc(error.sheet)})` : ""
					}: ${esc(error.reason)}${
						error.translated_text
							? `<br><small>مقدار ردشده: <b dir="auto">${esc(error.translated_text)}</b></small>`
							: ""
					}${
						error.before || error.after
							? `<br><small dir="ltr">${esc(error.before)} ← ${esc(error.after)}</small>`
							: ""
					}</li>`
			)
			.join("")}</ul>`;
		if (cint(operation.error_count) > errors.length) {
			html += `<p class="ptm-note">${cint(operation.error_count) - errors.length} ردیف دیگر در فایل اکسل خطاها.</p>`;
		}
	}
	html += `<p class="ptm-note">فقط ردیف‌های معتبرِ تازه یا تغییر‌یافته اعمال می‌شوند؛ هر ردیف نامعتبر جداگانه گزارش می‌شود.</p>`;
	return html;
}

function import_result_html(operation) {
	const parts = [
		`اعمال‌شده: ${cint(operation.applied)}`,
		`بی‌تغییر: ${cint(operation.unchanged)}`,
		`ردشده: ${cint(operation.rejected) || cint(operation.error_count)}`,
		`ناموفق: ${cint(operation.failed)}`,
	];
	let html = `<p>${parts.join(" · ")}</p>`;
	return html;
}

function restore_report_html(operation, preview) {
	const report = (operation.detail || {}).report || {};
	const parts = [
		`ترجمه بازنویسی‌شده: ${cint(report.translations_restored)}`,
		`ترجمه حذف‌شده: ${cint(report.translations_removed)}`,
		`فونت بازگردانده‌شده: ${cint(report.fonts_restored)}`,
		`فونت حذف‌شده: ${cint(report.fonts_removed)}`,
	];
	let html = `<p>${parts.join(" · ")}</p>`;
	if (cint(report.preserved_unowned)) {
		html += `<p class="ptm-note">${cint(
			report.preserved_unowned
		)} ترجمهٔ فارسی که این برنامه ننوشته بود، حذف نشد و دست‌نخورده ماند.</p>`;
	}
	const preserved = report.preserved_unowned_sample || [];
	if (preserved.length) {
		html += `<ul>${preserved
			.map(
				(item) =>
					`<li dir="auto">نگه‌داشته‌شده: ${esc(item.source_text)}${
						item.value ? ` ← ${esc(item.value)}` : ""
					}</li>`
			)
			.join("")}</ul>`;
	}
	if (cint(report.overwritten)) {
		html += `<p class="ptm-note">${cint(
			report.overwritten
		)} ترجمه پس از آخرین نوشتن این برنامه تغییر کرده بود؛ همان مقدار نسخهٔ پشتیبان بازنویسی شد.</p>`;
	}
	const overwritten = report.overwritten_sample || [];
	if (overwritten.length) {
		html += `<ul>${overwritten
			.map(
				(item) =>
					`<li dir="auto">${esc(item.source_text)}: مقدار کنونی ${esc(
						item.current_value
					)} ← مقدار نسخهٔ پشتیبان ${esc(item.snapshot_value)}</li>`
			)
			.join("")}</ul>`;
	}
	if (cint(report.fonts_added_since_snapshot)) {
		html += `<p class="ptm-note">${cint(
			report.fonts_added_since_snapshot
		)} خانوادهٔ فونت پس از این نسخه افزوده شده است؛ فقط با تیکِ حذف فونت برمی‌گردد.</p>`;
	}
	const missing = report.fonts_missing_files || [];
	if (missing.length) {
		html += `<p class="ptm-note">فایل این فونت‌ها پیدا نشد، پس بازگردانده نمی‌شوند: ${missing
			.map(esc)
			.join("، ")}</p>`;
	}
	if (preview && cint(preview.planned_actions)) {
		html += `<p class="ptm-note">${cint(preview.planned_actions)} تغییر برنامه‌ریزی شده است.</p>`;
	}
	const sample = (preview && preview.sample) || [];
	if (sample.length) {
		html += `<ul>${sample
			.map(
				(item) =>
					`<li dir="auto">${item.type === "translation_delete" ? "حذف" : "بازنویسی"}: ${esc(
						item.source_text
					)}${item.value ? ` ← ${esc(item.value)}` : ""}</li>`
			)
			.join("")}</ul>`;
	}
	const pending = (preview && preview.pending_operations) || [];
	if (pending.length) {
		html += `<p class="ptm-note">عملیات در صف یا در حال اجرا: ${pending
			.map((item) => esc(item.name))
			.join("، ")}</p>`;
	}
	return html;
}

function restore_options_dialog(title, primary_label, on_submit) {
	const dialog = new frappe.ui.Dialog({
		title,
		fields: [
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: "حالت بازگردانی",
				options: "full\nvalues",
				default: "full",
				description:
					"«کامل» ردیف‌هایی را که پس از این نسخه ساخته شده‌اند هم حذف می‌کند؛ «فقط مقادیر» آن ردیف‌ها را دست‌نخورده می‌گذارد.",
			},
			{
				fieldname: "remove_fonts",
				fieldtype: "Check",
				label: "خانواده‌های فونتی که پس از این نسخه افزوده شده‌اند هم حذف شوند",
				default: 0,
			},
		],
		primary_action_label: primary_label,
		primary_action(values) {
			dialog.hide();
			on_submit(values);
		},
	});
	dialog.show();
}

class PersianTranslationOperations {
	constructor(manager) {
		this.manager = manager;
		this.method = manager.method;
		this.timer = null;
		this.dialog = new frappe.ui.Dialog({
			title: "صف عملیات ترجمه",
			size: "extra-large",
			primary_action_label: "بستن",
			primary_action: () => this.close(),
		});
		this.$body = $(`<div class="ptm-ops"></div>`).appendTo(this.dialog.body);
	}

	open() {
		this.dialog.show();
		this.load();
	}

	close() {
		this.stop();
		this.dialog.hide();
	}

	stop() {
		if (this.timer) {
			clearTimeout(this.timer);
			this.timer = null;
		}
	}

	load() {
		this.stop();
		if (!on_manager_page()) {
			return;
		}
		frappe.call({
			method: this.method + ".operation_list",
			args: { limit: 20 },
			callback: (response) => {
				const operations = response.message || [];
				this.render(operations);
				if (operations.some((operation) => is_running(operation.status))) {
					this.timer = setTimeout(() => this.load(), 2000);
				}
			},
		});
	}

	render(operations) {
		this.$body.empty();
		if (!operations.length) {
			this.$body.append($(`<div class="ptm-empty text-muted"></div>`).text("عملیاتی ثبت نشده است."));
			return;
		}
		operations.forEach((operation) => this.render_row(operation));
	}

	render_row(operation) {
		const $row = $(`<div class="ptm-group"></div>`).appendTo(this.$body);
		const status = OPERATION_STATUS_LABELS[operation.status] || operation.status || "";
		$(`<div class="ptm-group-label"></div>`)
			.text(`${operation_title(operation)} — ${status}`)
			.appendTo($row);
		const meta = [
			operation.name,
			operation.file_name || operation.snapshot,
			operation.started_at ? `شروع: ${operation.started_at}` : "",
			cint(operation.planned) ? `پیشرفت: ${cint(operation.processed)} از ${cint(operation.planned)}` : "",
		].filter(Boolean);
		$(`<div class="ptm-note" dir="auto"></div>`).text(meta.join(" · ")).appendTo($row);
		if (operation.summary) {
			$(`<div class="ptm-note"></div>`).text(operation.summary).appendTo($row);
		}
		const $actions = $(`<div class="ptm-row-actions"></div>`).appendTo($row);
		if (operation.status === "Running" && operation.stale) {
			$(`<div class="ptm-note text-muted"></div>`)
				.text("اجرای این عملیات نیمه‌کاره ماند؛ می‌توانید آن را از آخرین ردیف ثبت‌شده ادامه دهید.")
				.appendTo($row);
		}
		if (is_running(operation.status) && !operation.stale) {
			$(`<button class="btn btn-xs btn-default"></button>`)
				.text(operation.cancel_requested ? "توقف درخواست شده" : "توقف")
				.prop("disabled", !!operation.cancel_requested)
				.on("click", () => {
					frappe.call({
						method: this.method + ".operation_cancel",
						args: { name: operation.name },
						callback: () => this.load(),
					});
				})
				.appendTo($actions);
		} else {
			if (this.resumable(operation)) {
				$(`<button class="btn btn-xs btn-primary"></button>`)
					.text("ادامه از آخرین ردیف ثبت‌شده")
					.on("click", () => this.resume(operation))
					.appendTo($actions);
			}
			$(`<button class="btn btn-xs btn-default"></button>`)
				.text("نمایش گزارش")
				.on("click", () => this.show_report(operation))
				.appendTo($actions);
		}
		if (operation_has_errors(operation)) {
			$(`<button class="btn btn-xs btn-default"></button>`)
				.text("دانلود ردیف‌های اعمال‌نشده (اکسل)")
				.on("click", () => open_operation_errors(this.method, operation.name))
				.appendTo($actions);
		}
	}

	resumable(operation) {
		const interrupted = operation.status === "Running" && operation.stale;
		return (
			(SETTLED_STATUSES.includes(operation.status) || interrupted) &&
			!PREVIEW_KINDS.includes(operation.kind) &&
			(interrupted || cint(operation.processed) < cint(operation.planned))
		);
	}

	resume(operation) {
		this.manager.resume(operation, (resumed, run) => {
			this.load();
			this.manager.show_report(resumed, run);
		});
	}

	show_report(operation) {
		this.manager.watch(operation_title(operation), operation, (finished, run) =>
			this.manager.show_report(finished, run)
		);
	}
}

class PersianTranslationSnapshots {
	constructor(manager) {
		this.manager = manager;
		this.method = manager.method;
		this.snapshots = [];
		this.dialog = new frappe.ui.Dialog({
			title: "نسخه‌های پشتیبان (نقاط بازیابی)",
			size: "extra-large",
			primary_action_label: "بستن",
			primary_action: () => this.close(),
		});
		this.$body = $(`<div class="ptm-snap"></div>`).appendTo(this.dialog.body);
	}

	open() {
		this.dialog.show();
		if (!this.snapshots.length) {
			this.load();
		}
	}

	close() {
		this.dialog.hide();
	}

	load() {
		if (!on_manager_page()) {
			return;
		}
		this.$body.html(`<div class="text-muted">در حال خواندن…</div>`);
		frappe.call({
			method: this.method + ".snapshot_list",
			callback: (response) => {
				this.snapshots = response.message || [];
				this.render();
			},
		});
	}

	render() {
		this.$body.empty();
		$(`<p class="ptm-note"></p>`)
			.text(
				"نسخه‌های پشتیبان فقط آنچه را فارسی‌ساز مالک آن است نگه می‌دارند: ترجمه‌های فارسی، فونت و تنظیم چیدمان. اسناد کسب‌وکار هرگز بازگردانی نمی‌شوند."
			)
			.appendTo(this.$body);
		const $head = $(`<div class="ptm-row-actions"></div>`).appendTo(this.$body);
		$(`<button class="btn btn-sm btn-default"></button>`)
			.text("ثبت نسخهٔ پشتیبان دستی")
			.on("click", () => this.capture())
			.appendTo($head);
		if (!this.snapshots.length) {
			this.$body.append($(`<div class="ptm-empty text-muted"></div>`).text("نسخه‌ای ثبت نشده است."));
			return;
		}
		this.snapshots.forEach((snapshot) => this.render_row(snapshot));
	}

	render_row(snapshot) {
		const $row = $(`<div class="ptm-group"></div>`).appendTo(this.$body);
		$(`<div class="ptm-group-label"></div>`)
			.text(snapshot.label || snapshot.name)
			.appendTo($row);
		const meta = [
			SNAPSHOT_KIND_LABELS[snapshot.kind] || snapshot.kind,
			snapshot.captured_at,
			snapshot.captured_by,
			snapshot.name,
		].filter(Boolean);
		$(`<div class="ptm-note" dir="auto"></div>`).text(meta.join(" · ")).appendTo($row);
		if (snapshot.summary) {
			$(`<div class="ptm-note"></div>`).text(snapshot.summary).appendTo($row);
		}
		if (cint(snapshot.immutable)) {
			$(`<div class="ptm-note"></div>`)
				.text("نسخهٔ تغییرناپذیر: متن این نسخه هرگز بازنویسی نمی‌شود.")
				.appendTo($row);
		}
		const $actions = $(`<div class="ptm-row-actions"></div>`).appendTo($row);
		$(`<button class="btn btn-xs btn-default"></button>`)
			.text("پیش‌نمایش تغییرات")
			.on("click", () => this.preview(snapshot))
			.appendTo($actions);
		$(`<button class="btn btn-xs btn-default"></button>`)
			.text("بازگردانی")
			.on("click", () =>
				restore_options_dialog("بازگردانی نسخهٔ پشتیبان", "بازگردانی", (values) =>
					this.restore(snapshot, values)
				)
			)
			.appendTo($actions);
	}

	capture() {
		frappe.prompt(
			[
				{
					fieldname: "label",
					fieldtype: "Data",
					label: "برچسب این نسخه",
					default: "نسخهٔ دستی",
					reqd: 1,
				},
			],
			(values) => {
				frappe.call({
					method: this.method + ".snapshot_capture",
					args: { label: values.label },
					freeze: true,
					callback: () => {
						frappe.show_alert({ message: "نسخهٔ پشتیبان ثبت شد.", indicator: "green" });
						this.load();
					},
				});
			},
			"ثبت نسخهٔ پشتیبان دستی",
			"ثبت"
		);
	}

	preview(snapshot) {
		restore_options_dialog("پیش‌نمایش بازگردانی", "نمایش پیش‌نمایش", (values) =>
			this.manager.queue(
				"snapshot_preview",
				{ name: snapshot.name, mode: values.mode, remove_fonts: values.remove_fonts ? 1 : 0 },
				"پیش‌نمایش بازگردانی",
				(operation, run) => this.preview_finished(snapshot, values, operation, run)
			)
		);
	}

	preview_finished(snapshot, values, operation, run) {
		this.manager.show_report(operation, run);
		if (operation.status !== "Completed") {
			run.note("پیش‌نمایش کامل نشد.");
			return;
		}
		const preview = (operation.detail || {}).preview || {};
		if (!cint(preview.planned_actions)) {
			run.note("چیزی برای تغییر نیست؛ این نسخه با وضعیت فعلی یکسان است.");
			return;
		}
		run.button("بازگردانی این نسخه", true, () => {
			run.close();
			this.restore(snapshot, values);
		});
	}

	restore(snapshot, values) {
		frappe.confirm(
			`نسخهٔ «${esc(snapshot.label || snapshot.name)}» روی سایت بازگردانی شود؟ پیش از بازگردانی، از وضعیت کنونی یک نسخهٔ پشتیبان خودکار گرفته می‌شود تا این کار قابل برگشت باشد.`,
			() =>
				this.manager.queue(
					"snapshot_restore",
					{
						name: snapshot.name,
						mode: values.mode,
						remove_fonts: values.remove_fonts ? 1 : 0,
						confirm: 1,
					},
					"بازگردانی نسخهٔ پشتیبان",
					(operation, run) => this.restore_finished(operation, run)
				)
		);
	}

	restore_finished(operation, run) {
		this.manager.show_report(operation, run);
		this.load();
		this.manager.load();
		if (operation.status === "Completed") {
			frappe.show_alert({ message: "بازگردانی انجام شد.", indicator: "green" });
		} else {
			run.note("بازگردانی کامل نشد.");
		}
	}
}

function publish_report(result) {
	let html = `<p>به‌روزرسانی: ${result.updated || 0}، افزوده‌شده: ${result.appended || 0}</p>`;
	if (result.withheld) {
		html += `<p>${frappe.utils.escape_html(result.withheld_message || "")}</p>`;
		html += `<ul>${rows_html(result.withheld_sample || [])}</ul>`;
	}
	if (result.withheld) {
		html += `<p>${frappe.utils.escape_html(result.withheld_message || "")}</p>`;
		html += `<ul>${rows_html(result.withheld_sample || [])}</ul>`;
	}
	return html;
}

function rows_html(rows) {
	return rows
		.map((row) => {
			const context = row.context ? ` <small>(${frappe.utils.escape_html(row.context)})</small>` : "";
			return `<li dir="ltr">${frappe.utils.escape_html(row.source_text)}${context}</li>`;
		})
		.join("");
}

function cint(value) {
	return parseInt(value || 0, 10) || 0;
}

const STATUS_LABELS = {
	draft: "ویرایش‌شده",
	changed: "تغییرکرده",
	translated: "ترجمه‌شده",
	untranslated: "ترجمه‌نشده",
};

function status_html(key) {
	const name = String(key || "untranslated");
	const label = STATUS_LABELS[name] || STATUS_LABELS.untranslated;
	return `<span class="ptm-status ptm-status--${frappe.utils.escape_html(name)}">${frappe.utils.escape_html(
		label
	)}</span>`;
}
