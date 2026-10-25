"""This app's own Desk labels ship in Gettext, not in the public catalogue."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.translate import get_all_translations

from smartprocee_erpnext_persiant.persian_translation.catalogue import read_catalogue
from smartprocee_erpnext_persiant.persian_translation.service import catalogue_path

NATIVE_UI = {
	"Persian Translation": "فارسی‌ساز",
	"Persian Translation Source": "منابع ترجمه فارسی",
	"Persian Font Family": "خانواده فونت فارسی",
	"Persian Snapshot": "نسخه پشتیبان فارسی‌ساز",
	"Persian Translation Operation": "عملیات ترجمه فارسی",
	"Persian Translation Ownership": "مالکیت ترجمه فارسی",
	"Persian Translation Backup": "پشتیبان ترجمه فارسی",
}


class TestNativeUiTranslations(IntegrationTestCase):
	def test_persian_session_reads_native_labels_from_gettext(self):
		from frappe.gettext.translate import get_translations_from_mo

		from smartprocee_erpnext_persiant.install import compile_native_translations

		compile_native_translations()
		# Site Translation rows may overlay these keys. The shipped Gettext
		# catalogue is what a fresh install reads before any scan or import.
		native = get_translations_from_mo("fa", "smartprocee_erpnext_persiant")
		english = get_all_translations("en")
		for source, expected in NATIVE_UI.items():
			with self.subTest(source):
				self.assertEqual(native.get(source), expected)
				self.assertNotEqual(english.get(source), expected)

	def test_native_labels_are_not_in_the_public_catalogue(self):
		sources = {row[0] for row in read_catalogue(catalogue_path())}
		for source in NATIVE_UI:
			with self.subTest(source):
				self.assertNotIn(source, sources)

	def test_app_doctypes_are_marked_translated(self):
		for source in NATIVE_UI:
			if source == "Persian Translation":
				continue
			if not frappe.db.exists("DocType", source):
				continue
			with self.subTest(source):
				self.assertTrue(frappe.get_meta(source).translated_doctype)
