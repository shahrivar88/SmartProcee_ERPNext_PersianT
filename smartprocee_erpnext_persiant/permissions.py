import frappe


def has_app_permission():
	"""Desk app list visibility. Page roles and API checks remain the real gate."""
	return "System Manager" in set(frappe.get_roles())


EXPORT_FILE_PREFIX = "persian-translations-PTOP-"


def file_has_permission(doc, ptype=None, user=None, debug=False):
	"""Deny other users a Persianizer Excel export. Leave every other File alone.

	Frappe 16.53 serves ``/private/files/`` through ``File.is_downloadable``,
	which follows the attached document. An export attached to
	``Persian Translation Operation`` would then be readable by any System
	Manager. This hook refuses those files unless the caller is Administrator
	or the file owner. Unrelated Files return True so Frappe's own File rules
	keep working.
	"""
	user = user or frappe.session.user
	if user == "Administrator" or not _is_excel_export_file(doc):
		return True
	if user in ("Guest", "") or user != (doc.owner or ""):
		return False
	return "System Manager" in set(frappe.get_roles(user))


def file_query_conditions(user=None) -> str:
	"""Hide other users' export workbooks from File lists. Other Files are unchanged."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""
	return (
		f"(`tabFile`.`file_name` not like {frappe.db.escape(EXPORT_FILE_PREFIX + '%')}"
		f" or `tabFile`.`owner` = {frappe.db.escape(user)})"
	)


def _is_excel_export_file(doc) -> bool:
	name = getattr(doc, "file_name", None) or ""
	if name.startswith(EXPORT_FILE_PREFIX) and name.lower().endswith(".xlsx"):
		return True
	if getattr(doc, "attached_to_doctype", None) != "Persian Translation Operation":
		return False
	attached = getattr(doc, "attached_to_name", None)
	if not attached:
		return False
	return frappe.db.get_value("Persian Translation Operation", attached, "kind") == "excel_export"
