import functools
import operator
from pathlib import Path

import frappe
from frappe.translate import clear_cache, get_all_translations
from frappe.utils import cint
from pypika import Order

from smartprocee_erpnext_persiant.persian_translation import operations, ownership
from smartprocee_erpnext_persiant.persian_translation.catalogue import catalogue_map, read_catalogue
from smartprocee_erpnext_persiant.persian_translation.excel_io import build_workbook
from smartprocee_erpnext_persiant.persian_translation.identity import translation_identity
from smartprocee_erpnext_persiant.persian_translation.kind import KIND_LABELS
from smartprocee_erpnext_persiant.persian_translation.location import prefetch, resolve
from smartprocee_erpnext_persiant.persian_translation.publish import publish_overrides
from smartprocee_erpnext_persiant.persian_translation.scan import (
	SOURCE_DOCTYPE,
	get_scan_status,
	set_scan_status,
)
from smartprocee_erpnext_persiant.persian_translation.validate import check_translation

APP_NAME = "smartprocee_erpnext_persiant"

# Columns the manager may sort on. The ones in the index table are ordered by
# the database and keep the fast paged query; the others only exist once a row
# has been turned into a payload, so they need every matching row in memory.
SQL_SORT_COLUMNS = {
	"app": "app",
	"source_text": "source_text",
}
# `translation` is the only sortable column whose value is not in the index at
# all: it is resolved from the Translation rows and the shipped catalogue, so it
# can only be ordered once every matching row has become a payload.
PAYLOAD_SORT_COLUMNS = {
	**SQL_SORT_COLUMNS,
	"kind": "kind",
	"location": "location",
	"translation": "current_translation",
	"status": "status",
}

# The stored columns the search box is compared against. `نوع` and
# `محل استفاده` are missing on purpose: both are computed from the site's own
# document metadata while a row becomes a payload, so no column holds them.
SEARCH_COLUMNS = (
	"app",
	"module",
	"source_path",
	"source_text",
	"context",
)
# The one fixed Persian place label `location` writes plus the fixed words its
# other labels are built from. A term that can match one of these must not be
# narrowed: the value exists in no column, only in the computed label.
DERIVED_SEARCH_LABELS = tuple(KIND_LABELS) + (
	"Sidebar",
	"Workspace",
	"Desktop Icon",
	"Navbar",
	"Report",
	"Web Form",
	"Onboarding",
	"Page",
	"Web Page",
	"کد رابط کاربری",
	"کد سرور",
)
# Past this many candidate strings the `IN` list costs more than the rows it
# saves, so the query is left whole and the payload filter does all the work.
MAX_SEARCH_SOURCES = 2000


def _search_narrows(search: str) -> bool:
	"""Whether the SQL query may be narrowed for this term without losing a row.

	The payload search also matches two computed fields -- ``نوع`` and
	``محل استفاده`` -- and a location label carries a DocType fieldname such as
	``Sales Invoice.grand_total``. None of those words is stored anywhere, so a
	term that could match one of them is searched the long way instead of being
	answered with a query that cannot see them.
	"""
	folded = search.casefold()
	if any(folded in label.casefold() for label in DERIVED_SEARCH_LABELS):
		return False
	return not _fieldname_matches(search)


def _fieldname_matches(search: str) -> bool:
	"""Whether any DocType fieldname or label contains the term. Read once per request."""
	cache = getattr(frappe.local, "_persian_search_fieldnames", None)
	if cache is None:
		cache = frappe.local._persian_search_fieldnames = {}
	if search not in cache:
		cache[search] = bool(
			frappe.db.sql(
				"select 1 from `tabDocField` where fieldname like %s or label like %s limit 1",
				(f"%{search}%", f"%{search}%"),
			)
		)
	return cache[search]


def _searchable_sources(search: str) -> set[str] | None:
	"""Source strings whose visible Persian translation contains the term.

	``merged_translations()`` holds every value the grid can show in
	``ترجمه فارسی``: this site's own rows, the shipped catalogue and whatever the
	installed apps ship. Its keys are either the source text or
	``source_text:context``, so both spellings of a matching key are offered and
	the exact payload filter decides afterwards which rows really match.

	``None`` means "too many candidates to be worth narrowing by".
	"""
	folded = search.casefold()
	found: set[str] = set()
	for key, value in merged_translations().items():
		if not value or folded not in str(value).casefold():
			continue
		found.add(key)
		head, separator, _tail = key.partition(":")
		if separator:
			found.add(head)
		if len(found) > MAX_SEARCH_SOURCES:
			return None
	return found


