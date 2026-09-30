import hashlib
from pathlib import Path

import frappe
from frappe.translate import clear_cache, get_all_translations
from frappe.utils import cint, sanitize_html

from smartprocee_erpnext_persiant.persian_translation.catalogue import catalogue_map, read_catalogue
from smartprocee_erpnext_persiant.persian_translation.excel_io import (
	build_workbook,
	classify_import_rows,
	read_workbook,
)
from smartprocee_erpnext_persiant.persian_translation.kind import text_kind, text_kinds
from smartprocee_erpnext_persiant.persian_translation.publish import publish_overrides
from smartprocee_erpnext_persiant.persian_translation.scan import (
	SOURCE_DOCTYPE,
	get_scan_status,
	set_scan_status,
)
from smartprocee_erpnext_persiant.persian_translation.validate import translation_error

APP_NAME = "smartprocee_erpnext_persiant"


def require_system_manager():
	if frappe.session.user == "Guest" or "System Manager" not in set(frappe.get_roles()):
		frappe.throw(
			"فقط System Manager می‌تواند ترجمه‌های فارسی را مدیریت کند.",
			frappe.PermissionError,
		)


def catalogue_path() -> Path:
	return Path(frappe.get_app_path(APP_NAME, "translations", "fa.csv"))


def translation_identity(source: str, context: str = "") -> str:
	return hashlib.sha256(f"{source}\x1f{context or ''}".encode()).hexdigest()


def load_catalogue_translations() -> dict[tuple[str, str], str]:
	cached = getattr(frappe.local, "_persian_catalogue_map", None)
	if cached is not None:
		return cached
	path = catalogue_path()
	mapped = catalogue_map(read_catalogue(path)) if path.exists() else {}
	frappe.local._persian_catalogue_map = mapped
	return mapped


def load_overrides() -> dict[tuple[str, str], str]:
	cached = getattr(frappe.local, "_persian_override_map", None)
	if cached is not None:
		return cached
	mapped = {}
	for row in frappe.get_all(
		"Translation",
		filters={"language": "fa"},
		fields=["source_text", "context", "translated_text"],
		limit_page_length=0,
	):
		mapped[(row.source_text, row.context or "")] = row.translated_text or ""
	frappe.local._persian_override_map = mapped
	return mapped


def effective_translation(source: str, context: str = "") -> str:
	merged = get_all_translations("fa")
	if context:
		specific = merged.get(f"{source}:{context}")
		if specific:
			return specific
	return merged.get(source) or ""


def is_changed(source: str, context: str) -> bool:
	overrides = load_overrides()
	key = (source, context or "")
	if key not in overrides:
		return False
	catalogue = load_catalogue_translations()
	return (overrides[key] or "") != (catalogue.get(key) or "")


def _row_payload(row) -> dict:
	source = row.source_text
	context = row.context or ""
	kinds = text_kinds(row.source_path or "", context)
	return {
		"name": row.name,
		"app": row.app,
		"module": row.module or "",
		"source_path": row.source_path or "",
		"source_text": source,
		"context": context,
		"kind": text_kind(row.source_path or "", context),
		"kinds": kinds,
		"current_translation": effective_translation(source, context),
		"changed": is_changed(source, context),
		"identity": translation_identity(source, context),
	}


def _matches_status(payload, status) -> bool:
	current = (payload["current_translation"] or "").strip()
	source = (payload["source_text"] or "").strip()
	translated = bool(current) and current != source
	if status == "translated":
		return translated
	if status == "untranslated":
		return not translated
	if status == "changed":
		return payload["changed"]
	return True


def _matches_kind(payload, kind) -> bool:
	if not kind:
		return True
	return kind in (payload.get("kinds") or [])


def _matches_search(payload, search) -> bool:
	if not search:
		return True
	haystack = " ".join(
		[
			payload["source_text"] or "",
			payload["context"] or "",
			payload["current_translation"] or "",
			payload["source_path"] or "",
			payload["module"] or "",
			payload["kind"] or "",
		]
	)
	return search.casefold() in haystack.casefold()


def list_apps() -> list[str]:
	require_system_manager()
	found = set(frappe.get_installed_apps(_ensure_on_bench=True))
	stored = frappe.db.sql(f"select distinct app from `tab{SOURCE_DOCTYPE}`", pluck=True)
	found.update(app for app in stored if app)
	return sorted(found)


def get_rows(search=None, app=None, status=None, kind=None, start=0, page_length=50):
	require_system_manager()
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or 50, 1), 100)
	search = (search or "").strip()
	app = (app or "").strip()
	kind = (kind or "").strip()
	status = status or "all"
	table = frappe.qb.DocType(SOURCE_DOCTYPE)
	query = frappe.qb.from_(table).select(
		table.name,
		table.app,
		table.module,
		table.source_path,
		table.source_text,
		table.context,
	)
	if app:
		query = query.where(table.app == app)
	needs_python_filter = bool(search) or bool(kind) or status != "all"
	if needs_python_filter:
		records = query.orderby(table.app).orderby(table.source_text).orderby(table.context).run(as_dict=True)
		payloads = []
		for row in records:
			payload = _row_payload(row)
			if _matches_search(payload, search) and _matches_status(payload, status) and _matches_kind(payload, kind):
				payloads.append(payload)
		total = len(payloads)
		page = payloads[start : start + page_length]
	else:
		total = frappe.db.count(SOURCE_DOCTYPE, {"app": app} if app else {})
		records = (
			query.orderby(table.app)
			.orderby(table.source_text)
			.orderby(table.context)
			.offset(start)
			.limit(page_length)
			.run(as_dict=True)
		)
		page = [_row_payload(row) for row in records]
	return {
		"rows": page,
		"total": total,
		"start": start,
		"page_length": page_length,
		"scan": get_scan_status(),
		"apps": sorted(set(frappe.get_installed_apps(_ensure_on_bench=True))),
	}


