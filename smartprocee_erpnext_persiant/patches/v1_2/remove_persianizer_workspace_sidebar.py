import frappe

APP_NAME = "smartprocee_erpnext_persiant"
OWNED_SIDEBARS = ("فارسی‌ساز", "Persian Translation")


def execute():
	"""Remove Persianizer-owned Desk Sidebar entries. Keep the home icon.

	The owner decision for 1.2.1 is that this app must not appear in the right
	Sidebar. Translation Manager stays on the Desktop Icon, Apps screen and
	navbar. A sidebar that belongs to another app is left in place.
	"""
	if not frappe.db.table_exists("Workspace Sidebar"):
		return
	has_app = frappe.db.has_column("Workspace Sidebar", "app")
	for name in OWNED_SIDEBARS:
		if not frappe.db.exists("Workspace Sidebar", name):
			continue
		if has_app:
			owner = frappe.db.get_value("Workspace Sidebar", name, "app")
			if owner and owner != APP_NAME:
				continue
		frappe.delete_doc("Workspace Sidebar", name, force=1, ignore_on_trash=1)
