import csv
from pathlib import Path
import shutil

import frappe
from frappe.core.doctype.translation.translation import clear_user_translation_cache


APP_NAME = "smartprocee_erpnext_persiant"


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


def _catalogue_keys():
	path = Path(__file__).parent / "translations" / "fa.csv"
	keys = set()
	with path.open(encoding="utf-8", newline="") as handle:
		for row in csv.reader(handle):
			if len(row) not in (2, 3):
				continue
			source = row[0].replace("\\n", "\n")
			context = row[2].replace("\\n", "\n") if len(row) == 3 else ""
			keys.add((source, context or ""))
	return keys


def after_install():
	"""Back up and remove only pre-existing Persian overrides for catalogue keys."""
	keys = _catalogue_keys()
	for row in frappe.get_all(
		"Translation",
		filters={"language": "fa"},
		fields=[
			"name",
			"language",
			"source_text",
			"translated_text",
			"context",
			"contributed",
			"contribution_status",
			"contribution_docname",
		],
	):
		if (row.source_text, row.context or "") not in keys:
			continue
		frappe.get_doc(
			{
				"doctype": "Persian Translation Backup",
				"source_docname": row.name,
				"language": row.language,
				"source_text": row.source_text,
				"translated_text": row.translated_text,
				"context": row.context,
				"contributed": row.contributed,
				"contribution_status": row.contribution_status,
				"contribution_docname": row.contribution_docname,
			}
		).insert(ignore_permissions=True)
		frappe.delete_doc("Translation", row.name, ignore_permissions=True, force=True)
	clear_user_translation_cache("fa")
	frappe.clear_cache()
	sync_public_assets()


def before_uninstall():
	"""Restore site-level translations displaced during installation."""
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
	clear_user_translation_cache("fa")
	frappe.clear_cache()
	target = _asset_path()
	if target.is_symlink() or target.is_file():
		target.unlink()
	elif target.exists():
		shutil.rmtree(target)
