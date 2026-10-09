"""Advisory detection for RTL adapters.

Everything here is read-only and report-only. It answers, for one adapter:

* is the target app installed, and at which version
* does its entry template still look the way the adapter was written for
* which document direction does that template currently declare
* does its built stylesheet still contain the physical utilities the adapter
  mirrors, or has the front end moved on

A failing check never silently assumes the adapter is healthy. It lowers the
reported state to ``Needs Review`` and states the reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import frappe

from smartprocee_erpnext_persiant.persian_rtl import registry
from smartprocee_erpnext_persiant.persian_rtl.adapters import base

ROOT_TAG = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
DIR_ATTRIBUTE = re.compile(r"\bdir\s*=\s*[\"']([^\"']*)[\"']", re.IGNORECASE)
CLASS_NAME = re.compile(r"\.((?:\\.|[-\w/\[\].])+)")
SKIPPED_PARTS = {"node_modules", "__pycache__", "dist", ".git"}


def detect(adapter: base.Adapter, states: dict | None = None) -> dict:
	"""A single adapter's full compatibility report."""
	from smartprocee_erpnext_persiant.persian_rtl import settings

	states = states if states is not None else settings.adapter_states()
	state = states.get(adapter.adapter_id, {})
	installed = registry.is_installed(adapter.target_app)
	version = registry.installed_version(adapter.target_app)
	version_state = registry.version_state(adapter)

	template = read_entry_template(adapter)
	style = read_style_signature(adapter) if installed else {"rule": registry.SIGNATURE_UNAVAILABLE}

	enabled = bool(state.get("enabled"))
	override = bool(state.get("override_version_check"))
	eligible, reason = _eligibility(adapter, enabled, override, version_state, style)

	return {
		"adapter_id": adapter.adapter_id,
		"title": adapter.title,
		"target_app": adapter.target_app,
		"routes": adapter.routes,
		"installed": installed,
		"version": version,
		"version_state": version_state,
		"tested_versions": adapter.tested_versions,
		"compatible_range": f"{adapter.compatible_min} - {adapter.compatible_max}",
		"entry_template": adapter.entry_template,
		"entry_template_present": template["present"],
		"entry_anchor_present": template["anchor_present"],
		"root_direction": template["direction"],
		"stylesheet_present": style.get("present"),
		"signature": style,
		"enabled": enabled,
		"override_version_check": override,
		"visual_ready": adapter.visual_ready,
		"risk": adapter.risk,
		"notes": adapter.notes,
		"eligible": eligible,
		"reason": reason,
		"state": _state(adapter, installed, version_state, enabled, eligible, reason, style, template),
	}


def read_entry_template(adapter: base.Adapter) -> dict:
	"""Root direction and mount anchor declared by the target's HTML entry point."""
	blank = {"present": False, "direction": "unknown", "anchor_present": False}
	if not registry.is_installed(adapter.target_app):
		return blank
	path = Path(frappe.get_app_path(adapter.target_app)) / Path(adapter.entry_template.split("/", 1)[-1])
	if not path.exists():
		return blank
	try:
		text = path.read_text(encoding="utf-8", errors="replace")
	except OSError:
		return blank
	root = ROOT_TAG.search(text)
	direction = "ltr"
	if root:
		found = DIR_ATTRIBUTE.search(root.group(0))
		direction = (found.group(1).strip().lower() if found else "ltr") or "ltr"
	return {
		"present": True,
		"direction": direction,
		"anchor_present": bool(adapter.entry_anchor) and adapter.entry_anchor in text,
	}


def read_style_signature(adapter: base.Adapter) -> dict:
	"""Compare the physical utilities the adapter mirrors with the shipped ones."""
	if not adapter.signature_physical:
		return {"rule": registry.SIGNATURE_UNAVAILABLE, "present": None}
	names = app_class_names(adapter.target_app)
	if not names:
		return {"rule": registry.SIGNATURE_UNAVAILABLE, "present": None}
	present = [item for item in adapter.signature_physical if item in names]
	missing = [item for item in adapter.signature_physical if item not in names]
	logical = sorted(item for item in adapter.signature_logical if item in names)
	stylesheet = adapter.asset_url
	stylesheet_present = None
	if stylesheet:
		stylesheet_present = stylesheet_path(stylesheet).exists()

	# Partial drift is reported but must not disable a working adapter: a target
	# that drops one mirrored utility still needs the other eighty-six. Only a
	# target that has stopped using physical utilities completely makes the
	# adapter pointless, and that is the one case worth raising the state for.
	if not present:
		rule = registry.SIGNATURE_OBSOLETE
	elif missing:
		rule = registry.SIGNATURE_PARTIAL
	else:
		rule = registry.SIGNATURE_COMPLIANT
	return {
		"rule": rule,
		"present": stylesheet_present,
		"physical_expected": len(adapter.signature_physical),
		"physical_present": len(present),
		"physical_missing": missing[:20],
		"logical_found": logical[:20],
		"class_count": len(names),
	}


