"""Site-local font files and the Desk stylesheet link."""

from __future__ import annotations

import uuid
from pathlib import Path

import frappe
from frappe.installer import update_site_config

ACTIVE_CSS = "persian-font-active.css"
MARKER = "persian-font-active.css"
UPLOAD_PREFIX = "persian-font-"


def write_upload(font_format: str, data: bytes) -> str:
	extension = "woff2" if font_format == "WOFF2" else "woff"
	filename = f"{UPLOAD_PREFIX}{uuid.uuid4().hex}.{extension}"
	_public_file(filename).write_bytes(data)
	return f"/files/{filename}"


def write_active_css(css: str) -> str:
	_public_file(ACTIVE_CSS).write_text(css, encoding="utf-8")
	version = uuid.uuid4().hex[:12]
	_set_stylesheet(f"/files/{ACTIVE_CSS}?v={version}")
	return version


def clear_active_css():
	path = _public_file(ACTIVE_CSS)
	if path.exists():
		path.unlink()
	_set_stylesheet(None)


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
	current = [item for item in list(frappe.conf.get("app_include_css") or []) if MARKER not in str(item)]
	if url:
		current.append(url)
		update_site_config("app_include_css", current)
		return
	if current:
		update_site_config("app_include_css", current)
		return
	update_site_config("app_include_css", "None")


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
	if filename == ACTIVE_CSS or "/" in filename:
		return ""
	return filename
