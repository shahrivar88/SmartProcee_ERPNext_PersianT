"""Restore points for the state this app owns, and nothing else.

A snapshot holds exactly three things, each one owned by فارسی‌ساز:

* every Persian (`language = fa`) ``Translation`` row,
* the font activation plus the ``Persian Font Family`` rows it activates,
* the ``Persian RTL Settings`` Single (enable flag, adapter switches, exclusions).

Business documents, other languages, other apps, Core tables and other apps'
files are never read into a snapshot and never touched by a restore.

Two snapshots are immutable, so a reinstall or a later migration can never
rewrite the record of how the site looked before this app changed anything:
``install_baseline`` (captured on the very first install) and ``adopted_state``
(captured once on an already-installed site, and *labelled as such* -- it is the
state when this app started managing the site, not a pre-install baseline).
"""

from __future__ import annotations

import base64
import json
import zlib

import frappe
from frappe.utils import now

from smartprocee_erpnext_persiant.persian_translation import ownership
from smartprocee_erpnext_persiant.persian_translation.system_font.css import (
	managed_family,
	render_adapter_css,
	render_family_css,
)
from smartprocee_erpnext_persiant.persian_translation.system_font.storage import ACTIVE_CSS, MARKER, write_active_css

SNAPSHOT = "Persian Snapshot"
FAMILY = "Persian Font Family"
FACE = "Persian Font Face"
SCHEMA = 1
# How many fresh/overwritten pairs a report carries. The counts are always exact;
# only the readable sample is bounded.
MAX_REPORTED_ROWS = 20

INSTALL_BASELINE = "install_baseline"
ADOPTED_STATE = "adopted_state"
PRE_APPLY = "pre_apply"
PRE_FONT = "pre_font"
PRE_RTL = "pre_rtl"
PRE_RESTORE = "pre_restore"
MANUAL = "manual"

IMMUTABLE_KINDS = (INSTALL_BASELINE, ADOPTED_STATE)
PRUNABLE_KINDS = (PRE_APPLY, PRE_FONT, PRE_RTL, PRE_RESTORE)
PRE_KIND_KEEP = 20

BASELINE_LABEL = "وضعیت پایه هنگام نصب — پیش از نخستین تغییر فارسی‌ساز"
ADOPTED_LABEL = "وضعیت هنگام شروع مدیریت این سایت (نقطهٔ بازیابی نیست، پایهٔ تاریخی نیست)"
ADOPTED_NOTE = (
	"این سایت پیش از این نسخه از فارسی‌ساز نصب شده بود، پس وضعیت پیش از نصب اولیه در دسترس نیست."
	" این نسخه، وضعیت لحظه‌ای شروع مدیریت را ثبت می‌کند و «پایهٔ تاریخی» نامیده نمی‌شود."
)

FACE_FIELDS = (
	"original_filename",
	"file_url",
	"fallback_url",
	"font_format",
	"css_weight",
	"font_style",
	"font_stretch",
	"enabled",
)
FAMILY_FIELDS = ("family_name", "css_family", "source", "is_active")


def capture(kind: str, label: str, note: str = "", immutable: bool = False) -> dict:
	"""Store one snapshot. Never overwrites: every capture is a new record."""
	payload = current_state()
	doc = frappe.new_doc(SNAPSHOT)
	doc.kind = kind
	doc.label = label
	doc.note = note
	doc.immutable = 1 if immutable else 0
	doc.captured_at = now()
	doc.captured_by = frappe.session.user if frappe.session.user != "Guest" else "Administrator"
	doc.schema_version = SCHEMA
	doc.translations_count = len(payload["translations"])
	doc.fonts_count = len(payload["fonts"]["families"])
	doc.rtl_enabled = payload["rtl"]["enabled"]
	doc.summary = _summary(payload)
	doc.payload = _encode(payload)
	doc.insert()
	if kind in PRUNABLE_KINDS:
		prune(kind)
	return {
		"name": doc.name,
		"kind": doc.kind,
		"label": doc.label,
		"immutable": bool(doc.immutable),
		"translations": doc.translations_count,
		"fonts": doc.fonts_count,
	}


def capture_install_baseline() -> dict | None:
	"""The one true pre-mutation baseline. Only a pristine site may hold one.

	`install_baseline` means "this is the state before Persianizer ever touched
	this site". That claim is only honest when nothing has been captured yet. If
	any snapshot exists the app has already been active here, the pre-install
	state is no longer knowable, and writing a baseline now would be a fake
	historical baseline -- the exact thing `ensure_adopted_state` exists to avoid.
	"""
	if has_any():
		return None
	return capture(INSTALL_BASELINE, BASELINE_LABEL, immutable=True)


