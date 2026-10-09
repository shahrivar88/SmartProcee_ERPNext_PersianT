import frappe

DOCTYPE = "Persian Translation Final"
TABLE = "tabPersian Translation Final"


def execute():
	"""Remove the rejected `Persian Translation Final` product feature from the site.

	A `ترجمه نهایی` lock -- one approved Persian value per (source, context) -- was
	rejected by the human: different Persian values for the same English source are
	legitimate when the context differs. The DocType and its code are gone, so the
	framework no longer creates the table and `bench migrate` never drops a table it
	did not create.

	Two safety rules:

	* The table is dropped only while it is empty. If a site somehow holds lock
	  rows, the patch keeps both the DocType and the table and records a message,
	  so no approval decision is destroyed silently.
	* Only this one exact DocType and this one exact table are touched.
	"""
	if not frappe.db.table_exists(DOCTYPE):
		_remove_doctype()
		return
	if frappe.db.count(DOCTYPE):
		frappe.msgprint(
			f"«{DOCTYPE}» {frappe.db.count(DOCTYPE)} ردیف دارد و حذف نشد؛"
			" این فیچر منسوخ شده است و باید دستی بررسی شود.",
			indicator="orange",
		)
		return
	_remove_doctype()
	frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `{TABLE}`")


def _remove_doctype():
	"""Delete the DocType metadata and its fields/permissions through the framework."""
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	frappe.delete_doc("DocType", DOCTYPE, force=1, ignore_on_trash=1, ignore_permissions=True)
