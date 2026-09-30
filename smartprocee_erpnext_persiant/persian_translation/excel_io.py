import hashlib
import re
from io import BytesIO

from openpyxl import Workbook, load_workbook

from smartprocee_erpnext_persiant.persian_translation.validate import translation_error

CORE_APPS = ("frappe", "erpnext")
OTHER_SHEET = "سایر"
SHEET_TITLE_LIMIT = 31
_INVALID_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]")
_DOCTYPE_NAME = re.compile(r"DocType:\s*([^|(]+)")

HEADERS = (
	"App",
	"Module",
	"Path",
	"Kind",
	"Source Text",
	"Context",
	"Current Persian Translation",
	"New Persian Translation",
	"Identity",
)


def _known_module_names() -> dict[str, str]:
	try:
		import frappe
	except Exception:
		return {}
	if not getattr(getattr(frappe, "local", None), "site", None):
		return {}
	known = {}
	for scrubbed in frappe.local.module_app or {}:
		display = frappe.unscrub(scrubbed)
		known[scrubbed.casefold()] = display
		known[display.casefold()] = display
	return known


def _doctype_module_map(rows) -> dict[str, str]:
	names = set()
	for row in rows:
		for match in _DOCTYPE_NAME.finditer(row.get("source_path") or ""):
			name = match.group(1).strip()
			if name:
				names.add(name)
	if not names:
		return {}
	try:
		import frappe
	except Exception:
		return {}
	if not getattr(getattr(frappe, "local", None), "site", None):
		return {}
	found = {}
	pending = list(names)
	for start in range(0, len(pending), 500):
		chunk = pending[start : start + 500]
		for item in frappe.get_all(
			"DocType",
			filters={"name": ["in", chunk]},
			fields=["name", "module"],
			limit_page_length=0,
		):
			if item.module:
				found[item.name] = item.module
	return found


def _match_module(name: str, known: dict[str, str]) -> str:
	cleaned = (name or "").strip()
	if not cleaned:
		return ""
	return known.get(cleaned.casefold()) or known.get(cleaned.casefold().replace(" ", "_")) or ""


def _infer_module(source_path: str, known: dict[str, str], doctype_modules: dict[str, str]) -> str:
	first = (source_path or "").split("|", 1)[0]
	first = first.split("(", 1)[0].strip()
	doctype = _DOCTYPE_NAME.match(first)
	if doctype:
		return doctype_modules.get(doctype.group(1).strip()) or ""
	for prefix in (
		"Workspace Sidebar Item:",
		"Workspace Sidebar title:",
		"Workspace Sidebar:",
		"Workspace title:",
		"Workspace content:",
		"Workspace Link description:",
		"Workspace Link:",
		"Workspace Shortcut:",
		"Workspace Chart:",
		"Workspace Number Card:",
		"Workspace Quick List:",
		"Workspace:",
	):
		if first.startswith(prefix):
			label = first[len(prefix) :].strip()
			return _match_module(label, known) or label
	for part in first.replace("\\", "/").split("/"):
		matched = _match_module(part, known)
		if matched:
			return matched
	return ""


def _module_for(row, known, doctype_modules) -> str:
	module = (row.get("module") or "").strip()
	return module or _infer_module(row.get("source_path") or "", known, doctype_modules)


def _sheet_order(app: str) -> tuple:
	return (app == OTHER_SHEET, CORE_APPS.index(app) if app in CORE_APPS else len(CORE_APPS), app.casefold())


def _unique_sheet_title(label: str, used: set[str]) -> str:
	"""Excel limits: 31 characters, no :\\/?*[] and no leading/trailing apostrophe.

	A name that must be shortened or already exists gets a suffix derived from the
	full label, so the same app always receives the same title.
	"""
	cleaned = _INVALID_SHEET_CHARS.sub(" ", label or "")
	cleaned = re.sub(r"\s+", " ", cleaned).strip().strip("'").strip() or OTHER_SHEET
	candidate = cleaned
	if len(cleaned) > SHEET_TITLE_LIMIT or candidate.casefold() in used:
		suffix = "~" + hashlib.sha1(label.encode()).hexdigest()[:6]
		candidate = cleaned[: SHEET_TITLE_LIMIT - len(suffix)] + suffix
	number = 2
	while candidate.casefold() in used:
		suffix = f" {number}"
		candidate = f"{cleaned[: SHEET_TITLE_LIMIT - len(suffix)]}{suffix}"
		number += 1
	used.add(candidate.casefold())
	return candidate


