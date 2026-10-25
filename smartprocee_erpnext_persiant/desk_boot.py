"""Translate Desk navigation display labels for a Persian session.

Frappe 16.53 dock items render ``entry.label`` without ``__()``. The
translations already live in this app's catalogue; this hook applies
``_()`` to display fields only. Identifiers such as ``link_to`` and
``module`` are left unchanged. English sessions are not touched.
"""

from __future__ import annotations

import frappe
from frappe import _


def apply_boot_display_translations(bootinfo) -> None:
	lang = str(getattr(frappe.local, "lang", "") or "")
	if not lang.startswith("fa") or not isinstance(bootinfo, dict):
		return
	_translate_sidebars(bootinfo.get("module_sidebars"))
	_translate_app_data(bootinfo.get("app_data"))
	_translate_icon_labels(bootinfo.get("desktop_icons"))


def _translate_sidebars(sidebars) -> None:
	if not isinstance(sidebars, dict):
		return
	for sidebar in sidebars.values():
		_translate_display(sidebar, "label")


def _translate_app_data(apps) -> None:
	if not isinstance(apps, list):
		return
	for app in apps:
		if not isinstance(app, dict):
			continue
		_translate_display(app, "title")
		for row in app.get("dock") or []:
			_translate_display(row, "title")
			_translate_display(row, "label")


def _translate_icon_labels(icons) -> None:
	if not isinstance(icons, list):
		return
	for icon in icons:
		_translate_display(icon, "label")


def _translate_display(row, key: str) -> None:
	if not isinstance(row, dict):
		return
	value = row.get(key)
	if value:
		row[key] = _(value)
