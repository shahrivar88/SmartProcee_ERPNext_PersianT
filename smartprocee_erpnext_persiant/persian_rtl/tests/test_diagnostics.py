"""Detection reports what it found and never assumes an adapter is healthy.

The report is also the portability contract in practice: it is what an
administrator on Server B (frappe + erpnext only) actually sees, so it must not
contain a single absolute path or a site-specific value.
"""

import re

import frappe
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant.persian_rtl import detection, diagnostics, registry

ABSOLUTE_PATH = re.compile(r"([A-Za-z]:[\\/]|/home/|/Users/|/var/folders/|/opt/|\\\\[^\\]+\\[^\\]+)")
REQUIRED_KEYS = (
	"adapter_id",
	"title",
	"target_app",
	"routes",
	"installed",
	"version",
	"version_state",
	"compatible_range",
	"entry_template",
	"root_direction",
	"signature",
	"enabled",
	"eligible",
	"reason",
	"state",
	"risk",
)


class TestDetectionReport(IntegrationTestCase):
	def setUp(self):
		frappe.local.lang = "fa"

	def test_every_adapter_is_reported_with_the_full_shape(self):
		rows = detection.detect_all()
		self.assertEqual(len(rows), len(registry.all_adapters()))
		for row in rows:
			with self.subTest(row.get("adapter_id")):
				for key in REQUIRED_KEYS:
					self.assertIn(key, row)

	def test_states_come_from_the_known_vocabulary(self):
		for row in detection.detect_all():
			with self.subTest(row["adapter_id"]):
				self.assertIn(row["state"], registry.STATE_ORDER)

	def test_an_uninstalled_target_is_reported_not_assumed(self):
		"""Server B has no CRM; that must be a report, not an exception."""
		if registry.is_installed("crm"):
			self.skipTest("crm is installed on this bench")
		row = _row(detection.detect_all(), "crm")
		self.assertEqual(row["state"], registry.NOT_INSTALLED)
		self.assertFalse(row["eligible"])

	def test_an_installed_target_reports_version_and_entry_template(self):
		if not registry.is_installed("crm"):
			self.skipTest("crm is not installed on this bench")
		row = _row(detection.detect_all(), "crm")
		self.assertTrue(row["version"])
		self.assertTrue(row["entry_template_present"])
		self.assertTrue(row["entry_anchor_present"])
		self.assertEqual(row["root_direction"], "ltr")

	def test_an_installed_target_passes_its_signature_check(self):
		if not registry.is_installed("crm"):
			self.skipTest("crm is not installed on this bench")
		row = _row(detection.detect_all(), "crm")
		self.assertEqual(row["signature"]["rule"], registry.SIGNATURE_COMPLIANT)
		self.assertEqual(row["signature"]["physical_missing"], [])

	def test_an_adapter_without_a_visual_layer_is_planned_not_enabled(self):
		for adapter_id in ("insights", "raven"):
			row = _row(detection.detect_all(), adapter_id)
			with self.subTest(adapter_id):
				self.assertFalse(row["eligible"])
				self.assertIn(row["state"], (registry.PLANNED, registry.NOT_INSTALLED))

	def test_the_report_never_contains_an_absolute_path(self):
		for row in detection.detect_all():
			for key, value in row.items():
				for text in _strings(value):
					with self.subTest(f"{row['adapter_id']} :: {key}"):
						self.assertIsNone(ABSOLUTE_PATH.search(text), text)

	def test_the_report_mentions_no_installed_app_outside_the_registry(self):
		reported = {row["target_app"] for row in detection.detect_all()}
		self.assertEqual(reported, {a.target_app for a in registry.all_adapters().values()})


class TestDiagnosticsEndpoint(IntegrationTestCase):
	def test_the_endpoint_is_admin_only(self):
		self.assertEqual(diagnostics.ALLOWED_ROLES, ("System Manager",))

	def test_route_probe_names_the_adapter_that_would_run(self):
		result = diagnostics.route_probe("/crm/leads")
		self.assertEqual(result["adapter_id"], "crm")

	def test_route_probe_refuses_an_api_path(self):
		result = diagnostics.route_probe("/api/method/ping")
		self.assertTrue(result["ignored"])
		self.assertIsNone(result["adapter_id"])

	def test_route_probe_reports_an_unclaimed_path(self):
		result = diagnostics.route_probe("/app/sales-invoice")
		self.assertIsNone(result["adapter_id"])
		self.assertIn("no adapter", result["reason"])

	def test_warnings_are_shaped_for_the_ui(self):
		for warning in diagnostics.build_warnings(detection.detect_all()):
			with self.subTest(warning.get("adapter_id")):
				self.assertIn(warning["level"], ("error", "warning", "info"))
				self.assertTrue(warning["message"])

	def test_summary_text_is_one_line_per_adapter(self):
		lines = diagnostics.summary_text().splitlines()
		self.assertEqual(len(lines), len(registry.all_adapters()))


