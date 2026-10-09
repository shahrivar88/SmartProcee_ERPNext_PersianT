import hashlib
import json
from pathlib import Path

import frappe
from frappe.gettext.extractors import desktop_icon, module_onboarding, onboarding_step, web_form, workspace, workspace_sidebar
from frappe.gettext.extractors.utils import is_translatable
from frappe.translate import get_messages_for_app
from frappe.utils import now

from smartprocee_erpnext_persiant.persian_translation.kind import comment_text

SCAN_CACHE_KEY = "persian_translation_scan"
SOURCE_DOCTYPE = "Persian Translation Source"


def message_name(app: str, source: str, context: str) -> str:
	digest = hashlib.sha256(f"{app}\x1f{source}\x1f{context}".encode()).hexdigest()[:40]
	return f"PTS-{digest}"


def set_scan_status(**values):
	current = frappe.cache.get_value(SCAN_CACHE_KEY) or {}
	current.update(values)
	frappe.cache.set_value(SCAN_CACHE_KEY, current, expires_in_sec=60 * 60 * 6)


def get_scan_status():
	return frappe.cache.get_value(SCAN_CACHE_KEY) or {"status": "idle"}


def _add(bucket, app, source, context, path, module=""):
	source = (source or "").strip()
	if not source or not is_translatable(source):
		return
	context = context or ""
	if not isinstance(context, str):
		context = str(context)
	app = app or "frappe"
	key = (app, source, context)
	origin = path or ""
	row = bucket.get(key)
	if row:
		if origin and origin not in row["source_path"]:
			combined = f"{row['source_path']} | {origin}" if row["source_path"] else origin
			row["source_path"] = combined[:1000]
		if module and not row["module"]:
			row["module"] = module
		return
	bucket[key] = {
		"app": app,
		"module": module or "",
		"source_path": origin[:1000],
		"source_text": source,
		"context": context,
	}


def _parse_message(item):
	"""Return path, message, runtime context, and an extractor note.

	Extractor comments describe the kind of text. They are not the context
	Frappe passes to _(), so they must not become Translation.context.
	"""
	if not isinstance(item, tuple) or len(item) not in (2, 3, 4):
		return None
	context = ""
	note = ""
	if len(item) == 2:
		path, message = item
	elif len(item) == 3:
		path, message, third = item
		note = comment_text(third)
		if isinstance(third, str) and not note:
			context = third
	else:
		path, message, third, _line = item
		note = comment_text(third)
		if isinstance(third, str) and not note:
			context = third
	if not isinstance(message, str):
		return None
	if path == "Navbar:":
		context = ""
	return path or "", message, context or "", note


def _app_for(module, explicit=None):
	if explicit:
		return explicit
	module_app = frappe.local.module_app or {}
	if not module:
		return ""
	return module_app.get(module) or module_app.get(frappe.scrub(module)) or ""


def _json_extractor(path: Path):
	if path.suffix != ".json":
		return None
	parent = path.parent.name
	grandparent = path.parent.parent.name
	if parent == "desktop_icon":
		return desktop_icon.extract
	if parent == "workspace_sidebar":
		return workspace_sidebar.extract
	if grandparent == "workspace":
		return workspace.extract
	if grandparent == "web_form":
		return web_form.extract
	if grandparent == "onboarding_step":
		return onboarding_step.extract
	if grandparent == "module_onboarding":
		return module_onboarding.extract
	return None


def _extract_json_message(item):
	if not isinstance(item, tuple) or len(item) < 3:
		return None
	message = item[2]
	if not isinstance(message, str):
		return None
	comments = item[3] if len(item) > 3 else []
	if isinstance(comments, (list, tuple)):
		note = "; ".join(str(comment) for comment in comments if comment)
	else:
		note = str(comments or "")
	return message, note


def _scan_json_files(app, bucket):
	root = Path(frappe.get_app_path(app))
	if not root.exists():
		return
	for path in root.rglob("*.json"):
		if "__pycache__" in path.parts or "node_modules" in path.parts:
			continue
		extractor = _json_extractor(path)
		if not extractor:
			continue
		try:
			with path.open(encoding="utf-8") as handle:
				extracted = extractor(handle)
				if extracted is None:
					continue
				items = list(extracted)
		except Exception:
			continue
		relative = str(path.relative_to(root.parent))
		for item in items:
			parsed = _extract_json_message(item)
			if not parsed:
				continue
			message, note = parsed
			origin = relative if not note else f"{relative} ({note})"
			_add(bucket, app, message, "", origin)