def ensure_adopted_state() -> dict | None:
	"""Honest fallback for a site where this app was already active.

	Refuses during an install (the baseline path owns that case) and when any
	snapshot already exists, so it can never be mistaken for, or overwrite, a
	real baseline.
	"""
	if getattr(frappe.flags, "in_install", None):
		return None
	if not frappe.db.exists("DocType", SNAPSHOT):
		return None
	if frappe.db.exists(SNAPSHOT, {}) or has_any():
		return None
	return capture(ADOPTED_STATE, ADOPTED_LABEL, note=ADOPTED_NOTE, immutable=True)


def has_any() -> bool:
	return bool(frappe.db.exists(SNAPSHOT, {}))


def prune(kind: str, keep: int = PRE_KIND_KEEP) -> int:
	"""Keep the newest `keep` snapshots of one prunable kind. Immutable ones are never touched."""
	if kind not in PRUNABLE_KINDS:
		return 0
	rows = frappe.get_all(
		SNAPSHOT,
		filters={"kind": kind, "immutable": 0},
		pluck="name",
		order_by="creation desc",
		limit_page_length=0,
	)
	removed = 0
	for name in rows[keep:]:
		if active_operations_using(name):
			continue
		frappe.delete_doc(SNAPSHOT, name, force=1, ignore_permissions=False)
		removed += 1
	return removed


def active_operations_using(name: str) -> list[str]:
	"""Queued or running operations that still read this snapshot."""
	from smartprocee_erpnext_persiant.persian_translation import operations

	if not name or not frappe.db.table_exists(operations.OPERATION):
		return []
	return frappe.get_all(
		operations.OPERATION,
		filters={"snapshot": name, "status": ["in", operations.ACTIVE_STATUSES]},
		pluck="name",
	)


def list_snapshots(limit: int = 100) -> list[dict]:
	rows = frappe.get_all(
		SNAPSHOT,
		fields=[
			"name",
			"kind",
			"label",
			"note",
			"immutable",
			"captured_at",
			"captured_by",
			"translations_count",
			"fonts_count",
			"rtl_enabled",
			"summary",
		],
		order_by="creation desc",
		limit_page_length=int(limit),
	)
	return rows


def load_payload(name: str) -> dict:
	blob = frappe.db.get_value(SNAPSHOT, name, "payload")
	if blob is None:
		frappe.throw("نسخهٔ پشتیبان پیدا نشد.")
	return _decode(blob)


def current_state() -> dict:
	return {
		"schema": SCHEMA,
		"translations": _translations(),
		"fonts": _fonts(),
		"rtl": _rtl(),
	}


def live_translations() -> list:
	"""Every Persian `Translation` row, read the way a snapshot stores it.

	This Frappe's query builder returns one dict-like row per record, so the
	fields are read by name. Indexing a row positionally would read a dict key
	and fail; every reader of these rows goes through this one function.
	"""
	return frappe.get_all(
		"Translation",
		filters={"language": "fa"},
		fields=["source_text", "context", "translated_text"],
		order_by="source_text asc",
		limit_page_length=0,
	)


def _translations() -> list[list[str]]:
	return [
		[row.source_text or "", row.context or "", row.translated_text or ""]
		for row in live_translations()
	]


def _fonts() -> dict:
	if not frappe.db.table_exists(FAMILY):
		return {"active_css": None, "families": []}
	families = []
	for row in frappe.get_all(FAMILY, fields=["name", *FAMILY_FIELDS], order_by="creation asc", limit_page_length=0):
		doc = frappe.get_doc(FAMILY, row.name)
		families.append(
			{
				"key": _family_key(doc.family_name),
				**{field: row.get(field) or "" for field in FAMILY_FIELDS},
				"is_active": 1 if row.get("is_active") else 0,
				"faces": [[face.get(field) or "" for field in FACE_FIELDS] for face in doc.faces],
			}
		)
	return {"active_css": _active_css(), "families": families}


def _active_css() -> str | None:
	for item in frappe.conf.get("app_include_css") or []:
		if MARKER in str(item):
			return str(item)
	return None


