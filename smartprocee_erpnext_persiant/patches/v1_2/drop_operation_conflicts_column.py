import frappe

DOCTYPE = "Persian Translation Operation"
COLUMN = "conflicts"


def execute():
	"""Drop the `conflicts` column the rejected conflict check left behind.

	The field is gone from the DocType, and `bench migrate` never drops a column it
	no longer knows about. The value was a per-run count shown only by the removed
	feature, so nothing reads it any more. Only this one column of this one table is
	touched; a site that never had it, or already lost it, is left alone.
	"""
	if not frappe.db.table_exists(DOCTYPE):
		return
	if frappe.get_meta(DOCTYPE).has_field(COLUMN):
		return
	_forget_cached_columns()
	if not frappe.db.has_column(DOCTYPE, COLUMN):
		return
	frappe.db.sql_ddl(f"ALTER TABLE `tab{DOCTYPE}` DROP COLUMN IF EXISTS `{COLUMN}`")
	_forget_cached_columns()


def _forget_cached_columns():
	"""The column list is cached; read the live table, not an earlier answer."""
	frappe.client_cache.delete_value(f"table_columns::tab{DOCTYPE}")