def _scan_menu_records(bucket):
	for sidebar in frappe.get_all("Workspace Sidebar", fields=["name", "title", "module", "app"]):
		app = _app_for(sidebar.module, sidebar.app)
		if not app:
			continue
		_add(bucket, app, sidebar.name, "", f"Workspace Sidebar: {sidebar.name}", sidebar.module or "")
		if sidebar.title and sidebar.title != sidebar.name:
			_add(bucket, app, sidebar.title, "", f"Workspace Sidebar title: {sidebar.name}", sidebar.module or "")
		items = frappe.get_all(
			"Workspace Sidebar Item",
			filters={"parent": sidebar.name},
			fields=["label"],
			limit_page_length=0,
		)
		for item in items:
			_add(
				bucket,
				app,
				item.label,
				"",
				f"Workspace Sidebar Item: {sidebar.name}",
				sidebar.module or "",
			)

	for icon in frappe.get_all("Desktop Icon", fields=["label", "app"], limit_page_length=0):
		_add(bucket, icon.app or "frappe", icon.label, "", "Desktop Icon")

	for workspace_doc in frappe.get_all(
		"Workspace",
		fields=["name", "label", "title", "module", "app", "content"],
		limit_page_length=0,
	):
		app = _app_for(workspace_doc.module, workspace_doc.app)
		if not app:
			continue
		_add(bucket, app, workspace_doc.label, "", f"Workspace: {workspace_doc.name}", workspace_doc.module or "")
		if workspace_doc.title and workspace_doc.title != workspace_doc.label:
			_add(bucket, app, workspace_doc.title, "", f"Workspace title: {workspace_doc.name}", workspace_doc.module or "")
		for text in workspace_content_labels(workspace_doc.content):
			_add(bucket, app, text, "", f"Workspace content: {workspace_doc.name}", workspace_doc.module or "")


def _scan_workspace_children(bucket):
	parents = {
		row.name: row
		for row in frappe.get_all("Workspace", fields=["name", "module", "app", "label"], limit_page_length=0)
	}
	child_tables = (
		("Workspace Link", "label", "Workspace Link"),
		("Workspace Link", "description", "Workspace Link description"),
		("Workspace Shortcut", "label", "Workspace Shortcut"),
		("Workspace Chart", "label", "Workspace Chart"),
		("Workspace Number Card", "label", "Workspace Number Card"),
		("Workspace Quick List", "label", "Workspace Quick List"),
	)
	for doctype, fieldname, origin in child_tables:
		if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, fieldname):
			continue
		rows = frappe.get_all(doctype, fields=["parent", fieldname], limit_page_length=0)
		for row in rows:
			parent = parents.get(row.parent)
			if not parent:
				continue
			app = _app_for(parent.module, parent.app)
			if not app:
				continue
			_add(bucket, app, row.get(fieldname), "", f"{origin}: {parent.name}", parent.module or "")


def _consume_message(app, bucket, item, module=""):
	parsed = _parse_message(item)
	if not parsed:
		return
	path, message, context, note = parsed
	if path == "Navbar:" and app != "frappe":
		return
	origin = path or ""
	if note and note not in origin:
		origin = f"{origin} ({note})" if origin else note
	_add(bucket, app, message, context, origin, module)


def _modules_outside_standard_extractor(app):
	"""Module names that scrub/unscrub would change, so Frappe's extractor misses their DocTypes."""
	outside = []
	for module in frappe.get_module_list(app) or []:
		if module != frappe.unscrub(frappe.scrub(module)):
			outside.append(module)
	return outside


def _scan_app_messages(app, bucket, errors):
	"""Collect an app's messages. Returns False when part of the extraction failed."""
	ok = True
	try:
		messages = get_messages_for_app(app, deduplicate=False)
	except Exception as exc:
		errors.append(f"{app}: {exc}")
		ok = False
		messages = []
	for item in messages:
		_consume_message(app, bucket, item)
	modules = _modules_outside_standard_extractor(app)
	if not modules:
		return ok
	from frappe.translate import get_messages_from_doctype, get_messages_from_page

	try:
		for row in frappe.get_all(
			"DocType",
			filters={"module": ["in", modules]},
			fields=["name", "module"],
			limit_page_length=0,
		):
			for item in get_messages_from_doctype(row.name):
				_consume_message(app, bucket, item, row.module or "")
		for page in frappe.get_all(
			"Page",
			filters={"module": ["in", modules]},
			fields=["name", "title", "module"],
			limit_page_length=0,
		):
			_consume_message(app, bucket, (None, page.title or page.name), page.module or "")
			for item in get_messages_from_page(page.name):
				_consume_message(app, bucket, item, page.module or "")
	except Exception as exc:
		errors.append(f"{app}: {exc}")
		ok = False
	return ok


