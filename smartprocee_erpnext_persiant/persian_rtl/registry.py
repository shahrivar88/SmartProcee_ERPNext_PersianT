"""Adapter discovery, version compatibility and route matching.

The registry is the single source of truth for *technical* adapter metadata. It
reads adapter packages from :mod:`smartprocee_erpnext_persiant.persian_rtl.adapters`
on demand, so a bench that does not ship CRM, Insights or Raven keeps working
without them: an adapter whose target app is absent is reported as
``not_installed`` and never touches a response.
"""

from __future__ import annotations

import importlib
import pkgutil

import frappe
from frappe.utils import get_app_version
from semantic_version import Version

from smartprocee_erpnext_persiant.persian_rtl.adapters import base

# Version compatibility outcomes.
SUPPORTED = "supported"
MISMATCH = "mismatch"
NOT_INSTALLED = "not_installed"
UNKNOWN = "unknown"

# Detection states, in the wording the administrator sees.
RTL_NATIVE = "RTL Native"
ADAPTER_ENABLED = "Adapter Enabled"
ADAPTER_AVAILABLE = "Adapter Available"
PLANNED = "Planned"
NEEDS_REVIEW = "Needs Review"
UNSUPPORTED = "Unsupported"
VERSION_MISMATCH = "Version Mismatch"
DISABLED = "Disabled"
NOT_INSTALLED = "Not Installed"
# An installed app that ships no adapter at all. It is neither broken nor
# supported: nobody has reviewed how that app behaves in Persian yet.
NO_ADAPTER = "No Adapter"

STATE_ORDER = (
	RTL_NATIVE,
	ADAPTER_ENABLED,
	ADAPTER_AVAILABLE,
	PLANNED,
	NEEDS_REVIEW,
	VERSION_MISMATCH,
	DISABLED,
	UNSUPPORTED,
	NO_ADAPTER,
	NOT_INSTALLED,
)

# Signature outcomes.
SIGNATURE_UNAVAILABLE = "Unavailable"
SIGNATURE_COMPLIANT = "Compliant"
SIGNATURE_PARTIAL = "Partial"
SIGNATURE_OBSOLETE = "Obsolete Candidate"


def all_adapters() -> dict[str, base.Adapter]:
	"""Every adapter this app ships, keyed by ``adapter_id``."""
	cached = getattr(frappe.local, "_persian_rtl_adapters", None)
	if cached is not None:
		return cached
	found: dict[str, base.Adapter] = {}
	for module in _adapter_packages():
		adapter = getattr(module, "ADAPTER", None)
		if not isinstance(adapter, base.Adapter):
			continue
		if adapter.adapter_id in found:
			raise ValueError(f"duplicate adapter id: {adapter.adapter_id}")
		found[adapter.adapter_id] = adapter
	frappe.local._persian_rtl_adapters = found
	return found


def adapter_for(adapter_id: str) -> base.Adapter | None:
	return all_adapters().get(adapter_id)


def _adapter_packages():
	"""Import ``persian_rtl.adapters.<name>.adapter`` for every shipped subpackage."""
	package = "smartprocee_erpnext_persiant.persian_rtl.adapters"
	for info in sorted(pkgutil.iter_modules(importlib.import_module(package).__path__), key=lambda i: i.name):
		if not info.ispkg or info.name.startswith("_"):
			continue
		try:
			yield importlib.import_module(f"{package}.{info.name}.adapter")
		except ModuleNotFoundError as exc:
			# A missing dependency inside an optional adapter must not break the app.
			frappe.logger().warning(f"Persian RTL: skipping adapter {info.name}: {exc}")


def installed_version(app: str) -> str:
	"""Version of an installed app, or an empty string when it is not installed."""
	if app not in frappe.get_installed_apps(_ensure_on_bench=True):
		return ""
	try:
		return str(get_app_version(app) or "")
	except Exception:
		return ""


def is_installed(app: str) -> bool:
	return app in frappe.get_installed_apps(_ensure_on_bench=True)


def parse_version(value: str) -> Version:
	"""Coerce a version string such as ``1.85`` or ``1.85.1`` to a comparable value.

	Frappe 16 advertises ``semantic_version`` and uses it for its own change log,
	so it is the one parser guaranteed to be present on every bench.
	"""
	return Version.coerce(str(value).strip())


def version_state(adapter: base.Adapter) -> str:
	"""Where the installed version sits against what the adapter was tested on.

	The range is narrow on purpose but never pinned to one build: ``1.85.1`` and
	``1.85.2`` both stay inside ``1.85.0 - 1.85.99``, so a patch release does not
	disable a working adapter. Anything outside the range is reported as a
	mismatch instead of being assumed compatible.
	"""
	version = installed_version(adapter.target_app)
	if not version:
		return NOT_INSTALLED
	try:
		current = parse_version(version)
		lower = parse_version(adapter.compatible_min)
		upper = parse_version(adapter.compatible_max)
	except ValueError:
		return UNKNOWN
	return SUPPORTED if lower <= current <= upper else MISMATCH


def route_matches(pattern: str, path: str) -> bool:
	"""Match a route pattern against a request path.

	``/crm/*`` covers ``/crm``, ``/crm/`` and ``/crm/leads``. A pattern without
	the wildcard matches that exact route only. Query strings are ignored.
	"""
	if not pattern or not path:
		return False
	path = path.split("?", 1)[0].split("#", 1)[0]
	if not path.startswith("/"):
		path = "/" + path
	path = path.rstrip("/") or "/"
	if pattern.endswith("/*"):
		prefix = pattern[:-2].rstrip("/") or "/"
		return path == prefix or path.startswith(prefix + "/")
	pattern = pattern.rstrip("/") or "/"
	return path == pattern


def is_path_ignored(path: str) -> bool:
	"""Paths that must never be touched, whatever an adapter declares."""
	path = (path or "").split("?", 1)[0]
	for prefix in ("/api/", "/assets/", "/files/", "/private/", "/socket.io", "/_/", "/node_modules/"):
		if path.startswith(prefix):
			return True
	return path in ("/api", "/socket.io")


def matching_adapters(path: str) -> list[base.Adapter]:
	"""Adapters whose route patterns cover this path, regardless of being enabled."""
	path = path or ""
	return sorted(
		(adapter for adapter in all_adapters().values() if any(route_matches(p, path) for p in adapter.routes)),
		key=lambda adapter: adapter.adapter_id,
	)


def quick_state(adapter: base.Adapter, enabled: bool) -> str:
	"""The state an administrator sees, without reading any stylesheet.

	Cheap on purpose: the settings form calls it on every save, while the full
	report in :mod:`persian_rtl.detection` also inspects the target's built CSS.

	An accepted untested version is reported as a mismatch either way. The saved
	override lets the adapter run against a build nobody verified; it does not
	make that build verified, so the state must not claim otherwise.
	"""
	if not is_installed(adapter.target_app):
		return NOT_INSTALLED
	if version_state(adapter) == MISMATCH:
		return VERSION_MISMATCH
	if not adapter.visual_ready:
		return PLANNED
	return ADAPTER_ENABLED if enabled else ADAPTER_AVAILABLE