def _rtl() -> dict:
	from smartprocee_erpnext_persiant.persian_rtl import settings

	doc = settings.settings_doc()
	if not doc:
		return {"available": 0, "enabled": 0, "diagnostic_mode": 0, "adapters": [], "exclusions": []}
	return {
		"available": 1,
		"enabled": 1 if doc.enabled else 0,
		"diagnostic_mode": 1 if doc.diagnostic_mode else 0,
		"adapters": [
			[
				row.adapter_id or "",
				1 if row.enabled else 0,
				1 if row.override_version_check else 0,
				row.admin_notes or "",
				1 if row.use_system_font else 0,
			]
			for row in doc.adapters
		],
		"exclusions": [
			[row.label or "", row.selector or "", row.mode or ""] for row in doc.extra_exclusions
		],
	}


def _summary(payload: dict) -> str:
	fonts = payload["fonts"]["families"]
	return (
		f"{len(payload['translations'])} ترجمه فارسی، "
		f"{len(fonts)} خانواده فونت، RTL {'روشن' if payload['rtl']['enabled'] else 'خاموش'}."
	)


def _family_key(family_name: str) -> str:
	"""The business key of a font family. Its document name is a random hash."""
	return (family_name or "").strip().casefold()


def _encode(payload: dict) -> str:
	raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
	return base64.b64encode(zlib.compress(raw, 6)).decode("ascii")


def _decode(blob: str) -> dict:
	return json.loads(zlib.decompress(base64.b64decode(blob)).decode("utf-8"))


def missing_font_files(payload: dict) -> list[str]:
	"""Recorded font files that no longer exist on disk, so a restore cannot honour them."""
	from pathlib import Path

	files_dir = Path(frappe.get_site_path("public", "files"))
	missing = []
	for family in payload["fonts"]["families"]:
		for face in family["faces"]:
			url = face[FACE_FIELDS.index("file_url")]
			if not url or not str(url).startswith("/files/"):
				continue
			if not (files_dir / str(url)[len("/files/"):]).exists():
				missing.append(url)
	return sorted(set(missing))


def build_plan(name: str, mode: str = "full", remove_fonts: int = 0) -> tuple[list[dict], dict]:
	"""What a restore of this snapshot would change, as a list of actions.

	Read-only. `mode="values"` restores values but leaves rows that were created
	after the snapshot in place; `mode="full"` also removes them. Font families
	are only removed when `remove_fonts` is set explicitly.

	`full` removes a row only while it still holds the value this app last wrote
	for that string. Ownership outlives a deleted row, so a claim alone is not
	enough: a row that appeared after the snapshot without this app's value -- a
	hand edit, a fixture, another app, or a value typed in again after this app's
	row was deleted -- is preserved and reported as `preserved_unowned` instead of
	being deleted. A row this app did write and that somebody changed afterwards
	is restored and reported as `overwritten`, so the change is visible instead of
	silently lost.
	"""
	payload = load_payload(name)
	full = (mode or "full") == "full"
	actions: list[dict] = []
	deleted = 0
	preserved: list[dict] = []
	overwritten: list[dict] = []

	snapshot_values = {(row[0], row[1]): row[2] for row in payload["translations"]}
	current_rows = {
		(row.source_text or "", row.context or ""): (row.translated_text or "")
		for row in live_translations()
	}
	owned = ownership.owned_map()
	for (source, context), value in sorted(snapshot_values.items()):
		current = current_rows.get((source, context))
		if current == value:
			continue
		record = owned.get(ownership.key_of(source, context))
		if record and (record.last_value or "").strip() and (record.last_value or "") != (current or ""):
			overwritten.append(
				{
					"source_text": source,
					"context": context,
					"snapshot_value": value,
					"current_value": current or "",
					"last_written_value": record.last_value or "",
				}
			)
		actions.append({"type": "translation_upsert", "source_text": source, "context": context, "value": value})
	if full:
		for (source, context), current in current_rows.items():
			if (source, context) in snapshot_values:
				continue
			record = owned.get(ownership.key_of(source, context))
			if record and (record.last_value or "") == current:
				actions.append({"type": "translation_delete", "source_text": source, "context": context})
				deleted += 1
			else:
				preserved.append(
					{
						"source_text": source,
						"context": context,
						"value": current,
					}
				)

	font_actions, font_report = _font_plan(payload, full, bool(remove_fonts))
	actions.extend(font_actions)
	actions.extend(_rtl_plan(payload))

	report = {
		"snapshot": name,
		"mode": "full" if full else "values",
		"remove_fonts": bool(remove_fonts),
		"translations_restored": sum(1 for a in actions if a["type"] == "translation_upsert"),
		"translations_removed": sum(1 for a in actions if a["type"] == "translation_delete"),
		"deleted_total": deleted,
		"preserved_unowned": len(preserved),
		"preserved_unowned_sample": preserved[:MAX_REPORTED_ROWS],
		"overwritten": len(overwritten),
		"overwritten_sample": overwritten[:MAX_REPORTED_ROWS],
		**font_report,
	}
	return actions, report


