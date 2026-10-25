"""The Persianizer home icon. Not a Workspace Sidebar.

Frappe 16.53 hides nested Desktop Icons unless the parent is a visible
top-level icon, and it no longer accepts ``link_type=Page``. This module
keeps one standard home icon that opens Translation Manager.
"""

from __future__ import annotations

import frappe

from smartprocee_erpnext_persiant.install import APP_NAME, MENU_LABEL, PAGE_ROUTE

ICON = "Desktop Icon"
HOME_LINK = f"/app/{PAGE_ROUTE}"
ICON_NAME = MENU_LABEL


def ensure_home_icon() -> str | None:
	"""Create or repair the standard home icon. Does not create a Sidebar.

	A user-hidden standard icon stays hidden. A non-standard row of the same
	name is left alone so a personal shortcut is not overwritten.
	"""
	if not frappe.db.table_exists(ICON):
		return None
	values = _icon_values()
	if frappe.db.exists(ICON, ICON_NAME):
		doc = frappe.get_doc(ICON, ICON_NAME)
		if not cint(doc.standard):
			return doc.name
		changed = False
		for field, value in values.items():
			if field == "hidden":
				continue
			if getattr(doc, field, None) != value:
				setattr(doc, field, value)
				changed = True
		if not _has_system_manager_role(doc):
			doc.append("roles", {"role": "System Manager"})
			changed = True
		if changed:
			doc.flags.ignore_permissions = True
			doc.save()
	else:
		doc = frappe.new_doc(ICON)
		doc.update(values)
		doc.append("roles", {"role": "System Manager"})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_links=True)
	_clear_desktop_icon_cache()
	return ICON_NAME


def _icon_values() -> dict:
	values = {
		"label": ICON_NAME,
		"standard": 1,
		"hidden": 0,
		"icon": "languages",
		"link": HOME_LINK,
		"parent_icon": "",
		"restrict_removal": 0,
	}
	if not frappe.db.table_exists(ICON):
		return values
	meta = frappe.get_meta(ICON)
	link_type = _field_options(meta, "link_type")
	if "External" in link_type:
		values["link_type"] = "External"
		values["link_to"] = ""
	elif "Page" in link_type:
		values["link_type"] = "Page"
		values["link_to"] = PAGE_ROUTE
	if meta.has_field("icon_type"):
		icon_types = _field_options(meta, "icon_type")
		values["icon_type"] = "Link" if "Link" in icon_types else (icon_types[0] if icon_types else "Link")
	if frappe.db.has_column(ICON, "app"):
		values["app"] = APP_NAME
	return values


def _field_options(meta, fieldname: str) -> list[str]:
	field = meta.get_field(fieldname)
	if not field:
		return []
	return [item.strip() for item in (field.options or "").split("\n") if item.strip()]


def _has_system_manager_role(doc) -> bool:
	return any(row.role == "System Manager" for row in (doc.roles or []))


def _clear_desktop_icon_cache() -> None:
	try:
		from frappe.desk.desktop_icon import clear_desktop_icons_cache

		clear_desktop_icons_cache()
	except (ImportError, AttributeError):
		frappe.clear_cache()


def cint(value) -> int:
	from frappe.utils import cint as _cint

	return _cint(value)
