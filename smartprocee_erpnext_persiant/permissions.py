import frappe


def has_app_permission():
	"""Desk app list visibility. Page roles and API checks remain the real gate."""
	return "System Manager" in set(frappe.get_roles())
