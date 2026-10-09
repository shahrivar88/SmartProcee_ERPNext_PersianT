"""Site-local font files and the Desk stylesheet link."""

from __future__ import annotations

import uuid
from pathlib import Path

import frappe
from frappe.installer import update_site_config

ACTIVE_CSS = "persian-font-active.css"
# The standalone-app twin of ACTIVE_CSS. It carries the same faces but hangs off
# `html[dir="rtl"]` instead of `html[lang="fa"]`, because a standalone SPA keeps
# its own `<html lang="en">` and never receives `app_include_css`. Only an RTL
# adapter links it, and an adapter only runs for a Persian session.
ADAPTER_CSS = "persian-font-adapter.css"
MARKER = "persian-font-active.css"
UPLOAD_PREFIX = "persian-font-"


def write_upload(font_format: str, data: bytes) -> str:
	extension = "woff2" if font_format == "WOFF2" else "woff"
	filename = f"{UPLOAD_PREFIX}{uuid.uuid4().hex}.{extension}"
	_public_file(filename).write_bytes(data)
	return f"/files/{filename}"


def write_active_css(css: str, adapter_css: str | None = None) -> str:
	"""Store the active font stylesheet(s) and register the Desk one.

	The Desk file is linked through `app_include_css`. The adapter file, when
	given, is picked up by the RTL adapters at request time through
	:func:`adapter_font_url`.
	"""
	_public_file(ACTIVE_CSS).write_text(css, encoding="utf-8")
	if adapter_css:
		_public_file(ADAPTER_CSS).write_text(adapter_css, encoding="utf-8")
	else:
		_drop_adapter_css()
	version = uuid.uuid4().hex[:12]
	_set_stylesheet(f"/files/{ACTIVE_CSS}?v={version}")
	frappe.local._persian_adapter_font_url = None
	return version


def read_active_css() -> tuple[str | None, str | None]:
	"""The Desk and adapter stylesheets as stored, ``None`` for a missing file."""
	return tuple(
		path.read_text(encoding="utf-8") if path.exists() else None
		for path in (_public_file(ACTIVE_CSS), _public_file(ADAPTER_CSS))
	)


def adapter_font_url() -> str:
	"""URL of the active Persian font stylesheet for standalone apps.

	The activated custom family when there is one, so a standalone app follows the
	font the Desk shows. With no custom family the result is empty and the app
	keeps its own font, exactly like the Desk keeps Frappe's. The `?v` value is
	the file's modification time in nanoseconds, so selecting another font --
	even twice within one second -- makes the browser fetch it again instead of
	serving a cached build.
	"""
	cached = getattr(frappe.local, "_persian_adapter_font_url", None)
	if cached is not None:
		return cached
	path = _public_file(ADAPTER_CSS)
	url = f"/files/{ADAPTER_CSS}?v={path.stat().st_mtime_ns}" if path.exists() else ""
	frappe.local._persian_adapter_font_url = url
	return url


def clear_active_css():
	path = _public_file(ACTIVE_CSS)
	if path.exists():
		path.unlink()
	_drop_adapter_css()
	_set_stylesheet(None)


def _drop_adapter_css():
	path = _public_file(ADAPTER_CSS)
	if path.exists():
		path.unlink()
	frappe.local._persian_adapter_font_url = None


def delete_upload(url: str):
	filename = _upload_filename(url)
	if not filename:
		return
	path = _public_file(filename)
	if path.exists():
		path.unlink()


def remove_managed_files():
	folder = Path(frappe.get_site_path("public", "files"))
	if folder.exists():
		for path in folder.glob("persian-font-*"):
			if path.is_file():
				path.unlink()
	clear_active_css()


def _set_stylesheet(url: str | None):
	# An empty list is written instead of a sentinel such as "None": www/desk.py
	# does `hooks.get("app_include_css", []) + frappe.conf.get("app_include_css", [])`,
	# so a non-list site config value would raise a TypeError.
	current = [item for item in list(frappe.conf.get("app_include_css") or []) if MARKER not in str(item)]
	if url:
		current.append(url)
	update_site_config("app_include_css", current)


def _public_file(filename: str) -> Path:
	if "/" in filename or "\\" in filename or filename.startswith("."):
		raise ValueError("unsafe font filename")
	return Path(frappe.get_site_path("public", "files", filename))


def _upload_filename(url: str) -> str:
	value = str(url or "")
	prefix = "/files/"
	if not value.startswith(prefix + UPLOAD_PREFIX):
		return ""
	filename = value[len(prefix):]
	if filename in (ACTIVE_CSS, ADAPTER_CSS) or "/" in filename:
		return ""
	return filename
