import frappe

from smartprocee_erpnext_persiant.install import delete_legacy_external_icon


def execute():
	"""Drop the old home shortcut that used a space and an absolute URL.

	The standard Desktop Icon is imported from this app during model sync.
	This patch only removes the non-standard External shortcut, so a second
	migrate does not recreate it.
	"""
	delete_legacy_external_icon()
