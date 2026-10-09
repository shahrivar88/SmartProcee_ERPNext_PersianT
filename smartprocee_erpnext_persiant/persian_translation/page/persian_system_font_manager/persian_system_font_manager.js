frappe.pages["persian-system-font-manager"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "مدیریت فونت سیستم",
		single_column: true,
	});
	frappe.persian_system_font_manager = new PersianSystemFontManager(page);
};

const PSF_METHOD = "smartprocee_erpnext_persiant.persian_translation.system_font.service";
const PSF_WEIGHTS = {
	100: "Thin",
	200: "ExtraLight",
	300: "Light",
	400: "Regular",
	500: "Medium",
	600: "SemiBold",
	700: "Bold",
	800: "ExtraBold",
	900: "Black",
};
const PSF_STRETCHES = [
	"ultra-condensed",
	"extra-condensed",
	"condensed",
	"semi-condensed",
	"normal",
	"semi-expanded",
	"expanded",
	"extra-expanded",
	"ultra-expanded",
];
const PSF_STYLES = ["normal", "italic", "oblique"];

class PersianSystemFontManager {
	constructor(page) {
		this.page = page;
		this.loaded_faces = new Set();
		this.page.add_inner_button("بازگشت به فونت پیش‌فرض", () => this.reset(), "عملیات");
		this.$body = $('<div class="psf-manager"></div>').appendTo(this.page.main);
		this.ensure_style();
		this.render_upload();
		this.$status = $('<div class="psf-status"></div>').appendTo(this.$body);
		this.$families = $('<div class="psf-families"></div>').appendTo(this.$body);
		this.load();
	}

	call(method, args) {
		return frappe.call({ method: `${PSF_METHOD}.${method}`, args, freeze: true });
	}

	load() {
		return this.call("list_font_families").then((r) => this.render(r.message || {}));
	}

	render_upload() {
		const $box = $(`
			<div class="psf-card">
				<h5>افزودن خانواده فونت</h5>
				<p class="text-muted small">
					همه فایل‌های یک خانواده را با هم انتخاب کنید.
					<b>WOFF2 (فرمت پیشنهادی)</b> — WOFF (جایگزین).
					وزن، حالت و عرض هر فایل از فراداده داخلی فونت خوانده می‌شود.
				</p>
				<input type="file" class="psf-input" multiple accept=".woff2,.woff,.ttf,.otf">
				<button class="btn btn-primary btn-sm psf-upload">بارگذاری و بررسی</button>
			</div>`).appendTo(this.$body);
		$box.find(".psf-upload").on("click", () => this.upload($box.find(".psf-input")[0]));
	}

