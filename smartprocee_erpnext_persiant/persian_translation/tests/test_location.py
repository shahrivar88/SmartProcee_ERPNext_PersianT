"""The location and kind ladder, and the Excel columns the manager shows.

These tests pin the two promises the manager makes to a translator:

* ``نوع`` and ``محل استفاده`` are read from Frappe's own metadata, never guessed,
  and a build path never reaches the screen as if it were a place
* the workbook carries the same readable columns as the table, with the technical
  identity kept at the end

Nothing here writes to the site.
"""

import tempfile
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant.persian_translation import excel_io, kind, location, metadata


class TestKindVocabulary(IntegrationTestCase):
	def test_the_filter_order_lists_every_label_once(self):
		self.assertEqual(len(kind.KIND_LABELS), len(set(kind.KIND_LABELS)))
		self.assertEqual(kind.KIND_LABELS[0], kind.FIELD)
		self.assertIn(kind.UNKNOWN, kind.KIND_LABELS)

	def test_context_and_note_phrases_are_read_as_facts(self):
		self.assertEqual(kind.from_context("Button in list view actions menu"), kind.BUTTON)
		self.assertEqual(kind.from_note("Label of a field in DocType Sales Invoice"), kind.FIELD)
		self.assertEqual(kind.from_note("option in a select field"), kind.OPTION)
		self.assertEqual(kind.from_context(""), "")

	def test_a_runtime_context_is_not_a_note(self):
		self.assertTrue(kind.is_extractor_comment("Label of a field"))
		self.assertFalse(kind.is_extractor_comment("Button in list view"))
		self.assertEqual(kind.comment_text("Button in list view"), "")


class TestMetadata(IntegrationTestCase):
	def test_select_options_drop_dynamic_and_icon_lines(self):
		options = metadata.select_options("$frappe.get_meta('X')\nDraft\nSubmitted\nicon-check\n\n")
		self.assertEqual(options, {"Draft", "Submitted"})

	def test_a_profile_reads_labels_options_and_descriptions(self):
		profile = metadata.profiles(["Sales Invoice"])["Sales Invoice"]
		self.assertIn("Customer", profile.labels)
		self.assertIn("customer", profile.fieldnames("Customer"))
		self.assertIn("Draft", profile.options)

	def test_an_unknown_document_is_simply_absent(self):
		self.assertEqual(metadata.profiles(["PTM No Such Document"]), {})

	def test_a_name_that_matches_no_record_is_asked_about_once(self):
		"""A miss must be remembered, not repeated for every later row.

		``prefetch`` asks about the origin of every row in one pass. A folder slug
		that is not a doctype used to be missing from the store every time it was
		asked about again, so each later row that mentioned it re-ran the four
		metadata queries -- thousands of queries for a single page.
		"""
		asked = []
		original = metadata._rows
		frappe.local._persian_metadata_profiles = {}

		def counting_rows(doctype, filters, fields):
			asked.append(doctype)
			return original(doctype, filters, fields)

		metadata._rows = counting_rows
		try:
			metadata.profiles(["PTM No Such Document"])
			first = len(asked)
			metadata.profiles(["PTM No Such Document"])
		finally:
			metadata._rows = original
		self.assertEqual(first, 4, "one ask covers the four metadata tables")
		self.assertEqual(len(asked), first, "a remembered miss must not be queried again")


