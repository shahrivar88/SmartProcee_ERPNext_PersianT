from pathlib import Path
import shutil

import frappe
from frappe.core.doctype.navbar_settings.navbar_settings import sync_standard_items
from frappe.core.doctype.translation.translation import clear_user_translation_cache

from smartprocee_erpnext_persiant.persian_translation import snapshots
from smartprocee_erpnext_persiant.persian_translation.system_font.storage import remove_managed_files


APP_NAME = "smartprocee_erpnext_persiant"
MENU_LABEL = "فارسی‌ساز"
PAGE_ROUTE = "persian-translation-manager"


def _asset_root() -> Path | None:
	"""The resolved `sites/assets` directory, or ``None`` when there is not one.

	Resolving first means a `sites/assets` that is itself a symlink to the bench's
	`assets` directory (the normal container layout) is handled correctly, and it
	also means the path this app may delete inside can never be a different one.
	"""
	root = (Path(frappe.get_site_path()).parent / "assets")
	try:
		resolved = root.resolve()
	except OSError:
		return None
	if not resolved.is_dir() or resolved.parent == resolved:
		return None
	return resolved


def _asset_path() -> Path | None:
	"""`<sites>/assets/smartprocee_erpnext_persiant`, or ``None`` if that is not it.

	Every guard lives here: the target is this app's folder inside the resolved
	assets directory and nothing else. No site name and no bench path is
	hard-coded, and a function that returns ``None`` cannot be turned into a
	destructive call by accident.
	"""
	root = _asset_root()
	if root is None:
		return None
	target = root / APP_NAME
	if target.name != APP_NAME or target.parent != root:
		return None
	return target


def _copy_source() -> Path | None:
	"""This app's own `public` directory, and only that directory.

	The folder that gets copied must really be the `public` folder *of this app*:
	a bench that resolves the two calls to different places is a broken layout,
	and refusing it is cheaper than copying something unexpected into the assets
	volume.
	"""
	app_root = Path(frappe.get_app_path(APP_NAME))
	source = Path(frappe.get_app_path(APP_NAME, "public"))
	try:
		resolved_root = app_root.resolve()
		resolved = source.resolve()
	except OSError:
		return None
	if resolved.name != "public" or resolved.parent != resolved_root:
		return None
	return resolved


def sync_public_assets():
	"""Copy this app's static assets into the shared sites volume.

	A real copy is intentional: it remains available to a separate nginx/frontend
	container even when that container cannot resolve bench-generated symlinks.
	Running migrate refreshes the copy after every app update.

	The copy is staged next to the target and swapped in only after it succeeded,
	so a missing source or a failed copy leaves the working assets untouched
	instead of deleting them first. Only `<sites>/assets/smartprocee_erpnext_persiant`
	is ever replaced: unrelated assets in the same directory are never touched, and
	a symlink in the target's place is unlinked, never followed.
	"""
	source = _copy_source()
	target = _asset_path()
	if source is None or not source.is_dir():
		_refuse(f"source directory is not this app's public folder: {source}")
		return
	if target is None:
		_refuse(
			"no safe app-owned assets directory under "
			f"{Path(frappe.get_site_path()).parent / 'assets'}"
		)
		return
	staging = target.parent / f".{APP_NAME}.staging"
	_remove(staging)
	try:
		shutil.copytree(source, staging)
	except Exception:
		_remove(staging)
		raise
	try:
		_replace_assets(target, staging)
	except Exception:
		_remove(staging)
		raise


def _refuse(reason: str) -> None:
	frappe.log_error(title="Persian assets not copied", message=reason)


def _remove(path: Path) -> None:
	"""Remove a file, a symlink or a directory tree -- never through a symlink."""
	if path.is_symlink() or path.is_file():
		path.unlink()
	elif path.is_dir():
		shutil.rmtree(path)


def _replace_assets(target: Path, staging: Path) -> None:
	_remove(target)
	staging.rename(target)


def ensure_restore_point():
	"""Create the honest restore point for a site this app was already installed on.

	Never runs during an install (the immutable first-install baseline owns that
	case) and never overwrites an existing snapshot.
	"""
	snapshots.ensure_adopted_state()


def compile_native_translations():
	"""Compile this app's Gettext PO into the bench MO file Frappe reads at boot.

	``bench compile-po-to-mo`` uses a process pool. Calling that helper from
	install or migrate can hang, so this compiles only ``fa`` in-process.
	"""
	from frappe.gettext.translate import _compile_translation
	from frappe.translate import clear_cache

	_compile_translation(APP_NAME, "fa", force=True)
	clear_cache()


def after_install():
	"""Install static assets and the Desk menu item. Administrator Translation rows are left in place."""
	compile_native_translations()
	snapshots.capture_install_baseline()
	sync_standard_items()
	from smartprocee_erpnext_persiant.desk_icon import ensure_home_icon
	from smartprocee_erpnext_persiant.persian_translation.account_display import (
		ensure_display_translations,
	)

	ensure_home_icon()
	ensure_display_translations()
	clear_user_translation_cache("fa")
	frappe.clear_cache()
	sync_public_assets()


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
		).insert()


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
			frappe.delete_doc("Desktop Icon", row.name, force=1, ignore_on_trash=1)


def remove_navbar_item():
	"""Remove the Desk menu item now; migrate would only drop it after the app is gone."""
	settings = frappe.get_single("Navbar Settings")
	items = [row for row in settings.settings_dropdown if row.item_label != MENU_LABEL]
	if len(items) != len(settings.settings_dropdown):
		settings.set("settings_dropdown", items)
		settings.save()


def remove_desk_navigation():
	"""Remove every Desk artifact this app installs: menu item, sidebar and icon."""
	remove_navbar_item()
	for name in (MENU_LABEL, "Persian Translation"):
		if frappe.db.exists("Workspace Sidebar", name):
			frappe.delete_doc("Workspace Sidebar", name, force=1, ignore_on_trash=1)
	_remove_owned_module_sidebars()
	if frappe.db.exists("Desktop Icon", MENU_LABEL):
		frappe.delete_doc("Desktop Icon", MENU_LABEL, force=1, ignore_on_trash=1)


def _remove_owned_module_sidebars():
	"""Drop Frappe 16.53 Sidebar rows for this app's modules. Uninstall only."""
	if not frappe.db.exists("DocType", "Sidebar") or not frappe.db.table_exists("Sidebar"):
		return
	names = frappe.get_all(
		"Sidebar",
		filters={"module": ["in", ["Persian Translation", "Persian RTL"]]},
		pluck="name",
	)
	if frappe.db.exists("Sidebar", MENU_LABEL):
		names.append(MENU_LABEL)
	for name in dict.fromkeys(names):
		frappe.delete_doc("Sidebar", name, force=1, ignore_on_trash=1)


def before_uninstall():
	"""Restore previously displaced translations, then remove this site's font files.

	The copy under sites/assets is shared by every site on the bench, so it is left
	in place; other sites may still have this app installed.
	"""
	delete_legacy_external_icon()
	remove_desk_navigation()
	restore_displaced_translations()
	remove_managed_files()
	clear_user_translation_cache("fa")
	frappe.clear_cache()
