"""System Manager font administration.

Flow: upload -> inactive family with inspected faces -> review/mapping -> apply.
Metadata is read once on upload and stored on each face row.
"""

import json
from functools import partial

import frappe

from smartprocee_erpnext_persiant.persian_translation.system_font.css import (
	managed_family,
	render_adapter_css,
	render_family_css,
	sanitize_css_family,
)
from smartprocee_erpnext_persiant.persian_translation.system_font.inspect import (
	FontRejected,
	apply_correction,
	duplicate_messages,
	inspect_font_bytes,
	missing_regular_warning,
)
from smartprocee_erpnext_persiant.persian_translation.system_font.storage import (
	MARKER,
	clear_active_css,
	delete_upload,
	read_active_css,
	write_active_css,
	write_upload,
)

FAMILY = "Persian Font Family"
MAX_FILES = 32
MAX_BYTES = 8 * 1024 * 1024
FACE_FIELDS = (
	"original_filename",
	"file_url",
	"fallback_url",
	"font_format",
	"family_name",
	"subfamily",
	"full_name",
	"postscript_name",
	"weight_class",
	"width_class",
	"detected_style",
	"css_weight",
	"font_style",
	"font_stretch",
	"warning",
	"mapping_note",
	"enabled",
)


def require_font_manager():
	if frappe.session.user == "Guest" or "System Manager" not in set(frappe.get_roles()):
		frappe.throw("فقط System Manager می‌تواند فونت سیستم را مدیریت کند.", frappe.PermissionError)


@frappe.whitelist()
def list_font_families():
	require_font_manager()
	names = frappe.get_all(FAMILY, order_by="source asc, creation desc", pluck="name")
	css_items = list(frappe.conf.get("app_include_css") or [])
	return {
		"families": [family_review(frappe.get_doc(FAMILY, name)) for name in names],
		"custom_active": any(MARKER in str(item) for item in css_items),
	}


@frappe.whitelist(methods=["POST"])
def upload_font_family():
	require_font_manager()
	faces = [_inspect(filename, data) for filename, data in _uploads()]
	families = {face["family_name"] for face in faces}
	if len(families) > 1:
		frappe.throw(
			"فایل‌های انتخاب‌شده از بیش از یک خانواده هستند: "
			+ "، ".join(sorted(families))
			+ ". هر بار فقط یک خانواده را بارگذاری کنید.",
			frappe.ValidationError,
		)
	doc = frappe.new_doc(FAMILY)
	doc.family_name = sanitize_css_family(faces[0]["family_name"])
	doc.css_family = managed_family(doc.family_name)
	doc.source = "Uploaded"
	doc.is_active = 0
	written = []
	# A family that is never committed must not leave its files on disk.
	frappe.db.after_rollback.add(partial(_discard_uploads, written))
	for face in faces:
		face["file_url"] = write_upload(face["font_format"], face.pop("data"))
		written.append(face["file_url"])
		face["warning"] = "\n".join(face.pop("warnings") or [])
		doc.append("faces", {key: face.get(key) for key in FACE_FIELDS})
	doc.insert()
	return family_review(doc)


@frappe.whitelist(methods=["POST"])
def save_face_mapping(name, mapping):
	require_font_manager()
	doc = frappe.get_doc(FAMILY, name)
	doc.check_permission("write")
	if doc.is_active:
		frappe.throw("خانواده فعال را نمی‌توان ویرایش کرد. ابتدا بازگشت به فونت پیش‌فرض را بزنید.")
	corrections = {row.get("name"): row for row in _json(mapping)}
	for face in doc.faces:
		if face.name not in corrections:
			continue
		try:
			updated = apply_correction(face.as_dict(), corrections[face.name])
		except FontRejected as error:
			frappe.throw(f"{face.original_filename}: {error}", frappe.ValidationError)
		for key in ("css_weight", "font_style", "font_stretch", "enabled", "mapping_note"):
			face.set(key, updated[key])
	doc.save()
	return family_review(doc)


@frappe.whitelist(methods=["POST"])
def activate_family(name, confirm_warnings=0):
	require_font_manager()
	doc = frappe.get_doc(FAMILY, name)
	doc.check_permission("write")
	review = family_review(doc)
	if review["errors"]:
		frappe.throw(review["errors"][0], frappe.ValidationError)
	if review["warnings"] and not int(confirm_warnings or 0):
		return {"needs_confirmation": True, "review": review}
	try:
		desk_css = render_family_css(doc.family_name, review["faces"])
		adapter_css = render_adapter_css(doc.family_name, review["faces"])
	except ValueError:
		frappe.log_error(title="Persian font CSS", message=frappe.get_traceback())
		frappe.throw("ساخت CSS فونت ممکن نشد و تنظیمات قبلی حفظ شد.", frappe.ValidationError)
	_capture_restore_point(f"پیش از فعال‌سازی فونت «{doc.family_name}»")
	write_active_css(desk_css, adapter_css)
	_set_active_flag(doc, 1, deactivate_others=True)
	return {"activated": doc.name, "family_name": doc.family_name}


