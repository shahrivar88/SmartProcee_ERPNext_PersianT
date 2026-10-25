"""Request-time entry point for RTL injection.

Frappe calls ``after_request`` with ``response`` and ``request`` keyword
arguments, after routing and after the response body exists, and before caching
headers are finalised. That is the only supported place where a response built by
another application can still be adjusted without patching that application.

The guard order matters: everything cheap and database-free is checked first, so
the overwhelming majority of requests pay nothing but a few attribute reads.
"""

from __future__ import annotations

import frappe

from smartprocee_erpnext_persiant.persian_rtl import inject, registry, settings

PERSIAN = "fa"
HTML_TYPES = ("text/html", "application/xhtml+xml")
SAFE_METHODS = ("GET", "HEAD")


def current_language() -> str:
	"""Language that decides whether a standalone SPA may be mirrored.

	Desk usually sets ``frappe.local.lang``. CRM's website renderer may leave
	that as the system default while the signed-in user is Persian. CRM's own
	``get_translations`` already reads ``User.language``, so RTL and font
	injection follow the same source when the request language is not Persian.
	"""
	lang = _lang_code(getattr(frappe.local, "lang", "") or "")
	if lang == PERSIAN:
		return lang
	user = getattr(getattr(frappe, "session", None), "user", None)
	if not user or user == "Guest":
		return lang
	return _lang_code(frappe.get_cached_value("User", user, "language") or "") or lang


def _lang_code(value: str) -> str:
	return (value or "").split("-", 1)[0].split("_", 1)[0]


def current_path() -> str:
	request = getattr(frappe.local, "request", None)
	return getattr(request, "path", "") or ""


def is_html(response) -> bool:
	content_type = (response.headers.get("Content-Type") or response.mimetype or "").lower()
	return any(kind in content_type for kind in HTML_TYPES)


def after_request(response=None, request=None):
	"""Apply the matching RTL adapter to this response, if one claims it."""
	if response is None or request is None:
		return
	if getattr(response, "status_code", 200) != 200:
		return
	if (getattr(request, "method", "GET") or "GET").upper() not in SAFE_METHODS:
		return
	if response.direct_passthrough:
		return
	if not is_html(response):
		return

	path = getattr(request, "path", "") or current_path()
	if registry.is_path_ignored(path):
		return

	adapter = inject.choose_adapter(path)
	if adapter is None:
		return

	if current_language() != PERSIAN:
		return

	if not settings.is_enabled():
		return

	states = settings.adapter_states()
	eligible, reason = inject.is_eligible(adapter, states)
	if not eligible:
		_note_skip(adapter, reason)
		return

	body = response.get_data(as_text=True)
	updated = inject.inject(body, adapter, states)
	if updated != body:
		response.set_data(updated)
		response.headers.setdefault("Vary", "Accept-Language")


def _note_skip(adapter, reason: str):
	"""Record why an adapter that claims this route did not run.

	Only active in diagnostic mode, and never on a route that no adapter claims,
	so a normal request stays free of extra log traffic.
	"""
	if not settings.diagnostic_mode():
		return
	frappe.logger().info("Persian RTL: %s skipped (%s)", adapter.adapter_id, reason)
