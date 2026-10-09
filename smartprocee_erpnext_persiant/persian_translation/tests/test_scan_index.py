"""The scan index must describe the currently installed apps only."""

import re

import frappe
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant.persian_translation.scan import (
	SOURCE_DOCTYPE,
	message_name,
	reconcile_index,
	run_scan,
)

STALE_APP = "ptm_stale_app"
OWN_APP = "smartprocee_erpnext_persiant"


class ScanIndexMixin:
	def installed_apps(self) -> list[str]:
		return frappe.get_installed_apps(_ensure_on_bench=True)

	def indexed_apps(self) -> set[str]:
		return set(frappe.db.sql(f"select distinct app from `tab{SOURCE_DOCTYPE}`", pluck=True))

	def add_stale_row(self, app: str = STALE_APP) -> str:
		doc = frappe.get_doc(
			{
				"doctype": SOURCE_DOCTYPE,
				"app": app,
				"module": "Stale",
				"source_path": "leftover",
				"source_text": "__PTM_TEST__ STALE ROW",
				"context": "",
			}
		).insert()
		return doc.name

	def drop_stale_rows(self):
		# run_scan() commits, so the synthetic row is already in the site database
		# by the time the test ends. Deleting it inside a transaction the test
		# runner later rolls back would leave it behind, visible in the manager.
		frappe.db.delete(SOURCE_DOCTYPE, {"app": STALE_APP})
		frappe.db.commit()


class TestReconcileIndex(ScanIndexMixin, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(self.drop_stale_rows)

	def test_index_rows_of_removed_apps_are_dropped(self):
		self.assertNotIn(STALE_APP, self.installed_apps())
		self.add_stale_row()
		self.assertIn(STALE_APP, self.indexed_apps())

		removed = reconcile_index(self.installed_apps())

		self.assertGreaterEqual(removed, 1)
		self.assertNotIn(STALE_APP, self.indexed_apps())

	def test_index_rows_of_installed_apps_are_kept(self):
		before = self.indexed_apps()
		reconcile_index(self.installed_apps())
		self.assertEqual(self.indexed_apps(), before)
		self.assertTrue({OWN_APP} & self.indexed_apps())

	def test_reconcile_never_touches_translations(self):
		self.add_stale_row()
		before = frappe.db.count("Translation")
		reconcile_index(self.installed_apps())
		self.assertEqual(frappe.db.count("Translation"), before)

	def test_an_empty_installed_list_is_a_no_op(self):
		self.add_stale_row()
		self.assertEqual(reconcile_index([]), 0)
		self.assertIn(STALE_APP, self.indexed_apps())


class TestScanModes(ScanIndexMixin, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(self.drop_stale_rows)

	def test_partial_scan_keeps_rows_of_other_apps(self):
		self.add_stale_row()
		erpnext_rows = frappe.db.count(SOURCE_DOCTYPE, {"app": "erpnext"})

		result = run_scan(apps=[OWN_APP])

		self.assertTrue(result["strings"] > 0)
		self.assertEqual(result["stale_apps_removed"], 0)
		self.assertIn(STALE_APP, self.indexed_apps())
		self.assertEqual(frappe.db.count(SOURCE_DOCTYPE, {"app": "erpnext"}), erpnext_rows)
		self.assertTrue(frappe.db.count(SOURCE_DOCTYPE, {"app": OWN_APP}) > 0)

	def test_full_scan_drops_removed_apps(self):
		self.add_stale_row()
		result = run_scan()
		self.assertTrue(result["strings"] > 1000)
		self.assertGreaterEqual(result["stale_apps_removed"], 1)
		self.assertNotIn(STALE_APP, self.indexed_apps())
		self.assertTrue(frappe.db.count(SOURCE_DOCTYPE, {"app": "erpnext"}) > 1000)


class TestScanHelpers(IntegrationTestCase):
	def test_message_name_is_deterministic_and_bounded(self):
		name = message_name("erpnext", "Customer", "List")
		self.assertEqual(name, message_name("erpnext", "Customer", "List"))
		self.assertNotEqual(name, message_name("erpnext", "Customer", ""))
		self.assertTrue(re.fullmatch(r"PTS-[0-9a-f]{40}", name))
		self.assertLessEqual(len(name), 140)
