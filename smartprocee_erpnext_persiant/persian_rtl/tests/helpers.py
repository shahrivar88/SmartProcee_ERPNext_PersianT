"""Put site-wide decisions back the way a test found them.

A Frappe integration test rolls its transaction back when the class ends, but any
code path that commits -- and the background-operation tests commit on purpose --
carries whatever a test wrote along with it. The two classes that switch
`Persian RTL Settings` on used to leave it on for whichever class committed next,
so a full `bench run-tests` could end with the site RTL-enabled and the CRM
adapter switched on.

These helpers make a test class own the decisions it changes, so the suite always
finishes in the state it started in.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from smartprocee_erpnext_persiant.persian_rtl import settings

SNAPSHOT = "Persian Snapshot"


def _settings_ready() -> bool:
	return bool(frappe.db.exists("DocType", settings.SETTINGS_DOCTYPE))


def capture() -> dict | None:
	"""The RTL decisions as they are right now, or ``None`` before `bench migrate`."""
	if not _settings_ready():
		return None
	doc = frappe.get_doc(settings.SETTINGS_DOCTYPE)
	return {
		"enabled": cint(doc.enabled),
		"diagnostic_mode": cint(doc.diagnostic_mode),
		"adapters": {
			row.name: {
				"enabled": cint(row.enabled),
				"override_version_check": cint(row.override_version_check),
				"use_system_font": cint(row.use_system_font),
				"admin_notes": row.admin_notes or "",
			}
			for row in doc.adapters
		},
	}


def restore(state: dict | None) -> None:
	"""Write the captured decisions back and commit them.

	The write goes straight to the stored rows: restoring state is not an
	administrator decision, so it must not create a `pre_rtl` restore point of its
	own. Committing is the point of this function -- the operation tests that run
	later in the same process commit whatever transaction they inherit.
	"""
	if not state or not _settings_ready():
		return
	frappe.db.set_single_value(settings.SETTINGS_DOCTYPE, "enabled", state["enabled"])
	frappe.db.set_single_value(settings.SETTINGS_DOCTYPE, "diagnostic_mode", state["diagnostic_mode"])
	for name, values in state["adapters"].items():
		if frappe.db.exists(settings.ADAPTER_DOCTYPE, name):
			frappe.db.set_value(settings.ADAPTER_DOCTYPE, name, values, update_modified=False)
	frappe.clear_document_cache(settings.SETTINGS_DOCTYPE, settings.SETTINGS_DOCTYPE)
	frappe.db.commit()


def is_enabled() -> bool:
	state = capture() or {}
	return bool(state.get("enabled"))


def snapshot_names() -> set[str]:
	if not frappe.db.exists("DocType", SNAPSHOT):
		return set()
	return set(frappe.get_all(SNAPSHOT, pluck="name", limit_page_length=0))


def drop_new_snapshots(existing: set[str]) -> None:
	"""Remove the restore points that appeared during the test, and only those."""
	created = snapshot_names() - set(existing or ())
	for name in created:
		frappe.delete_doc(SNAPSHOT, name, force=1, ignore_on_trash=True, ignore_permissions=True)
	if created:
		frappe.db.commit()


class RTLStateMixin:
	"""Capture the RTL decisions in `setUp` and put them back when the test ends.

	Mixed in *before* `IntegrationTestCase`, so the subclass must call
	`super().setUp()` before it switches anything on. The restore is a cleanup, so
	it runs even when the test fails.
	"""

	def setUp(self):
		super().setUp()
		self._rtl_state = capture()
		self._rtl_snapshots = snapshot_names()
		self.addCleanup(self._restore_rtl_state)

	def _restore_rtl_state(self):
		restore(self._rtl_state)
		drop_new_snapshots(self._rtl_snapshots)