	upload(input) {
		const files = Array.from(input.files || []);
		if (!files.length) {
			frappe.msgprint("هیچ فایل فونتی انتخاب نشده است.");
			return;
		}
		const desktop = files.filter((file) => /\.(ttf|otf)$/i.test(file.name));
		if (desktop.length) {
			frappe.msgprint(
				"برای بهترین سازگاری و سرعت در ERPNext، نسخه WOFF2 این فونت را انتخاب کنید. در صورت نبود WOFF2 می‌توانید از WOFF استفاده کنید.<br><br>" +
					desktop.map((file) => frappe.utils.escape_html(file.name)).join("<br>")
			);
			return;
		}
		const data = new FormData();
		files.forEach((file) => data.append("file", file, file.name));
		frappe.dom.freeze("در حال بررسی فایل‌ها...");
		fetch(`/api/method/${PSF_METHOD}.upload_font_family`, {
			method: "POST",
			body: data,
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token, Accept: "application/json" },
		})
			.then((response) => response.json().then((json) => ({ ok: response.ok, json })))
			.then(({ ok, json }) => {
				frappe.dom.unfreeze();
				if (!ok) {
					frappe.msgprint({ title: "خطا در بارگذاری فونت", message: psf_server_message(json), indicator: "red" });
					return;
				}
				input.value = "";
				frappe.show_alert({ message: "فایل‌ها بررسی شدند. نگاشت را قبل از اعمال بازبینی کنید.", indicator: "blue" });
				this.load();
			})
			.catch(() => {
				frappe.dom.unfreeze();
				frappe.msgprint("ارتباط با سرور برقرار نشد.");
			});
	}

	render(data) {
		const families = data.families || [];
		const active = families.find((family) => family.is_active && data.custom_active);
		this.$status.html(
			active
				? `فونت فعال سیستم: <b>${psf_esc(active.family_name)}</b> (${psf_source_label(active.source)})`
				: "فونت فعال سیستم: <b>فونت پیش‌فرض سیستم</b>"
		);
		this.$families.empty();
		families.forEach((family) => this.render_family(family, data.custom_active));
	}

	render_family(family, custom_active) {
		const editable = family.source === "Uploaded" && !family.is_active;
		const is_live = family.is_active && custom_active;
		const $card = $(`<div class="psf-card" data-name="${psf_esc(family.name)}"></div>`).appendTo(this.$families);
		$card.append(`<h5>${psf_esc(family.family_name)} <span class="text-muted small">${psf_source_label(family.source)}${is_live ? " — فعال" : ""}</span></h5>`);
		$card.append(this.review_table(family, editable));
		$card.append(psf_messages(family.errors, "red"));
		$card.append(psf_messages(family.warnings, "orange"));
		$card.append(this.preview(family));
		const $actions = $('<div class="psf-actions"></div>').appendTo($card);
		if (editable) {
			$('<button class="btn btn-default btn-sm">ذخیره نگاشت</button>')
				.on("click", () => this.save_mapping(family, $card))
				.appendTo($actions);
		}
		if (!is_live) {
			$('<button class="btn btn-primary btn-sm">اعمال به کل سیستم</button>')
				.prop("disabled", (family.errors || []).length > 0)
				.on("click", () => this.activate(family, 0))
				.appendTo($actions);
		}
		if (family.source === "Uploaded" && !family.is_active) {
			$('<button class="btn btn-danger btn-sm">حذف خانواده</button>')
				.on("click", () => this.remove(family))
				.appendTo($actions);
		}
	}

	review_table(family, editable) {
		const conflicts = psf_conflicts(family.faces);
		const rows = family.faces
			.map((face) => {
				const status = conflicts.has(psf_face_key(face))
					? { text: "تداخل: فایل دیگری همین وزن/حالت/عرض/فرمت را دارد", cls: "text-danger" }
					: psf_face_status(face);
				return `<tr data-face="${psf_esc(face.name)}">
					<td class="psf-ltr">${psf_esc(face.original_filename)}</td>
					<td class="psf-ltr">${psf_esc(face.font_format)}${face.font_format === "WOFF2" ? " <span class=\"text-success\">(پیشنهادی)</span>" : ""}</td>
					<td class="psf-ltr">${psf_esc(face.family_name)}</td>
					<td class="psf-ltr">${psf_esc(face.subfamily)}</td>
					<td class="psf-ltr">${psf_cint(face.weight_class)}</td>
					<td>${editable ? psf_select("css_weight", Object.keys(PSF_WEIGHTS), face.css_weight, (w) => `${w} ${PSF_WEIGHTS[w]}`) : `${face.css_weight} ${PSF_WEIGHTS[face.css_weight] || ""}`}</td>
					<td>${editable ? psf_select("font_style", PSF_STYLES, face.font_style) : psf_esc(face.font_style)}</td>
					<td>${editable ? psf_select("font_stretch", PSF_STRETCHES, face.font_stretch) : psf_esc(face.font_stretch)}</td>
					<td>${editable ? `<input type="checkbox" data-field="enabled" ${face.enabled ? "checked" : ""}>` : face.enabled ? "بله" : "خیر"}</td>
					<td class="${status.cls}">${status.text}</td>
				</tr>`;
			})
			.join("");
		return `<div class="psf-table-wrap"><table class="table table-bordered table-sm psf-table">
			<thead><tr>
				<th>فایل</th><th>فرمت</th><th>خانواده</th><th>نوع</th><th>وزن فراداده</th>
				<th>CSS Weight</th><th>حالت</th><th>عرض</th><th>استفاده</th><th>وضعیت</th>
			</tr></thead><tbody>${rows}</tbody></table></div>`;
	}

	preview(family) {
		const css_family = `PSF Preview ${family.name}`;
		const faces = family.faces.filter((face) => face.enabled);
		faces.forEach((face) => this.load_face(css_family, face));
		const weights = [...new Set(faces.filter((f) => f.font_style === "normal" && f.font_stretch === "normal").map((f) => psf_cint(f.css_weight)))].sort();
		const regular = weights.includes(400) ? 400 : weights[0] || 400;
		const strong = weights.filter((w) => w >= 600)[0] || regular;
		const style = (weight, size) => `font-family: '${css_family}', sans-serif; font-weight: ${weight}; font-size: ${size}`;
		const weight_lines = weights
			.map((w) => `<div style="${style(w, "16px")}">${w} ${PSF_WEIGHTS[w] || ""} — نمونه نمایش فونت فارسی ۰۱۲۳۴۵۶۷۸۹</div>`)
			.join("");
		return $(`<details class="psf-preview"><summary>پیش‌نمایش با فایل‌های واقعی این خانواده</summary>
			<div class="psf-preview-body" dir="rtl">
				<div style="${style(strong, "22px")}">عنوان اصلی</div>
				<div style="${style(regular, "15px")}">نمونه نمایش فونت فارسی در سیستم برنامه‌ریزی منابع سازمان</div>
				<div style="${style(regular, "15px")}" dir="ltr">ERPNext System Font Preview</div>
				<div style="${style(regular, "15px")}">۰۱۲۳۴۵۶۷۸۹ — <span dir="ltr">0123456789</span></div>
				<div style="${style(regular, "12px")}">متن کوچک برای توضیحات فرم</div>
				<label style="${style(strong, "13px")}">Label / برچسب فیلد</label>
				<div class="psf-fake-input" style="${style(regular, "14px")}">متن داخل فیلد ورودی</div>
				<span class="btn btn-primary btn-sm" style="${style(strong, "13px")}">دکمه ذخیره</span>
				<table class="table table-sm psf-fake-table" style="${style(regular, "13px")}">
					<tr><th style="font-weight:${strong}">مشتری</th><th style="font-weight:${strong}">مبلغ</th></tr>
					<tr><td>شرکت نمونه</td><td>۱۲٬۵۰۰٬۰۰۰</td></tr>
				</table>
				<h6>وزن‌های موجود</h6>
				${weight_lines || '<div class="text-muted">وزن Normal ثبت نشده است.</div>'}
			</div></details>`);
	}

	load_face(css_family, face) {
		const key = `${css_family}|${face.file_url}`;
		if (this.loaded_faces.has(key) || !window.FontFace) {
			return;
		}
		this.loaded_faces.add(key);
		const format = face.font_format === "WOFF2" ? "woff2" : "woff";
		const font = new FontFace(css_family, `url("${face.file_url}") format("${format}")`, {
			weight: String(face.css_weight),
			style: face.font_style,
			stretch: face.font_stretch,
		});
		font.load().then(
			(loaded) => document.fonts.add(loaded),
			() => frappe.show_alert({ message: `بارگذاری ${face.original_filename} در مرورگر ناموفق بود.`, indicator: "red" })
		);
	}

	save_mapping(family, $card) {
		const mapping = family.faces.map((face) => {
			const $row = $card.find(`tr[data-face="${face.name}"]`);
			return {
				name: face.name,
				css_weight: $row.find('[data-field="css_weight"]').val(),
				font_style: $row.find('[data-field="font_style"]').val(),
				font_stretch: $row.find('[data-field="font_stretch"]').val(),
				enabled: $row.find('[data-field="enabled"]').is(":checked") ? 1 : 0,
			};
		});
		this.call("save_face_mapping", { name: family.name, mapping: JSON.stringify(mapping) }).then(() => {
			frappe.show_alert({ message: "نگاشت ذخیره شد.", indicator: "green" });
			this.load();
		});
	}

	activate(family, confirmed) {
		this.call("activate_family", { name: family.name, confirm_warnings: confirmed }).then((r) => {
			const result = r.message || {};
			if (result.needs_confirmation) {
				const text = (result.review.warnings || []).map(psf_esc).join("<br>");
				frappe.confirm(`${text}<br><br>با وجود این هشدارها اعمال شود؟`, () => this.activate(family, 1));
				return;
			}
			frappe.msgprint(
				"فونت روی کل سیستم اعمال شد. صفحه را تازه کنید. اگر فونت قبلی هنوز دیده می‌شود، یک بار Ctrl+Shift+R بزنید. ممکن است تا یک دقیقه طول بکشد تا همه پردازش‌های سرور تنظیم جدید را بخوانند."
			);
			this.load();
		});
	}

	reset() {
		frappe.confirm("فونت سفارشی غیرفعال و فونت پیش‌فرض فارسی‌ساز برگردانده شود؟", () => {
			this.call("reset_font").then(() => {
				frappe.msgprint(
					"فونت انتخاب‌شده غیرفعال شد و فونت پیش‌فرض سیستم دوباره فعال است. صفحه را تازه کنید (در صورت نیاز Ctrl+Shift+R)."
				);
				this.load();
			});
		});
	}

	remove(family) {
		frappe.confirm(`خانواده ${psf_esc(family.family_name)} و فایل‌های آن حذف شود؟`, () => {
			this.call("delete_family", { name: family.name }).then(() => this.load());
		});
	}

	ensure_style() {
		if (document.getElementById("psf-style")) {
			return;
		}
		$(`<style id="psf-style">
			.psf-card { border: 1px solid var(--border-color); border-radius: var(--border-radius-md); padding: var(--padding-md); margin-bottom: var(--margin-md); background: var(--card-bg); }
			.psf-status { margin-bottom: var(--margin-md); }
			.psf-actions { display: flex; gap: var(--margin-sm); margin-top: var(--margin-sm); }
			.psf-table-wrap { overflow-x: auto; }
			.psf-table select { min-width: 140px; }
			.psf-ltr { direction: ltr; text-align: left; }
			.psf-preview-body { padding: var(--padding-sm); display: grid; gap: 6px; }
			.psf-fake-input { border: 1px solid var(--border-color); border-radius: var(--border-radius); padding: 4px 8px; max-width: 320px; }
			.psf-fake-table { max-width: 360px; }
			.psf-preview-body .btn { justify-self: start; }
			.psf-upload { margin-inline-start: var(--margin-sm); }
		</style>`).appendTo(document.head);
	}
}

