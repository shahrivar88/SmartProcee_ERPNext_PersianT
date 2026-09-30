"""Register the bundled Yekan Bakh faces from their real metadata."""

from pathlib import Path

import frappe

from smartprocee_erpnext_persiant.persian_translation.system_font.css import managed_family
from smartprocee_erpnext_persiant.persian_translation.system_font.inspect import inspect_font_bytes

APP_NAME = "smartprocee_erpnext_persiant"
BUNDLED_FAMILY = "Yekan Bakh"
ASSET_PREFIX = f"/assets/{APP_NAME}/fonts/"


def register_bundled_family():
	if not frappe.db.table_exists("Persian Font Family"):
		return
	faces = _bundled_faces()
	if not faces:
		return
	existing = frappe.get_all(
		"Persian Font Family",
		filters={"family_name": BUNDLED_FAMILY, "source": "Bundled"},
		limit=1,
	)
	if existing:
		doc = frappe.get_doc("Persian Font Family", existing[0].name)
	else:
		doc = frappe.new_doc("Persian Font Family")
		doc.family_name = BUNDLED_FAMILY
		doc.source = "Bundled"
		doc.is_active = 0
	doc.css_family = managed_family(BUNDLED_FAMILY)
	doc.source = "Bundled"
	doc.set("faces", [])
	for face in faces:
		doc.append("faces", face)
	doc.save(ignore_permissions=True)


def _bundled_faces() -> list[dict]:
	folder = Path(frappe.get_app_path(APP_NAME, "public", "fonts"))
	if not folder.exists():
		return []
	faces = []
	for path in sorted(folder.glob("*.woff2")):
		inspected = inspect_font_bytes(path.name, path.read_bytes())
		fallback = path.with_suffix(".woff")
		row = _row(inspected, f"{ASSET_PREFIX}{path.name}")
		if fallback.exists():
			row["fallback_url"] = f"{ASSET_PREFIX}{fallback.name}"
		faces.append(row)
	return faces


def _row(inspected: dict, file_url: str) -> dict:
	return {
		"original_filename": inspected["original_filename"],
		"file_url": file_url,
		"font_format": inspected["font_format"],
		"family_name": inspected["family_name"],
		"subfamily": inspected["subfamily"],
		"full_name": inspected["full_name"],
		"postscript_name": inspected["postscript_name"],
		"weight_class": inspected["weight_class"],
		"css_weight": inspected["css_weight"],
		"font_style": inspected["font_style"],
		"detected_style": inspected["detected_style"],
		"font_stretch": inspected["font_stretch"],
		"width_class": inspected["width_class"],
		"warning": "\n".join(inspected.get("warnings") or []),
		"enabled": 1,
	}
