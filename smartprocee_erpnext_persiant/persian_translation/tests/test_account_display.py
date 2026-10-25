"""Account Category links and CRM Call Logs use display-only translations."""

import frappe
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant.persian_translation.account_display import (
	CALL_LOGS,
	CALL_LOGS_FA,
	DISPLAY_STRINGS,
	display_label,
	ensure_account_category_translated,
	ensure_call_logs_translation,
	ensure_display_translations,
	ensure_translation_row,
)
from smartprocee_erpnext_persiant.persian_translation.scan import sidebar_nav_labels


class TestAccountDisplay(IntegrationTestCase):
	def test_persian_display_uses_the_catalogue_and_keeps_english(self):
		self.assertEqual(display_label("Long-term Provisions", "en"), "Long-term Provisions")
		self.assertEqual(display_label("Long-term Provisions", "en-US"), "Long-term Provisions")
		self.assertEqual(display_label("Long-term Provisions", "fa"), "ذخایر بلندمدت")

	def test_stored_account_values_are_not_rewritten(self):
		if not frappe.db.exists("DocType", "Account"):
			self.skipTest("Account is not installed")
		rows = frappe.get_all(
			"Account",
			filters={"account_name": "Long-term Provisions"},
			fields=["name", "account_name", "account_category"],
			limit=5,
		)
		if not rows:
			self.skipTest("this site has no Long-term Provisions account")
		for row in rows:
			self.assertEqual(row.account_name, "Long-term Provisions")
			self.assertEqual(row.account_category, "Long-term Provisions")
			self.assertIn("Long-term Provisions", row.name)

	def test_account_category_is_marked_translated(self):
		if not frappe.db.exists("DocType", "Account Category"):
			self.skipTest("Account Category is not installed")
		ensure_account_category_translated()
		self.assertTrue(frappe.get_meta("Account Category").translated_doctype)

	def test_existing_account_category_setter_is_not_overwritten(self):
		if not frappe.db.exists("DocType", "Account Category"):
			self.skipTest("Account Category is not installed")
		ensure_account_category_translated()
		name = frappe.db.exists(
			"Property Setter",
			{
				"doc_type": "Account Category",
				"property": "translated_doctype",
				"doctype_or_field": "DocType",
			},
		)
		if not name:
			self.skipTest("this site has no Account Category Property Setter")
		original = frappe.db.get_value("Property Setter", name, "value")

		def restore():
			frappe.db.set_value("Property Setter", name, "value", original, update_modified=False)
			frappe.clear_cache(doctype="Account Category")

		self.addCleanup(restore)
		frappe.db.set_value("Property Setter", name, "value", "0", update_modified=False)
		frappe.clear_cache(doctype="Account Category")
		ensure_account_category_translated()
		self.assertEqual(frappe.db.get_value("Property Setter", name, "value"), "0")


class TestCallLogsCoverage(IntegrationTestCase):
	def test_the_sidebar_extractor_reads_only_the_nav_list(self):
		source = """
const other = [{ label: 'Ignore Me' }]
const links = [
  {
    label: 'Leads',
    to: 'Leads',
  },
  {
    label: 'Call Logs',
    to: 'Call Logs',
  },
]
function later() {
  return { label: 'Not Nav' }
}
"""
		self.assertEqual(sidebar_nav_labels(source), ["Leads", "Call Logs"])

	def test_the_sidebar_extractor_reads_crm_189_navigation_items(self):
		source = """
export const navigationItems = [
  {
    label: 'Dashboard',
    route: 'Dashboard',
  },
  { label: 'Leads', route: 'Leads' },
  { label: 'Call Logs', route: 'Call Logs' },
]
export function getNavigationItems() {
  return navigationItems
}
"""
		self.assertEqual(sidebar_nav_labels(source), ["Dashboard", "Leads", "Call Logs"])

	def test_call_logs_translation_is_installed_without_changing_fa_csv(self):
		ensure_call_logs_translation()
		self.assertEqual(
			frappe.db.get_value(
				"Translation",
				{"language": "fa", "source_text": CALL_LOGS},
				"translated_text",
			),
			CALL_LOGS_FA,
		)
		from smartprocee_erpnext_persiant.persian_translation.catalogue import read_catalogue
		from smartprocee_erpnext_persiant.persian_translation.service import catalogue_path

		sources = {row[0] for row in read_catalogue(catalogue_path())}
		self.assertNotIn(CALL_LOGS, sources)


class TestRoleAndAppLabelCoverage(IntegrationTestCase):
	def test_third_party_role_labels_are_translation_rows_not_catalogue(self):
		ensure_display_translations()
		from smartprocee_erpnext_persiant.persian_translation.catalogue import read_catalogue
		from smartprocee_erpnext_persiant.persian_translation.service import catalogue_path

		sources = {row[0] for row in read_catalogue(catalogue_path())}
		for source, translated in DISPLAY_STRINGS.items():
			self.assertEqual(
				frappe.db.get_value(
					"Translation",
					{"language": "fa", "source_text": source},
					"translated_text",
				),
				translated,
			)
			self.assertNotIn(source, sources)

	def test_existing_translation_row_is_not_overwritten(self):
		source = "Insights User"
		ensure_translation_row(source, "کاربر Insights")
		frappe.db.set_value(
			"Translation",
			{"language": "fa", "source_text": source},
			"translated_text",
			"مقدار سفارشی",
			update_modified=False,
		)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Translation",
				{"language": "fa", "source_text": source},
				"translated_text",
				"کاربر Insights",
				update_modified=False,
			)
		)
		ensure_display_translations()
		self.assertEqual(
			frappe.db.get_value("Translation", {"language": "fa", "source_text": source}, "translated_text"),
			"مقدار سفارشی",
		)
