"""Display-only helpers for ERPNext Account labels.

``Long-term Provisions`` is a stored Account name and an Account Category
document name. The catalogue already translates the phrase. This module never
writes that stored value; it only decides what a Persian session should show
and turns on Frappe's standard ``translated_doctype`` flag for Account Category
so Link fields use ``__()``.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.translate import get_all_translations

ACCOUNT_CATEGORY = "Account Category"
CALL_LOGS = "Call Logs"
CALL_LOGS_FA = "گزارش‌های تماس"
ROLE = "Role"
# Third-party role titles that this app's fa.csv must not absorb.
DISPLAY_STRINGS = {
	CALL_LOGS: CALL_LOGS_FA,
	"Insights User": "کاربر Insights",
	"Raven Admin": "مدیر Raven",
	"Employee Self Service": "خودخدمتی کارکنان",
}
TRANSLATED_DOCTYPES = (ACCOUNT_CATEGORY, ROLE, "Customer", "Supplier")


def display_label(source: str, lang: str | None = None) -> str:
	"""Return the Persian catalogue label, or the original stored value."""
	source = source or ""
	lang = lang or getattr(frappe.local, "lang", None) or ""
	if not source or not str(lang).startswith("fa"):
		return source
	return get_all_translations(lang).get(source) or source


def ensure_display_translations() -> None:
	"""Install display-only lookups and translated_doctype flags this site needs."""
	ensure_account_category_translated()
	for doctype in TRANSLATED_DOCTYPES:
		ensure_translated_doctype(doctype)
	for source, translated in DISPLAY_STRINGS.items():
		ensure_translation_row(source, translated)


def ensure_account_category_translated() -> None:
	"""Mark Account Category as a translated DocType without editing ERPNext."""
	ensure_translated_doctype(ACCOUNT_CATEGORY)


def ensure_translated_doctype(doctype: str) -> None:
	"""Turn on Frappe's standard ``translated_doctype`` flag without a core edit.

	A Property Setter the site already has — including a user who turned the
	flag off — is left alone. ``make_property_setter`` inserts a new row and
	drops the previous one, so calling it again would silently overwrite.
	"""
	if not frappe.db.exists("DocType", doctype):
		return
	if frappe.db.exists(
		"Property Setter",
		{
			"doc_type": doctype,
			"property": "translated_doctype",
			"doctype_or_field": "DocType",
		},
	):
		return
	if frappe.get_meta(doctype).translated_doctype:
		return
	make_property_setter(
		doctype,
		"",
		"translated_doctype",
		"1",
		"Check",
		for_doctype=True,
		validate_fields_for_doctype=False,
	)
	frappe.clear_cache(doctype=doctype)


def ensure_call_logs_translation() -> None:
	"""Ship the CRM sidebar label that the public catalogue cannot own."""
	ensure_translation_row(CALL_LOGS, CALL_LOGS_FA)


def ensure_translation_row(source: str, translated: str) -> None:
	"""Insert a Translation row once. Existing rows, including operator edits, stay.

	These strings are not Frappe/ERPNext catalogue sources, so they must not go
	into ``fa.csv``. A Translation row is the lookup ``__()`` already reads.
	"""
	if not source or frappe.db.exists("Translation", {"language": "fa", "source_text": source}):
		return
	frappe.get_doc(
		{
			"doctype": "Translation",
			"language": "fa",
			"source_text": source,
			"translated_text": translated,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache()
	if hasattr(frappe.translate, "clear_cache"):
		frappe.translate.clear_cache()
