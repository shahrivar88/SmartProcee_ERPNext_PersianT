"""Translation Manager: persistence, validation, Excel, provenance and publish."""

import json
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.model.utils.user_settings import get_user_settings
from frappe.tests import IntegrationTestCase
from frappe.translate import clear_cache, get_all_translations

from smartprocee_erpnext_persiant.persian_translation import service
from smartprocee_erpnext_persiant.persian_translation.catalogue import (
	catalogue_map,
	merge_overrides,
	read_catalogue,
	write_catalogue_atomic,
)
from smartprocee_erpnext_persiant.persian_translation.excel_io import (
	build_workbook,
	classify_import_rows,
	read_workbook,
)
from smartprocee_erpnext_persiant.persian_translation.page.persian_translation_manager.persian_translation_manager import (
	save_column_widths,
)
from smartprocee_erpnext_persiant.persian_translation.provenance import OwnershipIndex
from smartprocee_erpnext_persiant.persian_translation.publish import publish_overrides
from smartprocee_erpnext_persiant.persian_translation.release_check import audit_catalogue
from smartprocee_erpnext_persiant.persian_translation.tests.helpers import MARKER
from smartprocee_erpnext_persiant.persian_translation.validate import translation_error

CORE_KEY = ("Customer", "")
LOCAL_ONLY = (f"{MARKER} LOCAL ONLY", "")


class MarkerMixin:
	"""Remove every row this suite writes, so the site is left as it was found."""

	def cleanup_marker_rows(self):
		for name in frappe.get_all(
			"Translation",
			filters={"language": "fa", "source_text": ["like", f"{MARKER}%"]},
			pluck="name",
			limit_page_length=0,
		):
			frappe.delete_doc("Translation", name, force=1)
		for name in frappe.get_all(
			"Translation",
			filters={"language": "fa", "translated_text": ["like", f"{MARKER}%"]},
			pluck="name",
			limit_page_length=0,
		):
			frappe.delete_doc("Translation", name, force=1)
		if frappe.db.table_exists("Persian Translation Backup"):
			for name in frappe.get_all(
				"Persian Translation Backup",
				filters={"source_text": ["like", f"{MARKER}%"]},
				pluck="name",
				limit_page_length=0,
			):
				frappe.delete_doc("Persian Translation Backup", name, force=1)
		clear_cache()

	def setUp(self):
		super().setUp()
		self.cleanup_marker_rows()
		self.addCleanup(self.cleanup_marker_rows)


class TestTranslationPersistence(MarkerMixin, IntegrationTestCase):
	def test_saved_translation_is_visible_to_frappe_only_for_fa(self):
		saved = service.save_translations([{"source_text": f"{MARKER} PLAIN", "translated_text": "ساده"}])
		self.assertEqual(saved["saved"], 1)
		clear_cache()
		self.assertEqual(get_all_translations("fa").get(f"{MARKER} PLAIN"), "ساده")
		self.assertIn(get_all_translations("en").get(f"{MARKER} PLAIN"), (None, ""))

	def test_context_stays_independent(self):
		context = "Button in list view actions menu"
		service.save_translations(
			[
				{"source_text": f"{MARKER} CTX", "context": context, "translated_text": "دکمه"},
				{"source_text": f"{MARKER} CTX", "context": "", "translated_text": "زمینه خالی"},
			]
		)
		clear_cache()
		persian = get_all_translations("fa")
		self.assertEqual(persian.get(f"{MARKER} CTX:{context}"), "دکمه")
		self.assertEqual(persian.get(f"{MARKER} CTX"), "زمینه خالی")

	def test_saving_the_same_value_is_a_no_op(self):
		row = {"source_text": f"{MARKER} SAME", "context": "", "translated_text": "یکسان"}
		self.assertEqual(service.save_translations([row])["saved"], 1)
		self.assertEqual(service.save_translations([row])["saved"], 0)

	def test_blank_value_is_never_written(self):
		self.assertEqual(service.save_translations([{"source_text": f"{MARKER} BLANK", "translated_text": "  "}])["saved"], 0)
		self.assertFalse(frappe.db.exists("Translation", {"language": "fa", "source_text": f"{MARKER} BLANK"}))

	def test_an_existing_core_translation_is_untouched(self):
		before = get_all_translations("fa").get("Customer")
		service.save_translations([{"source_text": f"{MARKER} PLAIN", "translated_text": "ساده"}])
		clear_cache()
		self.assertEqual(get_all_translations("fa").get("Customer"), before)

	def test_broken_placeholder_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			service.save_translations([{"source_text": "Hello {0}", "translated_text": "بدون جایگزین"}])

	def test_forbidden_html_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			service.save_translations(
				[{"source_text": "Some label", "translated_text": "<script>alert(1)</script>"}]
			)


	def test_a_frappe_cache_clear_is_enough_to_see_a_removal(self):
		"""The app must not hold a second copy of the merged `fa` dictionary.

		``frappe.translate.clear_cache()`` evicts the merged dictionary that
		Frappe owns, so anything reading through it sees the change. A cache of our
		own would survive that eviction and keep serving the removed value for the
		rest of the process, which is exactly how a removed string used to stay
		visible after a write.
		"""
		source = f"{MARKER} CACHE"
		service.save_translations([{"source_text": source, "translated_text": "مقدار"}])
		clear_cache()
		self.assertEqual(service.effective_translation(source, ""), "مقدار")

		# Removed behind the service's back, so only Frappe's own invalidation can
		# make the removal visible.
		frappe.db.delete("Translation", {"language": "fa", "source_text": source})
		clear_cache()

		self.assertEqual(service.effective_translation(source, ""), "")