def stylesheet_path(asset_url: str) -> Path:
	"""Absolute path of an ``/assets/<app>/...`` URL on this bench.

	The app name comes from the URL, so the lookup works on any bench layout
	instead of assuming a bench directory.
	"""
	relative = (asset_url or "").split("/assets/", 1)[-1]
	app, _, rest = relative.partition("/")
	if not app or not rest:
		return Path("/nonexistent-persian-rtl-asset")
	return Path(frappe.get_app_path(app)) / "public" / rest


def app_class_names(app: str) -> set[str]:
	"""Class names appearing in an app's own built stylesheets, unescaped.

	Read from the installed copy of the app, so nothing depends on a build path
	from a developer machine.
	"""
	cached = getattr(frappe.local, "_persian_rtl_class_names", None)
	if cached is None:
		cached = frappe.local._persian_rtl_class_names = {}
	if app in cached:
		return cached[app]
	found: set[str] = set()
	public = Path(frappe.get_app_path(app)) / "public"
	if public.is_dir():
		for path in public.rglob("*.css"):
			if SKIPPED_PARTS & set(path.parts):
				continue
			try:
				text = path.read_text(encoding="utf-8", errors="replace")
			except OSError:
				continue
			for match in CLASS_NAME.finditer(text):
				name = match.group(1).replace("\\", "")
				# Variant prefixes are kept out: only the plain utility matters here.
				found.add(name.rsplit(":", 1)[-1])
	cached[app] = found
	return found


def _eligibility(adapter, enabled, override, version_state, style) -> tuple[bool, str]:
	if not enabled:
		return False, "disabled"
	if version_state == registry.NOT_INSTALLED:
		return False, f"{adapter.target_app} is not installed"
	if version_state == registry.MISMATCH and not override:
		return False, f"version {registry.installed_version(adapter.target_app)} is outside {adapter.compatible_min} - {adapter.compatible_max}"
	if not adapter.visual_ready:
		return False, "no visual adapter has been written yet"
	if style.get("rule") == registry.SIGNATURE_OBSOLETE:
		return False, "the target no longer uses the physical utilities this adapter mirrors; the adapter is likely obsolete"
	if style.get("present") is False:
		return False, "the adapter stylesheet is missing from the bench"
	return True, "ok"


def _state(adapter, installed, version_state, enabled, eligible, reason, style, template) -> str:
	if not installed:
		return registry.NOT_INSTALLED
	if version_state == registry.MISMATCH:
		# An accepted untested version still reports a mismatch. ``eligible``
		# already says the adapter will run because the administrator accepted
		# the range; the state must not turn that into "verified".
		return registry.VERSION_MISMATCH
	if eligible:
		return registry.ADAPTER_ENABLED
	if enabled:
		return registry.PLANNED if not adapter.visual_ready else registry.NEEDS_REVIEW
	if version_state == registry.MISMATCH:
		return registry.VERSION_MISMATCH
	if style.get("rule") == registry.SIGNATURE_OBSOLETE:
		return registry.NEEDS_REVIEW
	if not adapter.visual_ready:
		return registry.PLANNED
	if template["direction"] == "rtl":
		return registry.RTL_NATIVE
	return registry.ADAPTER_AVAILABLE


def detect_all() -> list[dict]:
	from smartprocee_erpnext_persiant.persian_rtl import settings

	states = settings.adapter_states()
	rows = [detect(adapter, states) for adapter in registry.all_adapters().values()]
	order = {name: index for index, name in enumerate(registry.STATE_ORDER)}
	return sorted(rows, key=lambda row: (order.get(row["state"], 99), row["adapter_id"]))


# The two apps that *are* the Desk and the Website host. They render through
# Frappe's own templates, which already carry RTL support for `fa`, so they are
# reported as native instead of as an app nobody has reviewed.
DESK_HOSTS = ("frappe", "erpnext")

INTERFACE_DESK = "میزکار/وب (بومی)"
INTERFACE_SPA = "اپ مستقل (SPA)"
INTERFACE_UNKNOWN = "بررسی‌نشده"

