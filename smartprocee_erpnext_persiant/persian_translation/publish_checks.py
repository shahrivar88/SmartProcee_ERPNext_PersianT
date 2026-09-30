"""Checks that local translations of non-owner apps work but never reach fa.csv.

Nothing here names a specific installed app, so the checks run on any site.
"""

import shutil
import tempfile
from pathlib import Path

import frappe
from frappe.translate import clear_cache, get_all_translations

from smartprocee_erpnext_persiant.persian_translation.catalogue import catalogue_map, read_catalogue
from smartprocee_erpnext_persiant.persian_translation.provenance import CATALOGUE_OWNERS, OwnershipIndex
from smartprocee_erpnext_persiant.persian_translation.publish import publish_overrides
from smartprocee_erpnext_persiant.persian_translation.release_check import audit_catalogue
from smartprocee_erpnext_persiant.persian_translation.service import catalogue_path, save_translations

CORE_KEY = ("Customer", "")


def third_party_app(exclude=("smartprocee_erpnext_persiant",)) -> str | None:
	for app in frappe.get_installed_apps():
		if app not in CATALOGUE_OWNERS and app not in exclude:
			return app
	return None


def check_publish_gate(app: str, marker: str, check):
	index = OwnershipIndex.for_catalogue_owners()
	check(bool(index.owner_of(*CORE_KEY)), "a core field label is proven to be owned by a catalogue owner")
	overrides = {CORE_KEY: f"{marker} مشتری", (f"{marker} ONLY LOCAL", ""): "فقط محلی"}
	local = _local_only_source(app, index)
	if local:
		save_translations([{"source_text": local, "context": "", "translated_text": f"{marker} محلی"}])
		frappe.db.commit()
		clear_cache()
		check(
			get_all_translations("fa").get(local) == f"{marker} محلی",
			"a local override for an app outside the catalogue owners works through Frappe",
		)
		overrides[(local, "")] = f"{marker} محلی"
	with tempfile.TemporaryDirectory() as tmp:
		target = Path(tmp) / "fa.csv"
		shutil.copyfile(catalogue_path(), target)
		result = publish_overrides(target, overrides, index)
		published = catalogue_map(read_catalogue(target))
		check(result["updated"] == 1 and result["appended"] == 0, "publish writes only the core-owned override")
		check(result["withheld"] == len(overrides) - 1, "publish withholds every override outside the catalogue owners")
		check(
			all(key not in published for key in overrides if key != CORE_KEY),
			"withheld overrides are absent from the published copy",
		)
		check(not audit_catalogue(target, index).failures, "the published copy still passes the release check")


def _local_only_source(app, index):
	for source in frappe.get_all(
		"Persian Translation Source",
		filters={"app": app, "context": ""},
		pluck="source_text",
		limit_page_length=500,
	):
		if any(token in source for token in ("{", "}", "%", "<", ">")):
			continue
		if frappe.db.exists("Translation", {"language": "fa", "source_text": source}):
			continue
		if not index.owner_of(source, ""):
			return source
	return None
