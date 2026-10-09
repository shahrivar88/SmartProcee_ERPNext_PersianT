import json

import frappe
from frappe.model.utils.user_settings import get_user_settings, sync_user_settings, update_user_settings
from frappe.utils import cint

from smartprocee_erpnext_persiant.persian_translation import operations, schema, snapshots
from smartprocee_erpnext_persiant.persian_translation.service import (
	apply_import as _apply_import,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	export_excel as _export_excel,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	get_rows as _get_rows,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	preview_import as _preview_import,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	preview_restore as _preview_restore,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	publish_catalogue as _publish_catalogue,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	restore_snapshot as _restore_snapshot,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	save_translations as _save_translations,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	scan_status as _scan_status,
)
from smartprocee_erpnext_persiant.persian_translation.service import (
	start_scan as _start_scan,
)
from smartprocee_erpnext_persiant.persian_translation.service import require_system_manager

VIEW_SETTINGS = "persian-translation-manager"
# The columns of the table. `save_column_widths` accepts nothing else, so a stale
# browser cannot write widths for a column that no longer exists.
COLUMN_IDS = (
	"app",
	"kind",
	"location",
	"source_text",
	"translation",
	"status",
)
MIN_COLUMN_WIDTH = 40
MAX_COLUMN_WIDTH = 1600

# Every endpoint below reads or writes the tables this app adds through
# `bench migrate`. `schema.require_ready()` turns an un-migrated site into one
# clear Persian message instead of a raw "DocType ... not found" from a query.
# The manager only needs the translation tables; the RTL tables are a separate
# feature and their absence must not block translation work.
require_schema = schema.guard(doctypes=schema.TRANSLATION_DOCTYPES)


@frappe.whitelist()
@require_schema
def get_rows(search=None, app=None, status=None, kind=None, start=0, page_length=50, sort_by=None, sort_order=None):
	return _get_rows(
		search=search,
		app=app,
		status=status,
		kind=kind,
		start=start,
		page_length=page_length,
		sort_by=sort_by,
		sort_order=sort_order,
	)


@frappe.whitelist(methods=["POST"])
@require_schema
def save_translations(rows):
	return _save_translations(rows)


@frappe.whitelist(methods=["POST"])
@require_schema
def start_scan():
	return _start_scan()


@frappe.whitelist()
@require_schema
def scan_status():
	return _scan_status()


@frappe.whitelist()
@require_schema
def export_excel(search=None, app=None, status=None, kind=None, sort_by=None, sort_order=None):
	return _export_excel(
		search=search,
		app=app,
		status=status,
		kind=kind,
		sort_by=sort_by,
		sort_order=sort_order,
	)


@frappe.whitelist(methods=["POST"])
@require_schema
def preview_import(file_url):
	return _preview_import(file_url)


@frappe.whitelist(methods=["POST"])
@require_schema
def apply_import(file_url):
	return _apply_import(file_url)


@frappe.whitelist()
@require_schema
def operation_status(name):
	require_system_manager()
	return operations.get_operation(name)


@frappe.whitelist()
@require_schema
def operation_list(limit=20):
	return operations.list_operations(limit=limit)


@frappe.whitelist(methods=["POST"])
@require_schema
def operation_cancel(name):
	return operations.cancel_operation(name)


@frappe.whitelist(methods=["POST"])
@require_schema
def operation_resume(name):
	return operations.resume_operation(name)


@frappe.whitelist()
@require_schema
def operation_errors(name):
	require_system_manager()
	return operations.export_errors(name)


@frappe.whitelist()
@require_schema
def snapshot_list(limit=100):
	require_system_manager()
	return snapshots.list_snapshots(limit=cint(limit) or 100)


@frappe.whitelist(methods=["POST"])
@require_schema
def snapshot_capture(label=None):
	require_system_manager()
	return snapshots.capture(snapshots.MANUAL, (label or "").strip() or "نسخهٔ دستی")


@frappe.whitelist(methods=["POST"])
@require_schema
def snapshot_preview(name, mode="full", remove_fonts=0):
	return _preview_restore(name, mode=mode, remove_fonts=remove_fonts)


@frappe.whitelist(methods=["POST"])
@require_schema
def snapshot_restore(name, mode="full", remove_fonts=0, confirm=0):
	return _restore_snapshot(name, mode=mode, remove_fonts=remove_fonts, confirm=confirm)


@frappe.whitelist(methods=["POST"])
@require_schema
def publish_catalogue():
	return _publish_catalogue()


def _clean_column_widths(column_widths) -> dict:
	incoming = frappe.parse_json(column_widths) if isinstance(column_widths, str) else column_widths
	if not isinstance(incoming, dict):
		frappe.throw("اندازه ستون‌ها نامعتبر است.")
	cleaned = {}
	for column_id in COLUMN_IDS:
		if column_id not in incoming:
			continue
		width = cint(incoming.get(column_id))
		if MIN_COLUMN_WIDTH <= width <= MAX_COLUMN_WIDTH:
			cleaned[column_id] = width
	return cleaned


@frappe.whitelist(methods=["POST"])
def save_column_widths(column_widths):
	"""Store this user's column widths through the standard Frappe user-settings API.

	`update_user_settings(..., for_update=True)` writes the Redis-cached copy; the
	framework normally flushes that cache from the browser, so we flush it here
	with `sync_user_settings()` to keep the settings durable after a cache clear.
	"""
	require_system_manager()
	cleaned = _clean_column_widths(column_widths)
	current = json.loads(get_user_settings(VIEW_SETTINGS) or "{}")
	if not isinstance(current, dict):
		current = {}
	current["column_widths"] = cleaned
	update_user_settings(VIEW_SETTINGS, json.dumps(current, separators=(",", ":")), for_update=True)
	sync_user_settings()
	return cleaned
