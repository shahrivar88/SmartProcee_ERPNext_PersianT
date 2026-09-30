import json

import frappe
from frappe.model.utils.user_settings import get_user_settings, update_user_settings
from frappe.utils import cint

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
	publish_catalogue as _publish_catalogue,
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
COLUMN_IDS = (
	"app",
	"origin",
	"source_text",
	"context",
	"current_translation",
	"new_translation",
)
MIN_COLUMN_WIDTH = 40
MAX_COLUMN_WIDTH = 1600


@frappe.whitelist()
def get_rows(search=None, app=None, status=None, kind=None, start=0, page_length=50):
	return _get_rows(search, app, status, kind, start, page_length)


@frappe.whitelist()
def save_translations(rows):
	return _save_translations(rows)


@frappe.whitelist()
def start_scan():
	return _start_scan()


@frappe.whitelist()
def scan_status():
	return _scan_status()


@frappe.whitelist()
def export_excel(search=None, app=None, status=None, kind=None):
	return _export_excel(search, app, status, kind)


@frappe.whitelist()
def preview_import(file_url):
	return _preview_import(file_url)


@frappe.whitelist()
def apply_import(file_url):
	return _apply_import(file_url)


@frappe.whitelist()
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


@frappe.whitelist()
def save_column_widths(column_widths):
	"""Store this user's column widths in Frappe user settings, written through to the database."""
	require_system_manager()
	cleaned = _clean_column_widths(column_widths)
	current = json.loads(get_user_settings(VIEW_SETTINGS) or "{}")
	if not isinstance(current, dict):
		current = {}
	current["column_widths"] = cleaned
	payload = json.dumps(current, separators=(",", ":"))
	update_user_settings(VIEW_SETTINGS, payload, for_update=True)
	frappe.db.sql(
		"""INSERT INTO `__UserSettings` (`user`, `doctype`, `data`)
		VALUES (%s, %s, %s)
		ON DUPLICATE KEY UPDATE `data`=%s""",
		(frappe.session.user, VIEW_SETTINGS, payload, payload),
	)
	return cleaned
