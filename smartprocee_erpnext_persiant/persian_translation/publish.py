"""Publish local fa overrides into the public catalogue.

Only (source, context) identities owned by Frappe or ERPNext reach fa.csv.
Every other override stays a local Translation record on this site.
"""

from pathlib import Path

import frappe

from smartprocee_erpnext_persiant.persian_translation.catalogue import (
	catalogue_map,
	merge_overrides,
	read_catalogue,
	write_catalogue_atomic,
)
from smartprocee_erpnext_persiant.persian_translation.provenance import OwnershipIndex
from smartprocee_erpnext_persiant.persian_translation.validate import translation_error

WITHHELD_SAMPLE = 20


def publish_overrides(path: Path, overrides: dict, index: OwnershipIndex | None = None) -> dict:
	index = index or OwnershipIndex.for_catalogue_owners()
	original_rows = read_catalogue(path)
	changes, withheld, problems = _select(overrides, catalogue_map(original_rows), index)
	if problems:
		frappe.throw("انتشار متوقف شد. فایل اصلی تغییر نکرد. " + " | ".join(problems[:20]))
	result = {
		"updated": 0,
		"appended": 0,
		"unchanged": 0,
		"backup": "",
		"withheld": len(withheld),
		"withheld_sample": withheld[:WITHHELD_SAMPLE],
		"withheld_message": _withheld_message(len(withheld)),
	}
	if not changes:
		return result
	merged, stats = merge_overrides(original_rows, changes)
	if len(merged) < len(original_rows):
		frappe.throw("انتشار متوقف شد چون تعداد ردیف‌های کاتالوگ کمتر می‌شد.")
	backup = write_catalogue_atomic(path, merged)
	result.update(stats, backup=backup.name, rows=len(merged))
	return result


def _select(overrides, published, index):
	changes, withheld, problems = {}, [], []
	for key, translated in overrides.items():
		source, context = key
		if not (translated or "").strip() or translated == published.get(key, ""):
			continue
		if not index.owner_of(source, context):
			withheld.append({"source_text": source[:120], "context": context})
			continue
		problem = translation_error(source, translated, context)
		if problem:
			problems.append(f"{source[:80]}: {problem}")
			continue
		changes[key] = translated
	return changes, withheld, problems


def _withheld_message(count: int) -> str:
	if not count:
		return ""
	return (
		f"{count} ترجمه در fa.csv منتشر نشد، چون مالکیت متن اصلی آن‌ها به Frappe یا ERPNext ثابت نشد"
		" (برنامه‌های سفارشی یا شخص ثالث). این ترجمه‌ها فقط در همین سایت به‌صورت Translation باقی می‌مانند."
	)