def build_workbook(rows) -> bytes:
	"""One worksheet per app; the App column, not the sheet title, identifies the app."""
	known = _known_module_names()
	doctype_modules = _doctype_module_map(rows)
	groups = {}
	for row in rows:
		app = (row.get("app") or "").strip() or OTHER_SHEET
		groups.setdefault(app, []).append((row, _module_for(row, known, doctype_modules)))
	order = sorted(groups, key=_sheet_order)
	book = Workbook()
	used_titles = set()
	if not order:
		sheet = book.active
		sheet.title = OTHER_SHEET
		sheet.append(list(HEADERS))
		sheet.freeze_panes = "A2"
	for index, app in enumerate(order):
		sheet = book.active if index == 0 else book.create_sheet()
		sheet.title = _unique_sheet_title(app, used_titles)
		sheet.append(list(HEADERS))
		for row, module_column in groups[app]:
			sheet.append(
				[
					row.get("app") or "",
					module_column,
					row.get("source_path") or "",
					row.get("kind") or "",
					row.get("source_text") or "",
					row.get("context") or "",
					row.get("current_translation") or "",
					row.get("current_translation") or "",
					row.get("identity") or "",
				]
			)
		sheet.freeze_panes = "A2"
	payload = BytesIO()
	book.save(payload)
	return payload.getvalue()


def read_workbook(path) -> list[dict]:
	book = load_workbook(path, read_only=True, data_only=True)
	try:
		rows = []
		found_header = False

		def text(cell):
			if cell is None:
				return ""
			return cell if isinstance(cell, str) else str(cell)

		for sheet in book.worksheets:
			header_map = None
			for offset, raw in enumerate(sheet.iter_rows(values_only=True)):
				values = [text(cell) for cell in raw]
				if header_map is None:
					headers = [value.strip() for value in values]
					if "Source Text" in headers and offset < 5:
						header_map = {name: headers.index(name) for name in HEADERS if name in headers}
						found_header = True
					continue
				if not any(value.strip() for value in values):
					continue

				def cell(name, mapped=header_map, raw_values=values):
					position = mapped.get(name)
					if position is None or position >= len(raw_values):
						return ""
					return raw_values[position]

				rows.append(
					{
						"app": cell("App"),
						"module": cell("Module"),
						"source_path": cell("Path"),
						"kind": cell("Kind"),
						"source_text": cell("Source Text"),
						"context": cell("Context"),
						"current_translation": cell("Current Persian Translation"),
						"new_translation": cell("New Persian Translation"),
						"identity": cell("Identity"),
						"sheet": sheet.title,
						"excel_row": offset + 1,
					}
				)
		if not found_header:
			raise ValueError("ستون Source Text در فایل اکسل پیدا نشد.")
		return rows
	finally:
		book.close()


def classify_import_rows(file_rows, effective_for, identity_for) -> dict:
	"""Classify an exported workbook. Blank and unchanged Persian cells are ignored."""
	seen = {}
	unchanged = 0
	new_rows = []
	changed_rows = []
	errors = []
	for index, row in enumerate(file_rows, start=2):
		source = (row.get("source_text") or "").strip()
		context = row.get("context") or ""
		new_value = row.get("new_translation") or ""
		location = row.get("excel_row") or index
		if row.get("sheet"):
			location = f"{row.get('sheet')} / {location}"
		if not source:
			errors.append({"row": location, "message": "متن اصلی خالی است."})
			continue
		expected = identity_for(source, context)
		given = (row.get("identity") or "").strip()
		if given and given != expected:
			errors.append({"row": location, "message": "شناسه ردیف با متن اصلی و زمینه هم‌خوان نیست."})
			continue
		key = (source, context)
		if key in seen and seen[key] != new_value.strip():
			errors.append({"row": location, "message": "همین متن و زمینه با ترجمه متفاوت دیگری در فایل آمده است."})
			continue
		seen[key] = new_value.strip()
		if not new_value.strip():
			unchanged += 1
			continue
		current = effective_for(source, context) or ""
		if new_value.strip() == current.strip():
			unchanged += 1
			continue
		problem = translation_error(source, new_value, context)
		if problem:
			errors.append({"row": location, "source_text": source, "message": problem})
			continue
		payload = {"source_text": source, "context": context, "translated_text": new_value.strip()}
		if current.strip() and current.strip() != source.strip():
			changed_rows.append(payload)
		else:
			new_rows.append(payload)
	return {
		"file_rows": len(file_rows),
		"unchanged": unchanged,
		"new": len(new_rows),
		"changed": len(changed_rows),
		"errors": errors,
		"actions": new_rows + changed_rows,
	}