def _font_plan(payload: dict, full: bool, remove_fonts: bool) -> tuple[list[dict], dict]:
	if not frappe.db.table_exists(FAMILY):
		return [], {
			"fonts_restored": 0,
			"fonts_removed": 0,
			"fonts_missing_files": [],
			"fonts_added_since_snapshot": 0,
		}
	recorded = {family["key"]: family for family in payload["fonts"]["families"]}
	current = {
		_family_key(row.family_name): row.name
		for row in frappe.get_all(FAMILY, fields=["name", "family_name"], limit_page_length=0)
	}
	missing = missing_font_files(payload)
	actions = []
	restored = 0
	for key, family in recorded.items():
		if key in current:
			continue
		if not _has_site_files(family):
			continue
		if any(url in missing for url in _family_file_urls(family)):
			continue
		actions.append({"type": "font_family_create", "family": family})
		restored += 1
	added_since = [key for key in current if key not in recorded]
	removed = 0
	if remove_fonts:
		# Only families this app created can be removed, and never while active.
		protection = _active_family_names()
		for key in added_since:
			if current[key] in protection:
				continue
			actions.append({"type": "font_family_delete", "name": current[key], "key": key})
			removed += 1
	active_css = payload["fonts"]["active_css"]
	current_active = _active_css()
	if (active_css or None) != (current_active or None):
		actions.append({"type": "font_activate", "url": active_css, "snapshot": payload})
	return actions, {
		"fonts_restored": restored,
		"fonts_removed": removed,
		"fonts_missing_files": missing,
		"fonts_added_since_snapshot": len(added_since),
	}


def _family_file_urls(family: dict) -> list[str]:
	index = FACE_FIELDS.index("file_url")
	return [str(face[index]) for face in family["faces"] if face[index]]


def _has_site_files(family: dict) -> bool:
	"""Whether every face is a file uploaded to this site.

	Releases before 1.2.0 recorded a family whose faces were app assets. Those
	files are no longer shipped, so such a family can be neither recreated nor
	activated.
	"""
	return all(url.startswith("/files/") for url in _family_file_urls(family))


def _active_family_names() -> set[str]:
	"""Document names of the active font families. `pluck` returns plain strings."""
	return set(frappe.get_all(FAMILY, filters={"is_active": 1}, pluck="name"))


def _rtl_plan(payload: dict) -> list[dict]:
	if not payload["rtl"].get("available"):
		return []
	return [{"type": "rtl_restore", "state": payload["rtl"]}]


def apply_font_activate(url: str, payload: dict) -> None:
	"""Re-render the recorded stylesheet from the faces the snapshot recorded.

	The file is always regenerated, never copied back from disk. The active
	stylesheet lives at one fixed path, so a copy of it is the *current* font, not
	the recorded one: restoring an older activation would otherwise rewrite the
	newer font over itself and leave the site on the wrong family.
	"""
	from smartprocee_erpnext_persiant.persian_translation.system_font.storage import clear_active_css

	if not url:
		clear_active_css()
		return
	family = _recorded_family_for(url, payload)
	if not family:
		return
	if not _has_site_files(family):
		clear_active_css()
		return
	faces = _faces_for_css(family)
	write_active_css(
		render_family_css(family["family_name"], faces),
		render_adapter_css(family["family_name"], faces),
	)


def fonts_referenced_by_snapshots() -> set[str]:
	"""Every font file any stored snapshot still needs.

	A family row may be deleted; its files may not be, as long as a snapshot the
	operator can still restore points at them. Deleting them would turn that
	snapshot into one whose restore refuses to run.
	"""
	urls: set[str] = set()
	for name in frappe.get_all(SNAPSHOT, pluck="name", limit_page_length=0):
		try:
			payload = load_payload(name)
		except Exception:  # noqa: BLE001 - a broken snapshot must not block a delete
			continue
		urls.update(_payload_font_urls(payload))
	return urls


def font_urls_of_payload(blob) -> set[str]:
	"""The font files one stored payload records. An unreadable payload records none."""
	try:
		return _payload_font_urls(_decode(blob))
	except Exception:  # noqa: BLE001 - a broken snapshot must not block a delete
		return set()


def _payload_font_urls(payload: dict) -> set[str]:
	index = FACE_FIELDS.index("file_url")
	urls = set()
	for family in (payload.get("fonts") or {}).get("families") or []:
		for face in family.get("faces") or []:
			if face and face[index]:
				urls.add(str(face[index]))
	return urls


