"""Administrator decisions layered on top of the registry.

The database never describes *how* an adapter works. It only stores the choices
a System Manager is allowed to make -- switch the adapter on, accept a version
range that was not tested, and use the active Persian font where the adapter
supports it -- plus optional extra exclusions for a target that needs them.
"""

from __future__ import annotations

import frappe

from smartprocee_erpnext_persiant.persian_rtl import registry

SETTINGS_DOCTYPE = "Persian RTL Settings"
ADAPTER_DOCTYPE = "Persian RTL Adapter"
EXCLUSION_DOCTYPE = "Persian RTL Exclusion"


def _doctype_ready() -> bool:
	"""Whether ``bench migrate`` has created this Single on the site.

	``frappe.db.table_exists`` cannot answer this: a Single has no table of its
	own, its values live in ``tabSingles``. So the DocType record itself is the
	right thing to look for.
	"""
	return bool(frappe.db.exists("DocType", SETTINGS_DOCTYPE))


def settings_doc():
	"""The Single, or ``None`` before ``bench migrate`` has created it."""
	if not _doctype_ready():
		return None
	return frappe.get_cached_doc(SETTINGS_DOCTYPE)


def is_enabled() -> bool:
	doc = settings_doc()
	return bool(doc and doc.enabled)


def diagnostic_mode() -> bool:
	doc = settings_doc()
	return bool(doc and doc.diagnostic_mode)


def adapter_states() -> dict[str, dict]:
	"""``{adapter_id: {enabled, override_version_check, use_system_font, notes}}`` from the Single."""
	doc = settings_doc()
	states: dict[str, dict] = {}
	for row in (doc.get("adapters") if doc else None) or []:
		if not row.adapter_id:
			continue
		states[row.adapter_id] = {
			"enabled": bool(row.enabled),
			"override_version_check": bool(row.override_version_check),
			"use_system_font": bool(row.use_system_font),
			"notes": row.admin_notes or "",
		}
	return states


def is_adapter_enabled(adapter_id: str) -> bool:
	return bool(adapter_states().get(adapter_id, {}).get("enabled"))


def accepts_untested_version(adapter_id: str) -> bool:
	return bool(adapter_states().get(adapter_id, {}).get("override_version_check"))


def extra_exclusions() -> tuple[dict, ...]:
	"""Administrator-added exclusions, validated before use."""
	doc = settings_doc()
	found = []
	for row in (doc.get("extra_exclusions") if doc else None) or []:
		if not (row.selector or "").strip():
			continue
		mode = row.mode if row.mode in ("LTR Island", "Auto Direction") else "LTR Island"
		found.append({"label": row.label or row.selector, "selector": row.selector.strip(), "mode": mode})
	return tuple(found)


def exclusions_for(adapter_id: str) -> tuple[dict, ...]:
	"""Adapter-declared exclusions plus the ones an administrator added."""
	adapter = registry.adapter_for(adapter_id)
	declared = [
		{"label": item.label, "selector": item.selector, "mode": item.mode, "source": "adapter"}
		for item in (adapter.exclusions if adapter else ())
	]
	added = [{**item, "source": "admin"} for item in extra_exclusions()]
	return tuple(declared + added)


def sync_from_registry() -> dict:
	"""Mirror the code registry into the Single without touching admin choices.

	Called from ``after_migrate``. While the set of adapters is unchanged only the
	registry-owned columns are written, row by row, so ``enabled``, the version
	override, ``use_system_font`` on a supporting adapter and the notes are never
	part of the write. A new adapter gets a row and a row that no longer has a
	matching adapter in code is removed, so uninstalling an adapter cannot leave a
	stale switch behind.
	"""
	if not _doctype_ready():
		return {"skipped": True}
	doc = frappe.get_doc(SETTINGS_DOCTYPE)
	adapters = registry.all_adapters()
	existing = {row.adapter_id: row for row in doc.adapters if row.adapter_id}
	if set(existing) == set(adapters) and len(existing) == len(doc.adapters):
		for adapter_id, row in existing.items():
			values = _registry_values(adapters[adapter_id], row)
			frappe.db.set_value(ADAPTER_DOCTYPE, row.name, values, update_modified=False)
	else:
		kept = []
		for adapter_id, adapter in sorted(adapters.items()):
			row = existing.get(adapter_id) or doc.append("adapters", {"adapter_id": adapter_id})
			row.update(_registry_values(adapter, row))
			kept.append(row)
		doc.set("adapters", kept)
		doc.save()
	frappe.clear_document_cache(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE)
	return {"adapters": len(adapters)}


def _registry_values(adapter, row) -> dict:
	"""The columns of a row that code owns. Everything else is the administrator's."""
	values = {
		"title": adapter.title,
		"target_app": adapter.target_app,
		"detected_version": registry.installed_version(adapter.target_app),
		"tested_versions": ", ".join(adapter.tested_versions),
		"compatible_range": f"{adapter.compatible_min} - {adapter.compatible_max}",
		"hosting": adapter.hosting,
		"risk": adapter.risk,
		"adapters_notes": adapter.notes,
		"supports_system_font": int(adapter.supports_system_font),
		"state": registry.quick_state(adapter, bool(row.enabled)),
	}
	if not adapter.supports_system_font:
		values["use_system_font"] = 0
	return values


def adapter_rows() -> list[dict]:
	"""Registry metadata joined with the stored switches. Used by the UI and diagnostics."""
	states = adapter_states()
	rows = []
	for adapter_id, adapter in sorted(registry.all_adapters().items()):
		state = states.get(adapter_id, {})
		rows.append({"adapter": adapter, "state": state})
	return rows