function psf_face_key(face) {
	return [face.css_weight, face.font_style, face.font_stretch, face.font_format].join("|");
}

function psf_conflicts(faces) {
	const counts = {};
	faces.filter((face) => face.enabled).forEach((face) => {
		const key = psf_face_key(face);
		counts[key] = (counts[key] || 0) + 1;
	});
	return new Set(
		faces.filter((face) => face.enabled && counts[psf_face_key(face)] > 1).map(psf_face_key)
	);
}

function psf_face_status(face) {
	if (!face.enabled) return { text: "استفاده نمی‌شود", cls: "text-muted" };
	if (face.warning || face.mapping_note) return { text: psf_esc(`${face.warning || ""} ${face.mapping_note || ""}`), cls: "text-warning" };
	return { text: "صحیح", cls: "text-success" };
}

function psf_select(field, values, current, label) {
	const options = values
		.map((value) => `<option value="${psf_esc(value)}" ${String(value) === String(current) ? "selected" : ""}>${psf_esc(label ? label(value) : value)}</option>`)
		.join("");
	return `<select class="form-control input-xs" data-field="${field}">${options}</select>`;
}

function psf_messages(items, color) {
	if (!items || !items.length) return "";
	return `<div class="psf-messages indicator-pill ${color}" style="display:block; white-space:normal; height:auto; margin-top:6px">${items.map(psf_esc).join("<br>")}</div>`;
}

function psf_server_message(json) {
	try {
		const list = JSON.parse(json._server_messages || "[]").map((m) => JSON.parse(m).message);
		if (list.length) return list.join("<br>");
	} catch (e) {
		// fall through to a generic message
	}
	return json.exception ? "فایل‌ها پذیرفته نشدند. جزئیات فنی در Error Log ثبت شد." : "خطای ناشناخته.";
}

function psf_source_label(source) {
	return source === "Uploaded" ? "بارگذاری‌شده" : psf_esc(source);
}

function psf_esc(value) {
	return frappe.utils.escape_html(String(value == null ? "" : value));
}

function psf_cint(value) {
	return parseInt(value || 0, 10) || 0;
}
