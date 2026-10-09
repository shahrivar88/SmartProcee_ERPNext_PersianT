import frappe

from smartprocee_erpnext_persiant.persian_translation.doctype.persian_font_family.persian_font_family import (
	SKIP_RESTORE_POINT,
)
from smartprocee_erpnext_persiant.persian_translation.system_font import storage

FAMILY = "Persian Font Family"
LEGACY_SOURCE = "Bundled"


def execute():
	"""Drop the font family registered from files shipped before v1.2.

	The app no longer ships font files, so the family points at assets that no
	longer exist. If it was the active font, the site falls back to the default
	font stack. Uploaded families are left alone.
	"""
	if not frappe.db.table_exists(FAMILY):
		return
	for row in frappe.get_all(FAMILY, filters={"source": LEGACY_SOURCE}, fields=["name", "is_active"]):
		if row.is_active:
			storage.clear_active_css()
			frappe.db.set_value(FAMILY, row.name, "is_active", 0, update_modified=False)
		frappe.delete_doc(FAMILY, row.name, force=1, flags={SKIP_RESTORE_POINT: True})