def collect_messages(apps=None):
	"""Return (rows, errors, failed_apps) for the given installed apps."""
	frappe.flags.scanned_files = set()
	installed = list(apps or frappe.get_installed_apps(_ensure_on_bench=True))
	allowed = set(installed)
	bucket = {}
	errors = []
	failed = []
	_scan_menu_records(bucket)
	_scan_workspace_children(bucket)
	for app in installed:
		_scan_json_files(app, bucket)
		if not _scan_app_messages(app, bucket, errors):
			failed.append(app)
	rows = [row for row in bucket.values() if row["app"] in allowed]
	return rows, errors, failed


def replace_index(rows, apps):
	if apps:
		frappe.db.delete(SOURCE_DOCTYPE, {"app": ["in", list(apps)]})
	if not rows:
		return 0
	stamp = now()
	user = frappe.session.user
	values = []
	for row in rows:
		values.append(
			(
				message_name(row["app"], row["source_text"], row["context"]),
				row["app"],
				row["module"],
				row["source_path"],
				row["source_text"],
				row["context"],
				user,
				stamp,
				stamp,
				user,
				0,
				0,
			)
		)
	frappe.db.bulk_insert(
		SOURCE_DOCTYPE,
		[
			"name",
			"app",
			"module",
			"source_path",
			"source_text",
			"context",
			"owner",
			"creation",
			"modified",
			"modified_by",
			"docstatus",
			"idx",
		],
		values,
		chunk_size=200,
	)
	return len(values)


def reconcile_index(installed_apps) -> int:
	"""Drop index rows of apps that are no longer installed.

	Only the scan index (`Persian Translation Source`) is touched. Standard
	`Translation` rows are never removed. An empty installed list is a no-op:
	`frappe.get_installed_apps` returns `[]` while the app list is being built,
	and wiping the whole index there would be destructive.
	"""
	allowed = {app for app in installed_apps if app}
	if not allowed:
		return 0
	indexed = frappe.db.sql(f"select distinct app from `tab{SOURCE_DOCTYPE}`", pluck=True)
	stale = sorted(app for app in indexed if app and app not in allowed)
	for app in stale:
		frappe.db.delete(SOURCE_DOCTYPE, {"app": app})
	return len(stale)


def run_scan(apps=None):
	set_scan_status(status="running", message="در حال اسکن", started=now(), finished="", strings=0, errors=[])
	try:
		full_scan = not apps
		installed = list(apps or frappe.get_installed_apps(_ensure_on_bench=True))
		rows, errors, failed = collect_messages(installed)
		# An app whose extraction failed keeps its previous index rows.
		scanned = [app for app in installed if app not in set(failed)]
		indexable = set(scanned)
		rows = [row for row in rows if row["app"] in indexable]
		count = replace_index(rows, scanned)
		# A full scan knows the complete installed set, so stale apps are dropped.
		removed = reconcile_index(installed) if full_scan else 0
		frappe.db.commit()
		message = f"{count} متن از برنامه‌های نصب‌شده پیدا شد."
		if removed:
			message += f" {removed} برنامهٔ حذف‌شده از ایندکس پاک شد."
		if errors:
			message += " برخی برنامه‌ها خطا داشتند."
		set_scan_status(
			status="success",
			message=message,
			strings=count,
			errors=errors[:20],
			finished=now(),
		)
		return {"strings": count, "errors": errors, "stale_apps_removed": removed}
	except Exception as exc:
		frappe.db.rollback()
		set_scan_status(status="error", message=str(exc), finished=now())
		raise


def workspace_content_labels(content):
	"""Yield header and paragraph texts the standard workspace extractor translates."""
	try:
		blocks = json.loads(content or "[]")
	except Exception:
		return
	if not isinstance(blocks, list):
		return
	for item in blocks:
		if not isinstance(item, dict):
			continue
		if item.get("type") in ("header", "paragraph"):
			text = (item.get("data") or {}).get("text")
			if text:
				yield text