def refresh_active_css():
	"""Rebuild the generated stylesheets of the active family (``after_migrate``).

	The rules come from code, so a release that changes them must reach a site
	whose font was activated under an older one. Nothing is written when the
	files already match, so a routine migrate does not touch `site_config`.
	"""
	if not frappe.db.table_exists(FAMILY):
		return
	name = frappe.db.get_value(FAMILY, {"is_active": 1})
	if not name:
		return
	review = family_review(frappe.get_doc(FAMILY, name))
	if review["errors"]:
		return
	try:
		desk_css = render_family_css(review["family_name"], review["faces"])
		adapter_css = render_adapter_css(review["family_name"], review["faces"])
	except ValueError:
		frappe.log_error(title="Persian font CSS", message=frappe.get_traceback())
		return
	if read_active_css() != (desk_css, adapter_css):
		write_active_css(desk_css, adapter_css)


@frappe.whitelist(methods=["POST"])
def reset_font():
	require_font_manager()
	_capture_restore_point("پیش از بازگشت به فونت پیش‌فرض")
	clear_active_css()
	for name in frappe.get_all(FAMILY, filters={"is_active": 1}, pluck="name"):
		_set_active_flag(frappe.get_doc(FAMILY, name), 0)
	return {"reset": True}


@frappe.whitelist(methods=["POST"])
def delete_family(name):
	require_font_manager()
	doc = frappe.get_doc(FAMILY, name)
	doc.check_permission("delete")
	# The controller refuses an active family, records the restore
	# point and releases the files, exactly as for a Desk or REST delete.
	doc.delete()
	return {"deleted": name}


def _discard_uploads(urls) -> None:
	for url in urls:
		delete_upload(url)


def _capture_restore_point(label: str) -> None:
	"""Record the font state before it is changed, so the change is revertible."""
	from smartprocee_erpnext_persiant.persian_translation import snapshots

	snapshots.capture(snapshots.PRE_FONT, label, note="برای برگرداندن وضعیت فونت به پیش از این تغییر.")


def _set_active_flag(doc, active, deactivate_others=False):
	"""Flip `is_active` through a normal, permission-checked document write."""
	if deactivate_others:
		for name in frappe.get_all(FAMILY, filters={"is_active": 1, "name": ["!=", doc.name]}, pluck="name"):
			other = frappe.get_doc(FAMILY, name)
			other.check_permission("write")
			other.is_active = 0
			other.save()
	doc.check_permission("write")
	doc.is_active = int(bool(active))
	doc.save()


def family_review(doc) -> dict:
	faces = [{key: face.get(key) for key in (*FACE_FIELDS, "name")} for face in doc.faces]
	faces.sort(key=lambda face: (int(face["css_weight"] or 0), face["font_style"] or "", face["font_stretch"] or ""))
	enabled = [face for face in faces if face.get("enabled")]
	errors = duplicate_messages(enabled)
	if not enabled:
		errors.append("هیچ فایلی برای این خانواده فعال نیست.")
	warnings = [
		f"{face['original_filename']}: {line}"
		for face in enabled
		for line in (face.get("warning") or "").splitlines() + (face.get("mapping_note") or "").splitlines()
		if line
	]
	missing = missing_regular_warning(enabled)
	if missing:
		warnings.append(missing)
	return {
		"name": doc.name,
		"family_name": doc.family_name,
		"css_family": doc.css_family,
		"source": doc.source,
		"is_active": doc.is_active,
		"faces": faces,
		"errors": errors,
		"warnings": warnings,
	}


def _inspect(filename, data):
	try:
		face = inspect_font_bytes(filename, data)
	except FontRejected as error:
		frappe.log_error(title="Persian font rejected", message=f"{filename}\n{frappe.get_traceback()}")
		frappe.throw(f"{filename}: {error}", frappe.ValidationError)
	face["data"] = data
	return face


def _uploads():
	incoming = frappe.request.files.getlist("file") if frappe.request else []
	if not incoming:
		frappe.throw("هیچ فایل فونتی انتخاب نشده است.", frappe.ValidationError)
	if len(incoming) > MAX_FILES:
		frappe.throw(f"حداکثر {MAX_FILES} فایل در هر بارگذاری مجاز است.", frappe.ValidationError)
	uploads = []
	for item in incoming:
		data = item.stream.read(MAX_BYTES + 1)
		if len(data) > MAX_BYTES:
			frappe.throw(f"{item.filename}: حجم فایل بیش از ۸ مگابایت است.", frappe.ValidationError)
		uploads.append((item.filename, data))
	return uploads


def _json(value):
	parsed = json.loads(value) if isinstance(value, str) else value
	if not isinstance(parsed, list):
		frappe.throw("نگاشت ارسال‌شده معتبر نیست.", frappe.ValidationError)
	return parsed
