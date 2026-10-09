import frappe

APP_NAME = "smartprocee_erpnext_persiant"
LEGACY_SIDEBAR = "Persian Translation"
CURRENT_SIDEBAR = "فارسی‌ساز"


def execute():
	"""Drop the empty "Persian Translation" sidebar shipped before v1.2.

	`فارسی‌ساز` is the only sidebar this app ships now. Frappe does not delete a
	standard document that disappeared from an app during model sync, so it is
	removed here. A sidebar that still has items, or that belongs to another app,
	is left alone.
	"""
	if not frappe.db.table_exists("Workspace Sidebar"):
		return
	if not frappe.db.exists("Workspace Sidebar", LEGACY_SIDEBAR):
		return
	if frappe.db.get_value("Workspace Sidebar", LEGACY_SIDEBAR, "app") != APP_NAME:
		return
	if frappe.get_all(
		"Workspace Sidebar Item",
		filters={"parent": LEGACY_SIDEBAR},
		pluck="name",
		limit_page_length=1,
	):
		return
	if not frappe.db.exists("Workspace Sidebar", CURRENT_SIDEBAR):
		return
	frappe.delete_doc("Workspace Sidebar", LEGACY_SIDEBAR, force=1, ignore_on_trash=1)