def _narrow_by_search(query, table, search: str):
	"""Keep only the rows the payload search could possibly accept.

	Every condition below is a *superset* test: a row that matches on its own
	columns, or whose stored Persian translation matches, is kept. ``%`` and
	``_`` typed by the user stay wildcards, which only widens the result. The
	exact payload filter still runs on what is left, so a kept row may still be
	rejected -- never the other way round.
	"""
	like = f"%{search}%"
	conditions = [getattr(table, column).like(like) for column in SEARCH_COLUMNS]
	sources = _searchable_sources(search)
	if sources is None:
		return query
	if sources:
		conditions.append(table.source_text.isin(sorted(sources)))
	return query.where(functools.reduce(operator.or_, conditions))


def require_system_manager():
	if frappe.session.user == "Guest" or "System Manager" not in set(frappe.get_roles()):
		frappe.throw(
			"فقط System Manager می‌تواند ترجمه‌های فارسی را مدیریت کند.",
			frappe.PermissionError,
		)


def catalogue_path() -> Path:
	return Path(frappe.get_app_path(APP_NAME, "translations", "fa.csv"))


def load_catalogue_translations() -> dict[tuple[str, str], str]:
	cached = getattr(frappe.local, "_persian_catalogue_map", None)
	if cached is not None:
		return cached
	path = catalogue_path()
	mapped = catalogue_map(read_catalogue(path)) if path.exists() else {}
	frappe.local._persian_catalogue_map = mapped
	return mapped


def clear_translation_caches():
	"""Drop every cached view of the translation set.

	The two local maps of this app plus the `merged_translations` /
	`lang_user_translations` hash fields of Frappe. Call it after any write to
	`Translation` or to the shipped catalogue, otherwise the next read inside the
	same process keeps serving the old values.
	"""
	frappe.local._persian_override_map = None
	frappe.local._persian_catalogue_map = None
	ownership.clear_cache()
	clear_cache()


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


def merged_translations() -> dict:
	"""Frappe's merged `fa` dictionary.

	``frappe.translate.get_all_translations`` is already memoised for the
	request: :meth:`frappe.utils.redis_wrapper.RedisCache.hget` keeps the
	unpickled value in ``frappe.local.cache``, and
	``frappe.translate.clear_cache()`` evicts exactly that entry.

	Keeping a second copy in a local attribute would survive that eviction, so
	an edit followed by Frappe's own cache clear would keep serving the old
	dictionary for the rest of the process. There is deliberately no cache here
	beyond the one the framework owns.
	"""
	return get_all_translations("fa")


def effective_translation(source: str, context: str = "") -> str:
	merged = merged_translations()
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
	source_path = row.source_path or ""
	place = resolve(source_path, source, context)
	payload = {
		"name": row.name,
		"app": row.app,
		"module": row.module or "",
		"source_path": source_path,
		"source_text": source,
		"context": context,
		"kind": place.kind,
		"location": place.label,
		"other_locations": place.others,
		"current_translation": effective_translation(source, context),
		"changed": is_changed(source, context),
		"identity": translation_identity(source, context),
	}
	payload["status"] = row_status(payload)
	return payload


def _is_translated(payload) -> bool:
	current = (payload["current_translation"] or "").strip()
	return bool(current) and current != (payload["source_text"] or "").strip()


def row_status(payload) -> str:
	"""The single word the manager shows in its status column.

	Derived from the same rules the status filter uses, so the column and the
	filter can never disagree.
	"""
	if payload["changed"]:
		return "changed"
	return "translated" if _is_translated(payload) else "untranslated"


def _matches_status(payload, status) -> bool:
	if status == "translated":
		return _is_translated(payload)
	if status == "untranslated":
		return not _is_translated(payload)
	if status == "changed":
		return payload["changed"]
	return True


def _matches_kind(payload, kind) -> bool:
	if not kind:
		return True
	return payload.get("kind") == kind