STATE_LABELS = {
	registry.RTL_NATIVE: "راست‌به‌چپ بومی",
	registry.ADAPTER_ENABLED: "آداپتور فعال",
	registry.ADAPTER_AVAILABLE: "آداپتور در دسترس",
	registry.PLANNED: "نیازمند بررسی",
	registry.NEEDS_REVIEW: "نیازمند بررسی",
	registry.VERSION_MISMATCH: "ناسازگاری نسخه",
	registry.DISABLED: "غیرفعال",
	registry.UNSUPPORTED: "پشتیبانی‌نشده",
	registry.NO_ADAPTER: "آداپتور تعریف نشده",
	registry.NOT_INSTALLED: "نصب‌نیست",
}

# The Persian sentence behind each state, shown in the settings table. Kept next
# to the short label so the two can never disagree.
REASON_LABELS = {
	registry.RTL_NATIVE: "این برنامه میزکار/وب خود فریمورک است و راست‌به‌چپ فارسی را بومی پشتیبانی می‌کند.",
	registry.ADAPTER_ENABLED: "آداپتور روی نسخه نصب‌شده فعال است.",
	registry.ADAPTER_AVAILABLE: "آداپتور آماده است؛ برای اعمال، آن را فعال کنید.",
	registry.PLANNED: "برای این برنامه آداپتور بصری نوشته نشده و نیازمند بررسی است.",
	registry.NEEDS_REVIEW: "ساختار رابط این برنامه تغییر کرده و نیازمند بررسی است.",
	registry.VERSION_MISMATCH: "نسخه نصب‌شده خارج از بازه آزمون‌شده آداپتور است.",
	registry.DISABLED: "آداپتور این برنامه غیرفعال است.",
	registry.UNSUPPORTED: "این برنامه پشتیبانی نمی‌شود.",
	registry.NO_ADAPTER: "برای این برنامه آداپتوری تعریف نشده است.",
	registry.NOT_INSTALLED: "این برنامه روی این ماشین نصب نیست.",
}



def interface_kind(app: str, adapter: base.Adapter | None) -> str:
	"""Which kind of front end this app serves, as far as anyone knows."""
	if adapter is not None:
		return INTERFACE_SPA if adapter.hosting == base.STANDALONE else INTERFACE_DESK
	return INTERFACE_DESK if app in DESK_HOSTS else INTERFACE_UNKNOWN


def app_report() -> list[dict]:
	"""Every installed app, with the RTL state an administrator needs to see.

	The list is discovered at runtime, so a newly installed app appears on its own
	as "آداپتور تعریف نشده" without a code change. An app that ships an adapter
	is reported from the same detection the runtime uses, so the table and the
	actual behaviour cannot drift apart.
	"""
	by_app = {row["target_app"]: row for row in detect_all()}
	adapters = {adapter.target_app: adapter for adapter in registry.all_adapters().values()}
	rows = []
	for app in sorted(frappe.get_installed_apps(_ensure_on_bench=True)):
		detail = by_app.get(app)
		if detail is None:
			if app in DESK_HOSTS:
				state = registry.RTL_NATIVE
			else:
				state = registry.NO_ADAPTER
			rows.append(
				{
					"app": app,
					"version": registry.installed_version(app),
					"interface": interface_kind(app, None),
					"state": state,
					"state_label": STATE_LABELS[state],
					"reason_label": REASON_LABELS[state],
					"adapter_id": "",
					"enabled": False,
					"reason": "framework host" if state == registry.RTL_NATIVE else "no adapter is registered",
					"notes": "",
				}
			)
			continue
		rows.append(
			{
				"app": app,
				"version": detail["version"],
				"interface": interface_kind(app, adapters[app]),
				"state": detail["state"],
				"state_label": STATE_LABELS.get(detail["state"], detail["state"]),
				"reason_label": reason_label(detail),
				"adapter_id": detail["adapter_id"],
				"enabled": detail["enabled"],
				"reason": detail["reason"],
				"notes": detail["notes"],
			}
		)
	return rows


def reason_label(detail: dict) -> str:
	"""The Persian sentence an administrator reads for one app's state.

	`reason` stays the machine string the runtime logs; the settings table shows
	this instead, so no internal wording leaks into the UI.
	"""
	state = detail["state"]
	if state == registry.VERSION_MISMATCH:
		return (
			f"نسخه نصب‌شده ({detail['version']}) خارج از بازه آزمون‌شده "
			f"({detail['compatible_range']}) است."
		)
	if state == registry.ADAPTER_ENABLED and detail.get("override_version_check"):
		return "آداپتور فعال است، اما روی نسخه‌ای خارج از بازه آزمون‌شده اجرا می‌شود."
	return REASON_LABELS.get(state, STATE_LABELS.get(state, state))