def fonts_in_use() -> set[str]:
	"""Every font file a font face or a stored snapshot still refers to."""
	urls = fonts_referenced_by_snapshots()
	if not frappe.db.table_exists(FACE):
		return urls
	for row in frappe.get_all(FACE, fields=["file_url", "fallback_url"], limit_page_length=0):
		urls.update(str(url) for url in (row.file_url, row.fallback_url) if url)
	return urls


def release_font_files(urls) -> None:
	"""Delete the given font files once the transaction commits, if nothing uses them then.

	The references are read again after the commit, so a delete that is rolled
	back -- or a file another face or snapshot still records -- keeps its file.
	"""
	pending = getattr(frappe.local, "_persian_released_fonts", None)
	if pending is None:
		pending = frappe.local._persian_released_fonts = set()
	pending.update(str(url) for url in urls or [] if url)
	if pending:
		frappe.db.after_commit.add(_delete_released_fonts)


def _delete_released_fonts() -> None:
	from smartprocee_erpnext_persiant.persian_translation.system_font.storage import delete_upload

	pending = getattr(frappe.local, "_persian_released_fonts", None) or set()
	frappe.local._persian_released_fonts = set()
	if not pending:
		return
	needed = fonts_in_use()
	for url in sorted(pending - needed):
		delete_upload(url)


def delete_font_uploads(urls) -> list[str]:
	"""Delete uploaded font files, keeping every file a face or a stored snapshot still needs.

	Called only after the family row is gone, so a refused delete never removes a
	file. Returns the files that were kept, so a caller can report them.
	"""
	from smartprocee_erpnext_persiant.persian_translation.system_font.storage import delete_upload

	needed = fonts_in_use()
	kept = []
	for url in urls or []:
		if not url:
			continue
		if str(url) in needed:
			kept.append(str(url))
			continue
		delete_upload(url)
	return kept


def _recorded_family_for(url: str, payload: dict) -> dict | None:
	for family in payload["fonts"]["families"]:
		if family.get("is_active"):
			return family
	return payload["fonts"]["families"][0] if payload["fonts"]["families"] else None


def _faces_for_css(family: dict) -> list[dict]:
	faces = []
	for face in family["faces"]:
		item = dict(zip(FACE_FIELDS, face, strict=False))
		if not item.get("enabled"):
			continue
		faces.append(
			{
				"file_url": item["file_url"],
				"fallback_url": item["fallback_url"],
				"font_format": item["font_format"],
				"css_weight": item["css_weight"],
				"font_style": item["font_style"],
				"font_stretch": item["font_stretch"],
			}
		)
	return faces


def apply_font_family_create(family: dict) -> str:
	doc = frappe.new_doc(FAMILY)
	doc.family_name = family["family_name"]
	doc.css_family = family.get("css_family") or managed_family(family["family_name"])
	doc.source = family.get("source") or "Uploaded"
	doc.is_active = 0
	for face in family["faces"]:
		doc.append("faces", dict(zip(FACE_FIELDS, face, strict=False)))
	doc.insert()
	return doc.name


def apply_rtl_restore(state: dict) -> dict:
	"""Put the Single back the way the snapshot recorded it."""
	from smartprocee_erpnext_persiant.persian_rtl import settings

	if not settings._doctype_ready():
		return {"skipped": True}
	doc = frappe.get_doc(settings.SETTINGS_DOCTYPE)
	doc.enabled = int(state.get("enabled") or 0)
	doc.diagnostic_mode = int(state.get("diagnostic_mode") or 0)
	recorded = {row[0]: row for row in state.get("adapters") or [] if row and row[0]}
	kept = []
	for row in doc.adapters:
		record = recorded.get(row.adapter_id)
		if record is None:
			continue
		row.enabled = int(record[1] or 0)
		row.override_version_check = int(record[2] or 0)
		row.admin_notes = record[3] or ""
		# Snapshots taken before the font option existed recorded four columns.
		row.use_system_font = int(record[4] or 0) if len(record) > 4 else 0
		kept.append(row)
	doc.set("adapters", kept)
	doc.set(
		"extra_exclusions",
		[
			{"label": row[0] or "", "selector": row[1] or "", "mode": row[2] or "LTR Island"}
			for row in state.get("exclusions") or []
			if row and row[1]
		],
	)
	doc.save()
	frappe.clear_document_cache(settings.SETTINGS_DOCTYPE, settings.SETTINGS_DOCTYPE)
	return {"enabled": doc.enabled, "adapters": len(kept)}