class TestLocationLadder(IntegrationTestCase):
	def test_a_field_label_resolves_to_document_and_fieldname(self):
		place = location.resolve("DocType: Sales Invoice", "Customer")
		self.assertEqual(place.label, "Sales Invoice.customer")
		self.assertEqual(place.kind, kind.FIELD)

	def test_a_select_option_resolves_to_the_document(self):
		place = location.resolve("DocType: Sales Invoice", "Draft")
		self.assertEqual(place.label, "Sales Invoice")
		self.assertEqual(place.kind, kind.OPTION)

	def test_the_document_name_resolves_to_itself(self):
		place = location.resolve("DocType: Sales Invoice", "Sales Invoice")
		self.assertEqual(place.label, "Sales Invoice")
		self.assertEqual(place.kind, kind.DOCUMENT)

	def test_a_report_file_resolves_to_the_report(self):
		place = location.resolve("erpnext/accounts/report/general_ledger/general_ledger.py")
		self.assertEqual(place.label, "Report: General Ledger")
		self.assertEqual(place.kind, kind.REPORT)

	def test_a_frontend_bundle_is_never_shown_as_a_place(self):
		place = location.resolve("apps/crm/crm/public/frontend/assets/ViewControls-4vkJmtiW.js")
		self.assertEqual(place.kind, kind.CODE)
		self.assertNotIn("4vkJmtiW", place.label)
		self.assertNotIn("/", place.label)

	def test_a_server_file_resolves_to_the_server_layer(self):
		place = location.resolve("apps/erpnext/erpnext/setup/demo.py")
		self.assertEqual(place.label, "کد سرور")
		self.assertEqual(place.kind, kind.CODE)

	def test_no_origin_and_no_text_is_unknown(self):
		place = location.resolve("", "")
		self.assertEqual(place.label, "")
		self.assertEqual(place.kind, kind.UNKNOWN)

	def test_an_unreadable_origin_is_other_not_unknown(self):
		place = location.resolve("some recorded origin", "")
		self.assertEqual(place.label, "")
		self.assertEqual(place.kind, kind.OTHER)

	def test_an_origin_list_counts_the_other_places(self):
		place = location.resolve("DocType: Sales Invoice|DocType: Sales Order", "Customer")
		self.assertEqual(place.label, "Sales Invoice.customer")
		self.assertGreaterEqual(place.others, 1)

	def test_no_absolute_path_survives_into_a_label(self):
		origins = (
			r"C:\Users\someone\frappe-bench\apps\erpnext\erpnext\setup\demo.py",
			"/home/frappe/frappe-bench/apps/crm/crm/public/frontend/assets/x-abc123.js",
		)
		for origin in origins:
			place = location.resolve(origin)
			for leaked in ("frappe-bench", "Users", "abc123"):
				self.assertNotIn(leaked, place.label, origin)

	def test_prefetch_names_the_documents_of_a_page(self):
		self.assertEqual(location.doctype_names("DocType: Sales Invoice"), {"Sales Invoice"})
		location.prefetch(["DocType: Sales Invoice", "erpnext/stock/doctype/item/item.json"])
		self.assertIn("Sales Invoice", metadata.profiles(["Sales Invoice"]))


class TestExcelColumns(IntegrationTestCase):
	def test_the_columns_match_the_manager_table(self):
		self.assertEqual(
			excel_io.HEADERS,
			(
				"برنامه",
				"نوع",
				"محل استفاده",
				"متن اصلی",
				"ترجمه فعلی",
				"ترجمه جدید",
				"وضعیت",
				"یادداشت",
				"زمینه",
				"شناسه ردیف",
			),
		)
		self.assertEqual(excel_io.HEADERS[-1], "شناسه ردیف")
		self.assertEqual(excel_io.EDITED_COLUMN, "new_translation")

	def test_kind_and_location_survive_a_round_trip(self):
		rows = [
			{
				"app": "erpnext",
				"kind": "فیلد",
				"location": "Sales Invoice.customer",
				"source_text": "Customer",
				"current_translation": "مشتری",
				"status": "translated",
			}
		]
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "columns.xlsx"
			target.write_bytes(excel_io.build_workbook(rows))
			read = excel_io.read_workbook(target)
		self.assertEqual(len(read), 1)
		self.assertEqual(read[0]["kind"], "فیلد")
		self.assertEqual(read[0]["location"], "Sales Invoice.customer")
		self.assertEqual(read[0]["new_translation"], "مشتری")
