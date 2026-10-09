"""The schema guard: an un-migrated site must say so in Persian, not crash.

The manager page is served from the code on the bench while the tables only
appear after ``bench migrate``. When a site is upgraded in code but not migrated
the UI used to raise a raw "DocType ... not found" from inside a query. These
checks pin the behaviour that replaces it.
"""

import inspect

import frappe
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant.persian_rtl import diagnostics
from smartprocee_erpnext_persiant.persian_translation import schema
from smartprocee_erpnext_persiant.persian_translation.page.persian_translation_manager import (
	persian_translation_manager as endpoint,
)


class TestSchemaGuard(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.local._persian_missing_doctypes = None

	def tearDown(self):
		frappe.local._persian_missing_doctypes = None
		super().tearDown()

	def test_a_migrated_site_is_ready(self):
		self.assertEqual(schema.missing_doctypes(), [])
		self.assertTrue(schema.is_ready())
		schema.require_ready()  # must not raise

	def test_this_bench_has_every_required_doctype(self):
		for name in schema.REQUIRED_DOCTYPES:
			with self.subTest(name):
				self.assertTrue(frappe.db.exists("DocType", name), name)

	def test_an_absent_doctype_is_refused_with_the_admin_message(self):
		with _missing("Persian Snapshot"):
			with self.assertRaises(frappe.ValidationError) as context:
				schema.require_ready()
		message = str(context.exception)
		self.assertIn(schema.SCHEMA_TITLE, message)
		self.assertIn("Persian Snapshot", message)
		self.assertIn("bench migrate", message)

	def test_the_manager_endpoint_uses_the_guard(self):
		with _missing("Persian Translation Operation"):
			with self.assertRaises(frappe.ValidationError):
				endpoint.get_rows(start=0, page_length=1)

	def test_the_guard_keeps_the_endpoint_signature(self):
		"""`functools.wraps` must not hide the arguments Frappe has to map."""
		params = list(inspect.signature(endpoint.get_rows).parameters)
		self.assertEqual(
			params,
			["search", "app", "status", "kind", "start", "page_length", "sort_by", "sort_order"],
		)

	def test_each_feature_group_is_reported_on_its_own(self):
		"""Translation and RTL are separate features with separate tables."""
		self.assertEqual(
			schema.REQUIRED_DOCTYPES,
			schema.TRANSLATION_DOCTYPES + schema.RTL_DOCTYPES,
		)
		with _missing("Persian RTL Settings"):
			self.assertFalse(schema.is_ready(schema.RTL_DOCTYPES))
			self.assertTrue(schema.is_ready(schema.TRANSLATION_DOCTYPES))
			self.assertFalse(schema.is_ready())

	def test_a_missing_rtl_table_does_not_block_the_translation_manager(self):
		with _missing("Persian RTL Settings"):
			rows = endpoint.get_rows(start=0, page_length=1)
		self.assertEqual(len(rows["rows"]), 1)

	def test_the_rtl_screen_explains_a_missing_single_instead_of_denying_permission(self):
		with _missing("Persian RTL Settings"):
			with self.assertRaises(frappe.ValidationError) as context:
				diagnostics.compat_report()
		self.assertIn(schema.SCHEMA_TITLE, str(context.exception))

	def test_the_health_endpoint_is_not_guarded(self):
		"""`save_column_widths` touches no app table, so it keeps working."""
		self.assertFalse(_is_guarded(endpoint.save_column_widths))
		self.assertTrue(_is_guarded(endpoint.get_rows))


class _missing:
	"""Report exactly these DocTypes as absent for the duration of the block.

	The stub answers per requested group, the way the real one does, so a check
	scoped to one feature is not made to fail by another feature's tables.
	"""

	def __init__(self, *names):
		self.names = list(names)
		self.original = None

	def __enter__(self):
		self.original = schema.missing_doctypes
		names = list(self.names)

		def stub(doctypes=schema.REQUIRED_DOCTYPES, **_kwargs):
			return [name for name in names if name in doctypes]

		schema.missing_doctypes = stub
		frappe.local._persian_missing_doctypes = None
		return self

	def __exit__(self, *_exc):
		schema.missing_doctypes = self.original
		frappe.local._persian_missing_doctypes = None
		return False


def _is_guarded(fn) -> bool:
	return bool(getattr(fn, "_persian_schema_guarded", False))
