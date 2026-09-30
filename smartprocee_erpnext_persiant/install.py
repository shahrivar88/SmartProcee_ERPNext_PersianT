from pathlib import Path
import shutil

import frappe
from frappe.core.doctype.translation.translation import clear_user_translation_cache

from smartprocee_erpnext_persiant.persian_translation.system_font.bundled import register_bundled_family
from smartprocee_erpnext_persiant.persian_translation.system_font.storage import remove_managed_files


APP_NAME = "smartprocee_erpnext_persiant"
MENU_LABEL = "فارسی‌ساز"
PAGE_ROUTE = "persian-translation-manager"


def _asset_path():
	return Path(frappe.get_site_path()).parent / "assets" / APP_NAME


def sync_public_assets():
	"""Copy this app's static assets into the shared sites volume.

	A real copy is intentional: it remains available to a separate nginx/frontend
	container even when that container cannot resolve bench-generated symlinks.
	Running migrate refreshes the copy after every app update.
	"""
	source = Path(frappe.get_app_path(APP_NAME, "public"))
	target = _asset_path()
	if target.is_symlink() or target.is_file():
		target.unlink()
	elif target.exists():
		shutil.rmtree(target)
	shutil.copytree(source, target)


def after_install():
	"""Install font assets. Administrator Translation rows are left in place."""
	clear_user_translation_cache("fa")
	frappe.clear_cache()
	sync_public_assets()
	register_bundled_family()


def restore_displaced_translations():
	"""Restore backups from older installs only when that exact key is missing.

	An existing fa Translation, including one created in Persian Translation Manager,
	is never overwritten or deleted.
	"""
	if not frappe.db.table_exists("Persian Translation Backup"):
		return
	for row in frappe.get_all("Persian Translation Backup", fields=["name"], order_by="creation"):
		backup = frappe.get_doc("Persian Translation Backup", row.name)
		filters = {"language": backup.language, "source_text": backup.source_text}
		existing = frappe.get_all("Translation", filters=filters, fields=["name", "context"])
		if any((item.context or "") == (backup.context or "") for item in existing):
			continue
		frappe.get_doc(
			{
				"doctype": "Translation",
				"language": backup.language,
				"source_text": backup.source_text,
				"translated_text": backup.translated_text,
				"context": backup.context,
				"contributed": backup.contributed,
				"contribution_status": backup.contribution_status,
				"contribution_docname": backup.contribution_docname,
			}
		).insert(ignore_permissions=True)


def delete_legacy_external_icon():
	"""Remove a non-standard home shortcut that points at this page by absolute URL."""
	if not frappe.db.table_exists("Desktop Icon"):
		return
	rows = frappe.get_all(
		"Desktop Icon",
		filters={"standard": 0, "link_type": "External"},
		fields=["name", "link"],
	)
	for row in rows:
		if row.link and PAGE_ROUTE in row.link:
			frappe.delete_doc(
				"Desktop Icon",
				row.name,
				ignore_permissions=True,
				force=True,
				ignore_on_trash=True,
			)


def before_uninstall():
	"""Restore previously displaced translations, then remove this site's font files.

	The copy under sites/assets is shared by every site on the bench, so it is left
	in place; other sites may still have this app installed.
	"""
	delete_legacy_external_icon()
	for name in (MENU_LABEL, "Persian Translation"):
		if frappe.db.exists("Workspace Sidebar", name):
			frappe.delete_doc(
				"Workspace Sidebar",
				name,
				ignore_permissions=True,
				force=True,
				ignore_on_trash=True,
			)
	if frappe.db.exists("Desktop Icon", MENU_LABEL):
		frappe.delete_doc(
			"Desktop Icon",
			MENU_LABEL,
			ignore_permissions=True,
			force=True,
			ignore_on_trash=True,
		)
	restore_displaced_translations()
	remove_managed_files()
	clear_user_translation_cache("fa")
	frappe.clear_cache()
