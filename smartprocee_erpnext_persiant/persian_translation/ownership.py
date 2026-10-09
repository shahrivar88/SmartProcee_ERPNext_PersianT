"""Which strings this app has written, and what it last wrote there.

A restore may only remove Persian rows that this app itself created. Without a
record of what it wrote, `full` mode would delete *every* Persian row the
snapshot does not contain -- including a translation a human added by hand after
the snapshot was taken. This registry is that record.

Two rules keep it honest:

* Every write goes through `service._upsert_translation`, so `record()` is the
  single place ownership is claimed and no path can write a row without it.
* A record is never deleted by a translation delete: the string is still managed
  by this app, it just currently has no value. Deleting the record would make a
  later full restore treat the string as someone else's and refuse to remove it.
  Because the record outlives the row, a restore only removes a row that still
  holds `last_value`; a value somebody typed in later is never this app's.

The registry is a normal DocType, so permissions, audit fields and uninstall
behaviour stay the framework's job.
"""

from __future__ import annotations

import frappe
from frappe.utils import now

from smartprocee_erpnext_persiant.persian_translation.identity import translation_identity

DOCTYPE = "Persian Translation Ownership"
MAP_ATTR = "_persian_ownership_map"


def clear_cache() -> None:
	frappe.local._persian_ownership_map = None


def key_of(source: str, context: str = "") -> str:
	"""The document name of one string. Also the identity used everywhere else."""
	return translation_identity(source, context or "")


def record(source: str, context: str, value: str, app: str = "") -> None:
	"""Remember that this app wrote `value` for this string.

	Called after a successful write, inside the caller's transaction, so a row
	that is rolled back is not recorded as owned.
	"""
	if not frappe.db.table_exists(DOCTYPE):
		return
	name = key_of(source, context)
	values = {
		"source_text": source or "",
		"context": context or "",
		"last_value": value or "",
		"last_written_at": now(),
	}
	if app:
		values["app"] = app
	if frappe.db.exists(DOCTYPE, name):
		frappe.db.set_value(DOCTYPE, name, values, update_modified=False)
	else:
		frappe.get_doc({"doctype": DOCTYPE, "key_hash": name, **values}).insert(ignore_permissions=True)
	clear_cache()


def owned_map() -> dict[str, frappe._dict]:
	"""Every string this app owns, keyed by document name. Cached per request."""
	cached = getattr(frappe.local, MAP_ATTR, None)
	if cached is not None:
		return cached
	mapped = {}
	if frappe.db.table_exists(DOCTYPE):
		for row in frappe.get_all(
			DOCTYPE,
			fields=["name", "source_text", "context", "last_value", "app"],
			limit_page_length=0,
		):
			mapped[row.name] = frappe._dict(row)
	frappe.local._persian_ownership_map = mapped
	return mapped


def owns(source: str, context: str = "") -> bool:
	return key_of(source, context) in owned_map()


def last_value(source: str, context: str = "") -> str:
	row = owned_map().get(key_of(source, context))
	return (row.last_value or "") if row else ""
