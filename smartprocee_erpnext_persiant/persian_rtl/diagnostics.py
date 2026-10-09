"""Read-only diagnostics for the RTL layer.

Nothing here changes state and nothing here runs on a normal request. It is
called from the "بررسی سازگاری" button on ``Persian RTL Settings`` and reports
what the runtime would do, plus every reason it would refuse to do it.
"""

from __future__ import annotations

import frappe

from smartprocee_erpnext_persiant.persian_rtl import detection, registry, settings
from smartprocee_erpnext_persiant.persian_translation import schema

ALLOWED_ROLES = ("System Manager",)


@frappe.whitelist()
def report() -> dict:
	"""Full compatibility report for every registered adapter."""
	_require_read()
	rows = detection.detect_all()
	return {
		"enabled": settings.is_enabled(),
		"diagnostic_mode": settings.diagnostic_mode(),
		"language": frappe.local.lang if hasattr(frappe.local, "lang") else "",
		"rows": rows,
		"warnings": build_warnings(rows),
	}


@frappe.whitelist()
def compat_report() -> dict:
	"""The "مدیریت سازگاری راست‌به‌چپ" table: one row per installed app."""
	_require_read()
	apps = detection.app_report()
	return {
		"enabled": settings.is_enabled(),
		"language": frappe.local.lang if hasattr(frappe.local, "lang") else "",
		"apps": apps,
		"warnings": build_warnings([row for row in detection.detect_all() if row["installed"]]),
	}


def _require_read():
	"""Permission first, then schema.

	Checking permission first keeps a non-admin from learning anything about the
	site; the schema check then explains an empty screen instead of reporting a
	permission error for a Single that does not exist yet.
	"""
	if not frappe.has_permission("Persian RTL Settings", "read"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	schema.require_ready(schema.RTL_DOCTYPES)


@frappe.whitelist()
def route_probe(path: str) -> dict:
	"""Which adapter would handle this path, and with which decision."""
	_require_read()
	path = (path or "").strip()
	adapter = None if registry.is_path_ignored(path) else _first(registry.matching_adapters(path))
	decision = {"path": path, "ignored": registry.is_path_ignored(path), "adapter_id": None, "reason": ""}
	if adapter is None:
		decision["reason"] = "no adapter claims this path"
		return decision
	eligible, reason = _eligibility(adapter)
	decision.update({"adapter_id": adapter.adapter_id, "eligible": eligible, "reason": reason})
	return decision


def _first(items):
	return items[0] if items else None


def _eligibility(adapter):
	from smartprocee_erpnext_persiant.persian_rtl import inject

	return inject.is_eligible(adapter)


def build_warnings(rows) -> list[dict]:
	"""Problems an administrator should act on, most severe first."""
	warnings = []
	for row in rows:
		if row["state"] == registry.NEEDS_REVIEW:
			warnings.append({"level": "error", "adapter_id": row["adapter_id"], "message": row["reason"]})
		elif row["state"] == registry.VERSION_MISMATCH:
			warnings.append(
				{
					"level": "warning",
					"adapter_id": row["adapter_id"],
					"message": (
						f"{row['target_app']} {row['version']} is outside the tested range "
						f"{row['compatible_range']}. Enable 'پذیرش نسخهٔ تست‌نشده' only after a visual check."
					),
				}
			)
		elif row["state"] == registry.UNSUPPORTED:
			warnings.append(
				{
					"level": "warning",
					"adapter_id": row["adapter_id"],
					"message": f"no supported injection mechanism for {row['target_app']}",
				}
			)
	for row in rows:
		missing = row["signature"].get("physical_missing") or []
		if row["signature"].get("rule") == registry.SIGNATURE_PARTIAL and missing:
			warnings.append(
				{
					"level": "warning",
					"adapter_id": row["adapter_id"],
					"message": (
						"the target no longer ships some utilities this adapter mirrors, so those rules "
						"are now unused: " + ", ".join(missing)
					),
				}
			)
		if row["signature"].get("logical_found"):
			warnings.append(
				{
					"level": "info",
					"adapter_id": row["adapter_id"],
					"message": (
						"the target already uses logical utilities ("
						+ ", ".join(row["signature"]["logical_found"])
						+ "); when the physical utilities disappear this adapter can be retired"
					),
				}
			)
	return warnings


def summary_text() -> str:
	"""One-line-per-adapter text used by the settings form button."""
	rows = detection.detect_all()
	lines = []
	for row in rows:
		lines.append(
			"{state} | {app} {version} | {detail}".format(
				state=row["state"],
				app=row["target_app"],
				version=row["version"] or "-",
				detail=row["reason"] or "ready",
			)
		)
	return "\n".join(lines)