class TestChecksCleanup(IntegrationTestCase):
	"""`checks.run` must remove only its own marker rows, never a real translation."""

	def test_the_harness_refuses_a_site_that_did_not_opt_in_before_any_write(self):
		from smartprocee_erpnext_persiant.persian_translation import checks

		catalogue = Path(checks.catalogue_path())

		def state():
			return (
				frappe.db.count("Translation"),
				frappe.db.count("Persian Snapshot"),
				frappe.db.count("Persian Translation Operation"),
				frappe.db.count("Persian Translation Ownership"),
				catalogue.read_bytes(),
			)

		before = state()
		for conf in ({checks.OPT_IN: 0, "allow_tests": 1}, {checks.OPT_IN: 1, "allow_tests": 0}):
			with (
				patch.dict(frappe.local.conf, conf),
				patch.object(checks, "_cleanup") as cleanup,
				patch.object(checks, "catalogue_path") as path,
			):
				for entry in (checks.run, checks.seed_persistence_row, checks.verify_persistence_row):
					with self.assertRaises(frappe.PermissionError, msg=f"{entry.__name__} {conf}"):
						entry()
			cleanup.assert_not_called()
			path.assert_not_called()
		self.assertEqual(state(), before)

	def test_cleanup_keeps_every_row_without_the_marker(self):
		from smartprocee_erpnext_persiant.persian_translation import checks

		kept = self._translation("fa", "PTM cleanup keeps this row", "باقی بماند")
		other_language = self._translation("en", f"{MARKER} ENGLISH", "kept")
		by_source = self._translation("fa", f"{MARKER} SOURCE", "حذف")
		by_value = self._translation("fa", "PTM cleanup value marker", f"{MARKER} حذف")

		checks._cleanup()

		self.assertTrue(frappe.db.exists("Translation", kept))
		self.assertTrue(frappe.db.exists("Translation", other_language))
		self.assertFalse(frappe.db.exists("Translation", by_source))
		self.assertFalse(frappe.db.exists("Translation", by_value))

	def test_cleanup_forgets_only_its_own_ownership_claims(self):
		"""The checks write real source strings; their claims must not outlive the run."""
		from smartprocee_erpnext_persiant.persian_translation import checks, ownership

		leaked = "PTM cleanup leaked claim"
		live = "PTM cleanup live claim"
		real = "PTM cleanup real claim"
		ownership.record(leaked, "", f"{MARKER} نشت", app="smartprocee_erpnext_persiant")
		ownership.record(live, "", f"{MARKER} زنده", app="smartprocee_erpnext_persiant")
		self._translation("fa", live, "مقدار کاربر")
		ownership.record(real, "", "مقدار واقعی", app="smartprocee_erpnext_persiant")
		self.addCleanup(self._forget, (leaked, live, real))

		checks._cleanup()

		self.assertFalse(ownership.owns(leaked), "a test claim with no row left is removed")
		self.assertTrue(ownership.owns(live), "a claim whose row still exists is kept")
		self.assertTrue(ownership.owns(real), "a claim without the marker is never touched")

	def _forget(self, sources):
		from smartprocee_erpnext_persiant.persian_translation import ownership

		for source in sources:
			name = frappe.db.get_value(ownership.DOCTYPE, {"source_text": source, "context": ""})
			if name:
				frappe.delete_doc(ownership.DOCTYPE, name, force=1, ignore_permissions=True)
		ownership.clear_cache()
		frappe.db.commit()

	def _translation(self, language, source, value):
		name = (
			frappe.get_doc(
				{"doctype": "Translation", "language": language, "source_text": source, "translated_text": value}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self.addCleanup(self._remove, name)
		return name

	def _remove(self, name):
		if frappe.db.exists("Translation", name):
			frappe.delete_doc("Translation", name, force=1, ignore_permissions=True)
		frappe.db.commit()


class TestValidation(IntegrationTestCase):
	def test_placeholders_must_match(self):
		self.assertIsNotNone(translation_error("Hello {0}", "سلام"))
		self.assertIsNone(translation_error("Hello {0}", "سلام {0}"))
		self.assertIsNone(translation_error("Use %(name)s", "با %(name)s"))
		self.assertIsNotNone(translation_error("Go %s", "برو"))

	def test_html_structure_must_match(self):
		self.assertIsNotNone(translation_error("See <b>Qty</b>", "مقدار"))
		self.assertIsNone(translation_error("See <b>Qty</b>", "مقدار <b>Qty</b>"))

	def test_overlong_context_is_rejected(self):
		self.assertIsNotNone(translation_error("Label", "برچسب", "x" * 141))


class TestExcelRoundTrip(MarkerMixin, IntegrationTestCase):
	def _rows(self):
		return [
			{
				"app": "erpnext",
				"module": "Accounts",
				"source_path": "",
				"source_text": f"{MARKER} IMPORT",
				"context": "",
				"current_translation": "",
				"identity": service.translation_identity(f"{MARKER} IMPORT", ""),
			},
			{
				"app": "frappe",
				"module": "Core",
				"source_path": "",
				"source_text": "Customer Name",
				"context": "",
				"current_translation": f"{MARKER} نام",
				"identity": service.translation_identity("Customer Name", ""),
			},
		]

	def test_workbook_has_one_sheet_per_app(self):
		rows = self._rows() + [
			{
				"app": "frappe",
				"module": "Desk",
				"source_path": "",
				"source_text": f"{MARKER} DESK",
				"context": "",
				"current_translation": "",
				"identity": service.translation_identity(f"{MARKER} DESK", ""),
			}
		]
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "out.xlsx"
			target.write_bytes(build_workbook(rows))
			workbook = read_workbook(target)
		self.assertEqual({row["sheet"] for row in workbook}, {"frappe", "erpnext"})
		frappe_texts = {row["source_text"] for row in workbook if row["sheet"] == "frappe"}
		self.assertEqual(frappe_texts, {"Customer Name", f"{MARKER} DESK"})

	def test_workbook_round_trips_every_row(self):
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "out.xlsx"
			target.write_bytes(build_workbook(self._rows()))
			workbook = read_workbook(target)
		self.assertEqual(len(workbook), 2)
		imported = next(row for row in workbook if row["source_text"] == f"{MARKER} IMPORT")
		self.assertEqual(imported["identity"], service.translation_identity(f"{MARKER} IMPORT", ""))
		self.assertEqual(imported["app"], "erpnext")

	def test_mismatched_identity_is_rejected(self):
		classified = classify_import_rows(
			[
				{
					"source_text": f"{MARKER} IMPORT",
					"context": "",
					"new_translation": "چیزی",
					"identity": "not-the-right-identity",
				}
			],
			lambda source, context: "",
			service.translation_identity,
		)
		self.assertEqual(classified["actions"], [])
		self.assertEqual(len(classified["errors"]), 1)

	def test_same_source_and_context_with_different_values_are_both_accepted(self):
		"""Different Persian wording for one source is a translator's choice, not an error."""
		for context in ("", "Sales Invoice"):
			with self.subTest(context=context):
				identity = service.translation_identity(f"{MARKER} DUP", context)
				classified = classify_import_rows(
					[
						{
							"source_text": f"{MARKER} DUP",
							"context": context,
							"new_translation": "الف",
							"identity": identity,
						},
						{
							"source_text": f"{MARKER} DUP",
							"context": context,
							"new_translation": "ب",
							"identity": identity,
						},
					],
					lambda source, context: "",
					service.translation_identity,
				)
				self.assertEqual(classified["errors"], [])
				self.assertNotIn("conflicts", classified)
				self.assertEqual([row["translated_text"] for row in classified["actions"]], ["الف", "ب"])
				self.assertEqual([row["row_index"] for row in classified["actions"]], [1, 2])

	def test_repeating_the_same_value_is_accepted(self):
		classified = classify_import_rows(
			[
				{
					"source_text": f"{MARKER} SAME2",
					"context": "",
					"new_translation": "یکسان",
					"identity": service.translation_identity(f"{MARKER} SAME2", ""),
				},
				{
					"source_text": f"{MARKER} SAME2",
					"context": "",
					"new_translation": "یکسان",
					"identity": service.translation_identity(f"{MARKER} SAME2", ""),
				},
			],
			lambda source, context: "",
			service.translation_identity,
		)
		self.assertEqual(classified["errors"], [])
		self.assertEqual(len(classified["actions"]), 2)

	def test_blank_cell_does_not_delete_an_existing_translation(self):
		service.save_translations([{"source_text": "Customer Name", "translated_text": f"{MARKER} نام"}])
		clear_cache()
		classified = classify_import_rows(
			[
				{
					"source_text": "Customer Name",
					"context": "",
					"new_translation": "",
					"identity": service.translation_identity("Customer Name", ""),
				}
			],
			service.effective_translation,
			service.translation_identity,
		)
		self.assertEqual(classified["actions"], [])
		self.assertEqual(classified["unchanged"], 1)
		self.assertEqual(service.save_translations(classified["actions"])["saved"], 0)
		clear_cache()
		self.assertEqual(get_all_translations("fa").get("Customer Name"), f"{MARKER} نام")

	def test_generated_workbook_is_readable_by_the_importer(self):
		payloads = [
			payload
			for payload in service.get_rows(app="erpnext", start=0, page_length=60)["rows"]
			if "{" not in payload["source_text"] and "%" not in payload["source_text"]
		][:2]
		self.assertTrue(payloads, "the index should expose plain erpnext strings")
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "export.xlsx"
			target.write_bytes(build_workbook(payloads))
			rows = read_workbook(target)
		self.assertEqual(len(rows), len(payloads))

		# The exporter fills "New" with the current value, so a plain re-import changes nothing.
		classified = classify_import_rows(rows, service.effective_translation, service.translation_identity)
		self.assertEqual(classified["errors"], [])
		self.assertEqual(classified["actions"], [])
		self.assertEqual(classified["unchanged"], len(rows))

		rows[0]["new_translation"] = f"{MARKER} ویرایش"
		classified = classify_import_rows(rows, service.effective_translation, service.translation_identity)
		self.assertEqual(classified["errors"], [])
		self.assertEqual(len(classified["actions"]), 1)


class TestGlobalSort(IntegrationTestCase):
	"""Sorting must order the whole filtered set, then take the page from it.

	Sorting the page that happens to be on screen would look correct in a small
	dataset and silently wrong in the real one, so the checks below compare a
	short page against the same query asked for a much larger page. If the sort
	were page-only, the two would disagree.
	"""

	APP = "erpnext"

	def _rows(self, **kwargs):
		return service.get_rows(app=self.APP, **kwargs)["rows"]

	def test_the_total_is_the_filtered_set_not_the_page(self):
		result = service.get_rows(app=self.APP, start=0, page_length=5)
		self.assertEqual(result["total"], frappe.db.count(service.SOURCE_DOCTYPE, {"app": self.APP}))
		self.assertEqual(len(result["rows"]), 5)
		self.assertGreater(result["total"], 5)

	def test_a_payload_sorted_page_is_the_head_of_the_global_order(self):
		"""`نوع` and `محل استفاده` only exist after a row becomes a payload.

		They take the in-memory path, which is exactly where a page-only sort
		would hide, so this is the case that matters most.
		"""
		for column in ("kind", "location", "status"):
			with self.subTest(column=column):
				head = self._rows(start=0, page_length=100, sort_by=column, sort_order="asc")
				page = self._rows(start=0, page_length=7, sort_by=column, sort_order="asc")
				self.assertEqual(
					[row["name"] for row in page],
					[row["name"] for row in head[:7]],
					f"{column}: a short page is not the head of the global order",
				)
				self.assertEqual(
					[row["name"] for row in self._rows(start=7, page_length=7, sort_by=column, sort_order="asc")],
					[row["name"] for row in head[7:14]],
					f"{column}: the second page is not the next slice of the global order",
				)

	def test_a_column_sorted_page_is_the_head_of_the_global_order(self):
		expected = frappe.db.get_all(
			service.SOURCE_DOCTYPE,
			filters={"app": self.APP},
			pluck="source_text",
			order_by="source_text asc",
			limit_page_length=5,
		)
		page = self._rows(start=0, page_length=5, sort_by="source_text", sort_order="asc")
		self.assertEqual([row["source_text"] for row in page], expected)

	def test_the_direction_reverses_the_global_order(self):
		ascending = self._rows(start=0, page_length=5, sort_by="source_text", sort_order="asc")
		descending = self._rows(start=0, page_length=5, sort_by="source_text", sort_order="desc")
		self.assertNotEqual(
			[row["name"] for row in ascending],
			[row["name"] for row in descending],
			"descending must not return the ascending head",
		)
		self.assertEqual(
			[row["name"] for row in descending],
			[row["name"] for row in self._rows(start=0, page_length=100, sort_by="source_text", sort_order="desc")[:5]],
		)

	def test_a_payload_sorted_page_two_continues_page_one(self):
		"""`تعداد در هر صفحه` is the page, not the set: page two must not repeat it."""
		head = self._rows(start=0, page_length=30, sort_by="kind", sort_order="asc")
		page_two = self._rows(start=15, page_length=15, sort_by="kind", sort_order="asc")
		self.assertEqual(
			[row["name"] for row in page_two],
			[row["name"] for row in head[15:30]],
			"the second page is not the next slice of the global order",
		)

	def test_app_sort_has_a_deterministic_tiebreaker(self):
		"""`برنامه` has very few distinct values, so ties must still be stable.

		Without a unique secondary key the database may return the tied rows in any
		order, and page two would repeat or skip rows.
		"""
		head = self._rows(start=0, page_length=50, sort_by="app", sort_order="asc")
		second = self._rows(start=25, page_length=25, sort_by="app", sort_order="asc")
		self.assertEqual(
			[row["name"] for row in second],
			[row["name"] for row in head[25:50]],
		)

	def test_translation_column_is_sortable_and_empties_come_last(self):
		ascending = self._rows(start=0, page_length=20, sort_by="translation", sort_order="asc")
		values = [(row["current_translation"] or "") for row in ascending]
		self.assertTrue(all(value.strip() for value in values), "empty translations must sort last")
		self.assertEqual(values, sorted(values), "the asc order is not ascending")

		descending = self._rows(start=0, page_length=20, sort_by="translation", sort_order="desc")
		reverse_values = [(row["current_translation"] or "") for row in descending]
		self.assertTrue(all(value.strip() for value in reverse_values))
		self.assertEqual(reverse_values, sorted(reverse_values, reverse=True))

	def test_translation_sort_page_is_the_head_of_the_global_order(self):
		head = self._rows(start=0, page_length=100, sort_by="translation", sort_order="asc")
		page = self._rows(start=0, page_length=6, sort_by="translation", sort_order="asc")
		self.assertEqual(
			[row["name"] for row in page],
			[row["name"] for row in head[:6]],
		)

	def test_the_workbook_lists_rows_in_the_same_order_as_the_grid(self):
		"""The export must not re-rank a column the database already ranked.

		`bench export`-style re-sorting in Python would order text by Unicode code
		points while the grid uses the database collation, so the workbook would
		list the same rows in a different order than the page it came from.
		"""
		for column in ("source_text", "app", "kind", "location", "status"):
			with self.subTest(column=column):
				grid = self._rows(start=0, page_length=10, sort_by=column, sort_order="asc")
				exported = service._filtered_payloads(app=self.APP, sort_by=column, sort_order="asc")
				self.assertGreater(len(exported), 10)
				self.assertEqual(
					[row["name"] for row in grid],
					[row["name"] for row in exported[:10]],
					f"{column}: the workbook order is not the grid order",
				)


class TestManagerSortContract(IntegrationTestCase):
	"""The Desk table delegates sorting to the server, and the two agree on names.

	``frappe-datatable`` fires ``onSortColumn`` with the column object
	(``columnmanager.sortColumn``), never with ``(colIndex, sortOrder)``. A
	handler written for the two-argument form receives ``undefined`` as the
	index, finds no column and returns early -- the click then sorts only the
	rows on screen and the server is never asked, which looks like a working
	sort over a small dataset and a wrong one over the real one.
	"""

	PAGE_DIR = (
		"persian_translation",
		"page",
		"persian_translation_manager",
		"persian_translation_manager.js",
	)

	@classmethod
	def _source(cls) -> str:
		path = frappe.get_app_path("smartprocee_erpnext_persiant", *cls.PAGE_DIR)
		with open(path, encoding="utf-8") as handle:
			return handle.read()

	def test_the_sort_handler_takes_only_the_column_object(self):
		source = self._source()
		self.assertIn("onSortColumn: (column) => this.on_sort(column)", source)

	def test_the_sort_handler_does_not_read_a_column_index(self):
		self.assertNotRegex(
			self._source(),
			r"onSortColumn:\s*\([^)]*,",
			"a second parameter means the handler was written for a signature the table never sends",
		)

	def test_the_sortable_columns_match_the_columns_the_server_can_sort(self):
		declared = re.search(r"const SORTABLE_COLUMNS = \[(.*?)\];", self._source(), re.S)
		self.assertIsNotNone(declared, "the page must declare its sortable columns")
		self.assertEqual(
			set(re.findall(r'"([A-Za-z_]+)"', declared.group(1))),
			set(service.PAYLOAD_SORT_COLUMNS),
			"a column the page offers to sort is not a column the server can sort",
		)

	def test_the_sort_indicator_follows_the_servers_order(self):
		"""The arrow is a display of the server's answer, never a local sort."""
		source = self._source()
		self.assertIn("apply_sort_indicator()", source)
		self.assertIn('columns[index].sortOrder = this.sort_order === "desc" ? "desc" : "asc"', source)


class TestSearch(IntegrationTestCase):
	"""Search runs on the server over the whole indexed set, across the visible fields."""
	APP = "erpnext"
	NEEDLE = "Assign To"

	def _haystack(self, row):
		return " ".join(
			[
				row["source_text"] or "",
				row["context"] or "",
				row["current_translation"] or "",
				row["source_path"] or "",
				row["app"] or "",
				row["module"] or "",
				row["kind"] or "",
				row["location"] or "",
			]
		).casefold()

	def test_search_matches_every_returned_row(self):
		result = service.get_rows(search=self.NEEDLE, page_length=50)
		self.assertGreater(result["total"], 0)
		for row in result["rows"]:
			with self.subTest(row["source_text"]):
				self.assertIn(self.NEEDLE.casefold(), self._haystack(row))

	def test_search_is_case_insensitive(self):
		lower = service.get_rows(search=self.NEEDLE.casefold(), page_length=5)
		upper = service.get_rows(search=self.NEEDLE.upper(), page_length=5)
		self.assertEqual(lower["total"], upper["total"])

	def test_a_match_beyond_the_first_page_is_reachable(self):
		first = service.get_rows(search=self.NEEDLE, start=0, page_length=1)
		self.assertGreater(first["total"], 1, "the needle needs more than one match")
		second = service.get_rows(search=self.NEEDLE, start=1, page_length=1)
		self.assertNotEqual(first["rows"][0]["name"], second["rows"][0]["name"])

	def test_search_combines_with_a_filter(self):
		filtered = service.get_rows(search=self.NEEDLE, app=self.APP, page_length=10)
		for row in filtered["rows"]:
			self.assertEqual(row["app"], self.APP)

	def test_search_combines_with_sort(self):
		page = service.get_rows(
			search=self.NEEDLE, sort_by="source_text", sort_order="asc", page_length=6
		)["rows"]
		self.assertTrue(page, "the needle must still match after the sort is applied")
		for row in page:
			with self.subTest(row["name"]):
				self.assertIn(self.NEEDLE.casefold(), self._haystack(row))

		# The database orders text with its own collation, which is
		# case-insensitive, so the contract is "non-decreasing ignoring case" and
		# not Python's codepoint order.
		values = [row["source_text"].casefold() for row in page]
		self.assertEqual(values, sorted(values), "the searched page is not in ascending order")

		# ...and the page is the head of the same globally sorted result set, so
		# pagination cannot drift away from the ordering.
		head = service.get_rows(
			search=self.NEEDLE, sort_by="source_text", sort_order="asc", page_length=100
		)["rows"]
		self.assertEqual([row["name"] for row in page], [row["name"] for row in head[:6]])

		descending = service.get_rows(
			search=self.NEEDLE, sort_by="source_text", sort_order="desc", page_length=6
		)["rows"]
		reverse_values = [row["source_text"].casefold() for row in descending]
		self.assertEqual(reverse_values, sorted(reverse_values, reverse=True))

	def test_clearing_the_search_restores_the_full_count(self):
		full = service.get_rows(page_length=1)["total"]
		searched = service.get_rows(search=self.NEEDLE, page_length=1)["total"]
		cleared = service.get_rows(search="", page_length=1)["total"]
		self.assertLess(searched, full)
		self.assertEqual(cleared, full)

	def test_a_persian_translation_value_is_searchable(self):
		result = service.get_rows(search="مشتری", page_length=5)
		self.assertGreater(result["total"], 0)

	def test_the_matching_fields_include_app_and_location(self):
		payload = {
			"source_text": "x",
			"context": "",
			"current_translation": "",
			"source_path": "",
			"app": "raven",
			"module": "",
			"kind": "",
			"location": "Page: raven workspaces",
		}
		self.assertTrue(service._matches_search(payload, "raven"))
		self.assertTrue(service._matches_search(payload, "workspaces"))
		self.assertTrue(service._matches_search(payload, "RAVEN"))
		self.assertFalse(service._matches_search(payload, "erpnext"))


class TestProvenance(MarkerMixin, IntegrationTestCase):
	def test_a_core_label_is_proven_to_be_owned(self):
		index = OwnershipIndex.for_catalogue_owners()
		self.assertIsNotNone(index.owner_of(*CORE_KEY))
		self.assertIsNone(index.owner_of(*LOCAL_ONLY))

	def test_the_shipped_catalogue_passes_the_release_gate(self):
		audit = audit_catalogue()
		self.assertEqual(audit.rows, len(read_catalogue(service.catalogue_path())))
		self.assertEqual(audit.failures, [])

	def test_publish_writes_only_core_owned_rows(self):
		index = OwnershipIndex.for_catalogue_owners()
		overrides = {CORE_KEY: f"{MARKER} مشتری", LOCAL_ONLY: "فقط محلی"}
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "fa.csv"
			shutil.copyfile(service.catalogue_path(), target)
			before = len(read_catalogue(target))
			result = publish_overrides(target, overrides, index)
			published = catalogue_map(read_catalogue(target))
		self.assertEqual(result["updated"], 1)
		self.assertEqual(result["appended"], 0)
		self.assertEqual(result["withheld"], 1)
		self.assertEqual(published[CORE_KEY], f"{MARKER} مشتری")
		self.assertNotIn(LOCAL_ONLY, published)
		self.assertEqual(len(published), before)

	def test_publish_never_drops_catalogue_rows(self):
		rows = read_catalogue(service.catalogue_path())
		merged, stats = merge_overrides(rows, {(f"{MARKER} NEW", ""): "جدید"})
		self.assertEqual(len(merged), len(rows) + 1)
		self.assertEqual(stats["appended"], 1)
		self.assertEqual(stats["updated"], 0)

	def test_an_invalid_publish_leaves_the_file_untouched(self):
		"""`publish_overrides` refuses to rewrite fa.csv when a value is invalid."""
		index, key = self._owned_placeholder_key()
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "fa.csv"
			shutil.copyfile(service.catalogue_path(), target)
			original = target.read_bytes()
			with self.assertRaises(frappe.ValidationError):
				publish_overrides(target, {key: "بدون جایگزین"}, index)
			self.assertEqual(target.read_bytes(), original)
			self.assertEqual(sorted(path.name for path in target.parent.iterdir()), ["fa.csv"])

	def _owned_placeholder_key(self):
		index = OwnershipIndex.for_catalogue_owners()
		for row in read_catalogue(service.catalogue_path()):
			source = row[0]
			context = row[2] if len(row) > 2 else ""
			if "{0}" in source and index.owner_of(source, context):
				return index, (source, context)
		self.skipTest("no core-owned source with a positional placeholder in the catalogue")

	def test_atomic_write_leaves_no_temporary_file(self):
		with tempfile.TemporaryDirectory() as tmp:
			target = Path(tmp) / "fa.csv"
			shutil.copyfile(service.catalogue_path(), target)
			rows = read_catalogue(target)
			backup = write_catalogue_atomic(target, rows)
			self.assertEqual(catalogue_map(read_catalogue(target)), catalogue_map(rows))
			self.assertTrue(backup.exists())
			self.assertEqual(list(target.parent.glob(".fa.csv.tmp-*")), [])


class TestManagerApi(MarkerMixin, IntegrationTestCase):
	def test_save_column_widths_goes_through_the_standard_api(self):
		cleaned = save_column_widths(json.dumps({"app": 120, "unknown_column": 999, "context": 10}))
		self.assertEqual(cleaned, {"app": 120})
		stored = json.loads(get_user_settings("persian-translation-manager"))
		self.assertEqual(stored["column_widths"], {"app": 120})
		rows = frappe.db.sql(
			"select data from `__UserSettings` where `user`=%s and `doctype`=%s",
			(frappe.session.user, "persian-translation-manager"),
		)
		self.assertTrue(rows)
		self.assertEqual(json.loads(rows[0][0])["column_widths"], {"app": 120})

	def test_guest_is_denied(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				service.get_rows()
		finally:
			frappe.set_user("Administrator")

	def test_export_produces_a_workbook(self):
		frappe.local.response = frappe._dict({})
		service.export_excel(app="smartprocee_erpnext_persiant")
		content = frappe.response.get("filecontent") or b""
		self.assertEqual(content[:2], b"PK")
		self.assertEqual(frappe.response.get("type"), "binary")
		self.assertTrue(read_workbook(BytesIO(content)))


class TestCatalogueIntegrity(IntegrationTestCase):
	def test_catalogue_is_parseable_and_has_no_empty_translations(self):
		rows = read_catalogue(service.catalogue_path())
		self.assertGreater(len(rows), 1000)
		self.assertTrue(all(row[0].strip() for row in rows))
		self.assertTrue(all(row[1].strip() for row in rows))

	def test_catalogue_has_no_duplicate_identity(self):
		from smartprocee_erpnext_persiant.persian_translation.catalogue import catalogue_records

		seen = set()
		duplicates = []
		for line, row in catalogue_records(service.catalogue_path()):
			key = (row[0], row[2] if len(row) > 2 else "")
			if key in seen:
				duplicates.append(line)
			seen.add(key)
		self.assertEqual(duplicates, [])

	def test_workbook_bytes_are_deterministic(self):
		self.assertEqual(build_workbook([]), build_workbook([]))
		self.assertEqual(BytesIO(build_workbook([])).getvalue()[:2], b"PK")