def _matches_search(payload, search) -> bool:
	if not search:
		return True
	haystack = " ".join(
		[
			payload["source_text"] or "",
			payload["context"] or "",
			payload["current_translation"] or "",
			payload["source_path"] or "",
			payload["app"] or "",
			payload["module"] or "",
			payload["kind"] or "",
			payload["location"] or "",
		]
	)
	return search.casefold() in haystack.casefold()


def _sort_payloads(payloads, sort_by, sort_order):
	"""Order payloads by a derived column, with the empty values last.

	The input already arrives in a deterministic order (app, source_text,
	context) from the index query, and ``sorted`` is stable, so equal values keep
	that order. Pagination therefore continues correctly across pages.
	"""
	field = PAYLOAD_SORT_COLUMNS.get(sort_by)
	if not field:
		return payloads
	ordered = sorted(payloads, key=lambda item: item.get(field) or "", reverse=sort_order == "desc")
	# An empty kind, location, translation or status means "nothing could be
	# determined". Those rows belong at the end in both directions.
	return sorted(ordered, key=lambda item: not (item.get(field) or ""))


def list_apps() -> list[str]:
	require_system_manager()
	found = set(frappe.get_installed_apps(_ensure_on_bench=True))
	stored = frappe.db.sql(f"select distinct app from `tab{SOURCE_DOCTYPE}`", pluck=True)
	found.update(app for app in stored if app)
	return sorted(found)


def get_rows(search=None, app=None, status=None, kind=None, start=0, page_length=50, sort_by=None, sort_order=None):
	require_system_manager()
	start = max(cint(start), 0)
	page_length = min(max(cint(page_length) or 50, 1), 100)
	search = (search or "").strip()
	app = (app or "").strip()
	kind = (kind or "").strip()
	status = status or "all"
	sort_by = (sort_by or "").strip()
	sort_order = "desc" if (sort_order or "").strip().casefold() == "desc" else "asc"
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
	if search and _search_narrows(search):
		query = _narrow_by_search(query, table, search)
	# Sorting by a column that only exists in the payload (نوع, محل استفاده,
	# ترجمه فارسی, وضعیت) needs every matching row in memory, so it takes the
	# same path as a search. Sorting by a real column stays in SQL and keeps the
	# fast page. Either path ends with a unique tiebreaker, so page two always
	# continues page one instead of repeating or skipping rows.
	std_column = SQL_SORT_COLUMNS.get(sort_by)
	python_sort = bool(sort_by) and std_column is None
	if std_column:
		query = query.orderby(
			getattr(table, std_column), order=Order.desc if sort_order == "desc" else Order.asc
		).orderby(table.name)
	else:
		# The fallback order every unsorted read shares. Without it the database is
		# free to return a different slice for the same offset on the next request,
		# so page two could repeat or skip rows, a payload sort would break its
		# ties in whatever order the server happened to pick, and an export would
		# rank its rows in an order the grid never showed.
		query = query.orderby(table.app).orderby(table.source_text).orderby(table.context).orderby(table.name)
	needs_python_filter = bool(search) or bool(kind) or status != "all" or python_sort
	if needs_python_filter:
		records = query.run(as_dict=True)
		prefetch(row.source_path for row in records)
		payloads = []
		for row in records:
			payload = _row_payload(row)
			if _matches_search(payload, search) and _matches_status(payload, status) and _matches_kind(payload, kind):
				payloads.append(payload)
		if python_sort:
			payloads = _sort_payloads(payloads, sort_by, sort_order)
		total = len(payloads)
		page = payloads[start : start + page_length]
	else:
		total = frappe.db.count(SOURCE_DOCTYPE, {"app": app} if app else {})
		records = (
			query.offset(start).limit(page_length).run(as_dict=True)
		)
		prefetch(row.source_path for row in records)
		page = [_row_payload(row) for row in records]
	return {
		"rows": page,
		"total": total,
		"start": start,
		"page_length": page_length,
		"scan": get_scan_status(),
		"apps": sorted(set(frappe.get_installed_apps(_ensure_on_bench=True))),
		"kinds": list(KIND_LABELS),
	}


def _assert_safe_translation(source: str, translated: str, context: str = ""):
	"""Refuse anything Frappe would store differently from what the user typed."""
	finding = check_translation(source, translated, context)
	if finding:
		frappe.throw(finding.reason + (f" {finding.action}" if finding.action else ""))


