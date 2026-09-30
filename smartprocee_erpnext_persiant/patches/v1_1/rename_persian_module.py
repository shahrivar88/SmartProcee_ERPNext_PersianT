import frappe

OLD_MODULE = "SmartProcee_ERPNext_PersianT"
NEW_MODULE = "Persian Translation"
APP_NAME = "smartprocee_erpnext_persiant"


def execute():
	"""Point existing metadata at the portable module name.

	Frappe refuses to rename a standard Module Def. Create the new record,
	move links, then delete the old record. A fresh install has no old record.
	"""
	if not frappe.db.exists("Module Def", OLD_MODULE):
		return
	if not frappe.db.exists("Module Def", NEW_MODULE):
		frappe.get_doc(
			{
				"doctype": "Module Def",
				"module_name": NEW_MODULE,
				"app_name": APP_NAME,
				"custom": 0,
			}
		).insert(ignore_permissions=True)
	_repoint(OLD_MODULE, NEW_MODULE)
	frappe.delete_doc("Module Def", OLD_MODULE, ignore_permissions=True, force=True)


def _repoint(old, new):
	for doctype in ("DocType", "Page", "Report", "Workspace", "Dashboard", "Web Form", "Workspace Sidebar"):
		if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, "module"):
			continue
		for name in frappe.get_all(doctype, filters={"module": old}, pluck="name"):
			frappe.db.set_value(doctype, name, "module", new, update_modified=False)