def _assert_safe_translation(source: str, translated: str, context: str = ""):
	problem = translation_error(source, translated, context)
	if problem:
		frappe.throw(problem)
	cleaned = sanitize_html(translated)
	if "<" in translated and cleaned != translated:
		frappe.throw("ترجمه فارسی شامل HTMLای است که Frappe آن را تغییر می‌دهد. ذخیره انجام نشد.")


def save_translations(rows):
	require_system_manager()
	if isinstance(rows, str):
		rows = frappe.parse_json(rows)
	saved = 0
	for row in rows or []:
		source = (row.get("source_text") or "").strip()
		context = row.get("context") or ""
		translated = (row.get("translated_text") or "").strip()
		if not source or not translated:
			continue
		if translated == (effective_translation(source, context) or "").strip():
			continue
		_assert_safe_translation(source, translated, context)
		_upsert_translation(source, context, translated)
		saved += 1
	if saved:
		frappe.local._persian_override_map = None
		clear_cache()
	return {"saved": saved}


def _upsert_translation(source: str, context: str, translated: str):
	matches = frappe.get_all(
		"Translation",
		filters={"language": "fa", "source_text": source},
		fields=["name", "context"],
		limit_page_length=0,
	)
	matches = [row for row in matches if (row.context or "") == (context or "")]
	if matches:
		for row in matches:
			doc = frappe.get_doc("Translation", row.name)
			doc.language = "fa"
			doc.translated_text = translated
			doc.context = context or ""
			doc.save()
		return
	doc = frappe.get_doc(
		{
			"doctype": "Translation",
			"language": "fa",
			"source_text": source,
			"context": context or "",
			"translated_text": translated,
		}
	)
	doc.insert()


def start_scan():
	require_system_manager()
	status = get_scan_status()
	if status.get("status") == "running":
		frappe.throw("اسکن دیگری در حال اجراست.")
	set_scan_status(status="queued", message="اسکن در صف قرار گرفت.")
	frappe.enqueue(
		"smartprocee_erpnext_persiant.persian_translation.scan.run_scan",
		queue="long",
		timeout=60 * 60,
		enqueue_after_commit=True,
	)
	return {"queued": True}


def scan_status():
	require_system_manager()
	return get_scan_status()


def _filtered_payloads(search=None, app=None, status=None, kind=None):
	page_length = 100
	start = 0
	rows = []
	while True:
		batch = get_rows(search=search, app=app, status=status, kind=kind, start=start, page_length=page_length)
		rows.extend(batch["rows"])
		start += page_length
		if start >= batch["total"]:
			break
		if not batch["rows"]:
			break
	return rows


def export_excel(search=None, app=None, status=None, kind=None):
	require_system_manager()
	rows = _filtered_payloads(search, app, status, kind)
	frappe.response["filename"] = "persian-translations.xlsx"
	frappe.response["filecontent"] = build_workbook(rows)
	frappe.response["type"] = "binary"
	frappe.response["display_content_as"] = "attachment"


def _file_from_url(file_url: str) -> Path:
	file_url = (file_url or "").strip()
	if not file_url:
		frappe.throw("فایل اکسل انتخاب نشده است.")
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		frappe.throw("فایل اکسل پیدا نشد.")
	doc = frappe.get_doc("File", name)
	path = Path(doc.get_full_path()).resolve()
	site_root = Path(frappe.get_site_path()).resolve()
	if site_root not in path.parents:
		frappe.throw("مسیر فایل مجاز نیست.")
	if path.suffix.lower() != ".xlsx":
		frappe.throw("فقط فایل xlsx ساخته‌شده توسط همین صفحه پذیرفته می‌شود.")
	return path


def preview_import(file_url):
	require_system_manager()
	path = _file_from_url(file_url)
	try:
		file_rows = read_workbook(path)
	except ValueError as exc:
		frappe.throw(str(exc))
	classified = classify_import_rows(file_rows, effective_translation, translation_identity)
	classified.pop("actions", None)
	return {
		"file_rows": classified["file_rows"],
		"unchanged": classified["unchanged"],
		"new": classified["new"],
		"changed": classified["changed"],
		"errors": classified["errors"][:50],
		"error_count": len(classified["errors"]),
	}


def apply_import(file_url):
	require_system_manager()
	path = _file_from_url(file_url)
	try:
		file_rows = read_workbook(path)
	except ValueError as exc:
		frappe.throw(str(exc))
	classified = classify_import_rows(file_rows, effective_translation, translation_identity)
	result = save_translations(classified["actions"])
	return {
		"file_rows": classified["file_rows"],
		"unchanged": classified["unchanged"],
		"new": classified["new"],
		"changed": classified["changed"],
		"error_count": len(classified["errors"]),
		"errors": classified["errors"][:50],
		"saved": result["saved"],
	}


def publish_catalogue():
	"""Merge Frappe/ERPNext-owned fa overrides into this app's fa.csv. Does not use write_translations_file."""
	require_system_manager()
	result = publish_overrides(catalogue_path(), load_overrides())
	if result["updated"] or result["appended"]:
		frappe.local._persian_catalogue_map = None
		clear_cache()
	return result