class TestUntestedVersionIsNeverSilent(IntegrationTestCase):
	"""An accepted untested version may run. It must never look verified."""

	def setUp(self):
		if not registry.is_installed("crm"):
			self.skipTest("crm is not installed on this bench")

	def test_detection_reports_the_mismatch_even_when_the_override_is_on(self):
		adapter = _narrow(registry.all_adapters()["crm"])
		row = detection.detect(adapter, {adapter.adapter_id: {"enabled": 1, "override_version_check": 1}})
		self.assertTrue(row["eligible"])
		self.assertEqual(row["state"], registry.VERSION_MISMATCH)

	def test_the_mismatch_is_raised_as_a_warning_the_admin_can_read(self):
		adapter = _narrow(registry.all_adapters()["crm"])
		row = detection.detect(adapter, {adapter.adapter_id: {"enabled": 1, "override_version_check": 1}})
		warnings = diagnostics.build_warnings([row])
		self.assertTrue(warnings)
		self.assertEqual(warnings[0]["level"], "warning")
		self.assertIn("9.9.9", warnings[0]["message"])

	def test_quick_state_reports_the_mismatch_for_both_switch_positions(self):
		adapter = _narrow(registry.all_adapters()["crm"])
		self.assertEqual(registry.quick_state(adapter, enabled=True), registry.VERSION_MISMATCH)
		self.assertEqual(registry.quick_state(adapter, enabled=False), registry.VERSION_MISMATCH)


class TestAppReport(IntegrationTestCase):
	"""The "مدیریت سازگاری راست‌به‌چپ" table is discovered, never hardcoded."""

	def test_every_installed_app_is_listed_once(self):
		rows = detection.app_report()
		apps = [row["app"] for row in rows]
		self.assertEqual(sorted(apps), sorted(frappe.get_installed_apps(_ensure_on_bench=True)))
		self.assertEqual(apps, sorted(apps), "the table is ordered by app name")

	def test_a_framework_host_is_reported_as_native(self):
		for app in detection.DESK_HOSTS:
			with self.subTest(app):
				row = _app_row(detection.app_report(), app)
				self.assertEqual(row["state"], registry.RTL_NATIVE)
				self.assertEqual(row["state_label"], detection.STATE_LABELS[registry.RTL_NATIVE])

	def test_an_adapter_backed_app_reports_its_adapter(self):
		if not registry.is_installed("crm"):
			self.skipTest("crm is not installed on this bench")
		row = _app_row(detection.app_report(), "crm")
		self.assertEqual(row["adapter_id"], "crm")
		self.assertEqual(row["interface"], detection.INTERFACE_SPA)
		self.assertIn(
			row["state"],
			(registry.ADAPTER_AVAILABLE, registry.ADAPTER_ENABLED, registry.VERSION_MISMATCH),
		)

	def test_an_adapter_without_a_visual_layer_reads_needs_review(self):
		for app in ("insights", "raven"):
			if not registry.is_installed(app):
				continue
			with self.subTest(app):
				row = _app_row(detection.app_report(), app)
				self.assertEqual(row["state_label"], "نیازمند بررسی")

	def test_an_app_without_an_adapter_appears_as_undefined_not_hidden(self):
		adapter_apps = {adapter.target_app for adapter in registry.all_adapters().values()}
		plain = [
			row
			for row in detection.app_report()
			if row["app"] not in adapter_apps and row["app"] not in detection.DESK_HOSTS
		]
		if not plain:
			self.skipTest("every installed app ships an adapter or is a framework host")
		for row in plain:
			with self.subTest(row["app"]):
				self.assertEqual(row["state"], registry.NO_ADAPTER)
				self.assertEqual(row["state_label"], "آداپتور تعریف نشده")
				self.assertEqual(row["adapter_id"], "")
				self.assertFalse(row["enabled"])

	def test_every_row_carries_a_persian_label_and_reason(self):
		persian = re.compile(r"[\u0600-\u06FF]")
		for row in detection.app_report():
			with self.subTest(row["app"]):
				self.assertTrue(row["state_label"].strip())
				self.assertTrue(persian.search(row["state_label"]), row["state_label"])
				self.assertTrue(row["reason_label"].strip())
				self.assertTrue(persian.search(row["reason_label"]), row["reason_label"])

	def test_the_table_never_contains_an_absolute_path(self):
		for row in detection.app_report():
			for text in _strings(row):
				with self.subTest(f"{row['app']} :: {text}"):
					self.assertIsNone(ABSOLUTE_PATH.search(text), text)


class TestCompatReport(IntegrationTestCase):
	def test_the_report_matches_the_installed_app_set(self):
		report = diagnostics.compat_report()
		self.assertEqual(len(report["apps"]), len(frappe.get_installed_apps(_ensure_on_bench=True)))

	def test_a_guest_is_refused(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				diagnostics.compat_report()
		finally:
			frappe.set_user("Administrator")


def _app_row(rows, app):
	for row in rows:
		if row["app"] == app:
			return row
	raise AssertionError(f"{app} is missing from the app report")


def _narrow(adapter):
	"""The same adapter, mapped to a version range this bench cannot satisfy."""
	from dataclasses import replace

	return replace(adapter, compatible_min="9.9.9", compatible_max="9.9.9", tested_versions=("9.9.9",))


def _row(rows, adapter_id):
	for row in rows:
		if row["adapter_id"] == adapter_id:
			return row
	raise AssertionError(f"{adapter_id} is missing from the report")


def _strings(value):
	if isinstance(value, str):
		yield value
	elif isinstance(value, dict):
		for item in value.values():
			yield from _strings(item)
	elif isinstance(value, (list, tuple, set)):
		for item in value:
			yield from _strings(item)