def save_translations(rows):
	"""Write pending values that differ from what Frappe currently renders.

	A row that already holds the requested value is a no-op, so saving twice never
	writes twice.
	"""
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
		_upsert_translation(source, context, translated, app=row.get("app") or "")
		saved += 1
	if saved:
		clear_translation_caches()
	return {"saved": saved}


def _upsert_translation(source: str, context: str, translated: str, app: str = ""):
	"""Update the row that holds exactly this source and context, or insert a new one.

	The `source_text` column uses the case-insensitive `utf8mb4_unicode_ci` collation,
	so the rows Frappe returns for a filter are narrowed to an exact match here.
	Spellings that differ only in capitalization therefore stay separate rows and
	keep separate values; two spellings are never merged into one.

	This is the only place a Persian row is written, so it is also the only place
	ownership is claimed: a restore may only remove rows recorded here.
	"""
	matches = frappe.get_all(
		"Translation",
		filters={"language": "fa", "source_text": source},
		fields=["name", "context", "source_text"],
		limit_page_length=0,
	)
	matches = [
		row for row in matches if (row.context or "") == (context or "") and row.source_text == source
	]
	if matches:
		for row in matches:
			doc = frappe.get_doc("Translation", row.name)
			doc.language = "fa"
			doc.translated_text = translated
			doc.context = context or ""
			doc.save()
		ownership.record(source, context or "", translated, app=app)
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
	ownership.record(source, context or "", translated, app=app)


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


def _filtered_payloads(search=None, app=None, status=None, kind=None, sort_by=None, sort_order="asc"):
	"""Every matching payload, for export.

	The rows are read page by page and sorted once here at the end: sorting each
	page of a paged read would order the workbook per batch instead of per column.
	"""
	page_length = 100
	start = 0
	rows = []
	# A column the database can order is requested that way and is not touched
	# again: the database orders text with its own collation, so ranking it in
	# Python afterwards would list the workbook in an order the grid never showed.
	# A column that exists only in the payload is read in the deterministic
	# fallback order and ranked once, below.
	sql_column = sort_by in SQL_SORT_COLUMNS
	while True:
		batch = get_rows(
			search=search,
			app=app,
			status=status,
			kind=kind,
			start=start,
			page_length=page_length,
			sort_by=sort_by if sql_column else None,
			sort_order=sort_order if sql_column else None,
		)
		rows.extend(batch["rows"])
		start += page_length
		if start >= batch["total"]:
			break
		if not batch["rows"]:
			break
	if sort_by in PAYLOAD_SORT_COLUMNS and not sql_column:
		return _sort_payloads(rows, sort_by, sort_order)
	return rows


def export_excel(search=None, app=None, status=None, kind=None, sort_by=None, sort_order=None):
	require_system_manager()
	rows = _filtered_payloads(search, app, status, kind, sort_by, sort_order or "asc")
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
	"""Queue a workbook preview. Returns immediately; the browser polls the operation.

	Reading and classifying a workbook is proportional to its size, so it never
	runs inside the request.
	"""
	return operations.start_import(file_url, preview=1)


def apply_import(file_url):
	"""Queue a workbook apply. The worker batches, checkpoints and can be resumed.

	An undo snapshot (`pre_apply`) is captured by the worker itself, before its
	first write, so an unwanted apply is revertible and the HTTP request returns
	immediately.
	"""
	return operations.start_import(file_url)


def preview_restore(snapshot, mode="full", remove_fonts=0):
	"""Queue a read-only preview of what restoring a snapshot would change.

	Nothing is written by the preview itself. Building the plan reads every
	Persian translation row and every lock, so it runs in the worker exactly like
	the restore it describes; the browser polls the operation for the report.
	"""
	return operations.start_restore_preview(snapshot, mode=mode, remove_fonts=cint(remove_fonts))


def restore_snapshot(snapshot, mode="full", remove_fonts=0, confirm=0):
	"""Queue a restore. Refused while another operation is active."""
	return operations.start_restore(snapshot, mode=mode, remove_fonts=remove_fonts, confirm=confirm)


def publish_catalogue():
	"""Merge Frappe/ERPNext-owned fa overrides into this app's fa.csv. Does not use write_translations_file."""
	require_system_manager()
	result = publish_overrides(catalogue_path(), load_overrides())
	if result["updated"] or result["appended"]:
		clear_translation_caches()
	return result
