"""The registry is the single source of truth, so it must be portable and strict.

Two things are checked here that matter more than the individual adapters:

* route matching and the ignore list behave exactly as documented, because they
  are the only thing standing between a normal request and an unwanted rewrite
* no adapter declares anything machine specific -- no absolute path, no hashed
  frontend asset name, no site name -- so the same code runs on Server A, B or C
"""

import re

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from smartprocee_erpnext_persiant.persian_rtl import registry, settings
from smartprocee_erpnext_persiant.persian_rtl.tests.helpers import RTLStateMixin
from smartprocee_erpnext_persiant.persian_rtl.adapters.base import (
	STANDALONE,
	Adapter,
	Exclusion,
)

ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]|^/home/|^/Users/|^/var/|^/opt/|^\\\\")
HASHED_ASSET = re.compile(r"[-.][A-Za-z0-9_]{8}\.(js|css|mjs)")


class TestRouteMatching(UnitTestCase):
	def test_wildcard_covers_route_and_children(self):
		for path in ("/crm", "/crm/", "/crm/leads", "/crm/leads/1"):
			self.assertTrue(registry.route_matches("/crm/*", path), path)

	def test_wildcard_does_not_leak_to_a_similar_prefix(self):
		for path in ("/crmx", "/crm-old", "/", "/desk"):
			self.assertFalse(registry.route_matches("/crm/*", path), path)

	def test_exact_pattern_matches_only_itself(self):
		self.assertTrue(registry.route_matches("/raven", "/raven"))
		self.assertFalse(registry.route_matches("/raven", "/raven/channel"))

	def test_query_and_fragment_are_ignored(self):
		self.assertTrue(registry.route_matches("/crm/*", "/crm/leads?filters=%7B%7D"))
		self.assertTrue(registry.route_matches("/crm/*", "/crm/leads#top"))

	def test_empty_inputs_never_match(self):
		self.assertFalse(registry.route_matches("", "/crm"))
		self.assertFalse(registry.route_matches("/crm/*", ""))


class TestIgnoreList(UnitTestCase):
	def test_api_and_assets_are_never_touched(self):
		for path in ("/api/method/ping", "/assets/crm/frontend/index.js", "/files/x.pdf", "/socket.io/"):
			self.assertTrue(registry.is_path_ignored(path), path)

	def test_normal_routes_are_allowed(self):
		for path in ("/crm/leads", "/app/sales-invoice", "/raven/channel/general"):
			self.assertFalse(registry.is_path_ignored(path), path)


class TestAdapterContract(UnitTestCase):
	def test_adapters_are_discovered(self):
		found = registry.all_adapters()
		self.assertIn("crm", found)
		self.assertIn("insights", found)
		self.assertIn("raven", found)

	def test_ids_are_unique_and_match_their_key(self):
		for key, adapter in registry.all_adapters().items():
			self.assertEqual(key, adapter.adapter_id)

	def test_required_metadata_is_present(self):
		for adapter in registry.all_adapters().values():
			with self.subTest(adapter.adapter_id):
				self.assertTrue(adapter.title)
				self.assertTrue(adapter.target_app)
				self.assertTrue(adapter.routes)
				self.assertTrue(adapter.tested_versions)
				self.assertTrue(adapter.compatible_min)
				self.assertTrue(adapter.compatible_max)

	def test_visual_standalone_adapters_ship_a_stylesheet(self):
		for adapter in registry.all_adapters().values():
			if adapter.hosting == STANDALONE and adapter.visual_ready:
				self.assertTrue(adapter.stylesheet, adapter.adapter_id)

	def test_phase_one_limits_the_visual_layer_to_crm(self):
		visual = {a.adapter_id for a in registry.all_adapters().values() if a.visual_ready}
		self.assertEqual(visual, {"crm"})

	def test_missing_required_field_is_rejected(self):
		with self.assertRaises(ValueError):
			Adapter(
				adapter_id="broken",
				title="Broken",
				target_app="broken",
				entry_template="broken/www/broken.html",
				hosting=STANDALONE,
				routes=(),
				tested_versions=("1.0.0",),
				compatible_min="1.0.0",
				compatible_max="1.0.9",
			)

	def test_unknown_exclusion_mode_is_rejected(self):
		with self.assertRaises(ValueError):
			Exclusion(label="x", selector=".x", mode="Mirror Everything")


class TestPortability(UnitTestCase):
	def test_no_adapter_declares_a_machine_specific_path(self):
		for adapter in registry.all_adapters().values():
			for value in (adapter.entry_template, adapter.stylesheet, adapter.asset_url):
				with self.subTest(f"{adapter.adapter_id} :: {value}"):
					self.assertFalse(ABSOLUTE_PATH.search(value or ""), value)

	def test_no_adapter_uses_a_hashed_asset_name(self):
		for adapter in registry.all_adapters().values():
			with self.subTest(adapter.adapter_id):
				self.assertIsNone(HASHED_ASSET.search(adapter.stylesheet or ""))
				self.assertIsNone(HASHED_ASSET.search(adapter.entry_template or ""))

	def test_exclusion_selectors_carry_no_paths(self):
		for adapter in registry.all_adapters().values():
			for item in adapter.exclusions:
				with self.subTest(f"{adapter.adapter_id} :: {item.selector}"):
					self.assertFalse(ABSOLUTE_PATH.search(item.selector))
					self.assertNotIn("\\", item.selector)


class TestVersionState(IntegrationTestCase):
	def test_installed_app_reports_a_version(self):
		self.assertTrue(registry.installed_version("frappe"))

	def test_missing_app_is_reported_as_not_installed(self):
		self.assertEqual(registry.version_state(_fake_adapter("definitely_not_installed")), registry.NOT_INSTALLED)

	def test_version_inside_the_range_is_supported(self):
		adapter = _fake_adapter("frappe", low="0.0.1", high="999.0.0")
		self.assertEqual(registry.version_state(adapter), registry.SUPPORTED)

	def test_version_outside_the_range_is_a_mismatch(self):
		adapter = _fake_adapter("frappe", low="999.0.0", high="999.9.9")
		self.assertEqual(registry.version_state(adapter), registry.MISMATCH)

	def test_a_patch_release_stays_inside_the_range(self):
		"""The point of a range: 1.85.1 -> 1.85.2 must not disable the adapter."""
		low = registry.parse_version("1.85.0")
		high = registry.parse_version("1.85.99")
		self.assertTrue(low <= registry.parse_version("1.85.1") <= high)
		self.assertTrue(low <= registry.parse_version("1.85.2") <= high)
		self.assertFalse(low <= registry.parse_version("1.86.0") <= high)


ADMIN_FIELDS = ("enabled", "override_version_check", "use_system_font", "admin_notes")
DECIDED = {
	"crm": {"enabled": 1, "override_version_check": 1, "use_system_font": 1, "admin_notes": "crm note"},
	"insights": {"enabled": 0, "override_version_check": 0, "use_system_font": 0, "admin_notes": "insights note"},
	"raven": {"enabled": 1, "override_version_check": 1, "use_system_font": 0, "admin_notes": ""},
}


class TestRegistrySyncKeepsAdminState(RTLStateMixin, IntegrationTestCase):
	"""`after_migrate` refreshes what the registry owns and nothing the administrator owns."""

	def setUp(self):
		super().setUp()
		settings.sync_from_registry()
		for adapter_id, values in DECIDED.items():
			frappe.db.set_value(settings.ADAPTER_DOCTYPE, self._row_name(adapter_id), dict(values))
		frappe.clear_document_cache(settings.SETTINGS_DOCTYPE, settings.SETTINGS_DOCTYPE)

	def _row_name(self, adapter_id):
		return frappe.db.get_value(
			settings.ADAPTER_DOCTYPE, {"parent": settings.SETTINGS_DOCTYPE, "adapter_id": adapter_id}
		)

	def _decisions(self):
		rows = frappe.get_all(
			settings.ADAPTER_DOCTYPE,
			filters={"parent": settings.SETTINGS_DOCTYPE},
			fields=["adapter_id", *ADMIN_FIELDS],
		)
		return {
			row.adapter_id: {field: row[field] or (0 if field != "admin_notes" else "") for field in ADMIN_FIELDS}
			for row in rows
		}

	def test_sync_keeps_every_decision_and_is_idempotent(self):
		self.assertEqual(self._decisions(), DECIDED)
		for _ in range(2):
			settings.sync_from_registry()
			self.assertEqual(self._decisions(), DECIDED)

	def test_the_after_migrate_hooks_keep_every_decision(self):
		hooks = frappe.get_hooks("after_migrate", app_name="smartprocee_erpnext_persiant")
		self.assertIn("smartprocee_erpnext_persiant.persian_rtl.settings.sync_from_registry", hooks)
		for _ in range(2):
			for method in hooks:
				frappe.get_attr(method)()
			frappe.clear_cache()
			self.assertEqual(self._decisions(), DECIDED)
			self.assertEqual(
				{key: value["enabled"] for key, value in settings.adapter_states().items()},
				{key: bool(value["enabled"]) for key, value in DECIDED.items()},
			)

	def test_registry_columns_are_refreshed(self):
		name = self._row_name("insights")
		frappe.db.set_value(
			settings.ADAPTER_DOCTYPE,
			name,
			{"title": "stale", "detected_version": "0.0.0", "supports_system_font": 1, "use_system_font": 1},
		)
		settings.sync_from_registry()
		row = frappe.db.get_value(
			settings.ADAPTER_DOCTYPE,
			name,
			["title", "detected_version", "supports_system_font", "use_system_font", "enabled"],
			as_dict=True,
		)
		self.assertEqual(row.title, registry.all_adapters()["insights"].title)
		self.assertEqual(row.detected_version, registry.installed_version("insights"))
		self.assertEqual((row.supports_system_font, row.use_system_font), (0, 0))
		self.assertEqual(row.enabled, 0)

	def test_a_missing_row_comes_back_without_touching_the_others(self):
		original = self._rtl_state["adapters"][self._row_name("raven")]
		self.addCleanup(
			lambda: frappe.db.set_value(settings.ADAPTER_DOCTYPE, self._row_name("raven"), dict(original))
		)
		frappe.db.delete(settings.ADAPTER_DOCTYPE, {"parent": settings.SETTINGS_DOCTYPE, "adapter_id": "raven"})
		frappe.clear_document_cache(settings.SETTINGS_DOCTYPE, settings.SETTINGS_DOCTYPE)
		settings.sync_from_registry()
		decisions = self._decisions()
		self.assertEqual(decisions["crm"], DECIDED["crm"])
		self.assertEqual(decisions["insights"], DECIDED["insights"])
		self.assertEqual(decisions["raven"]["enabled"], 0, "a new row starts switched off")


def _fake_adapter(app: str, low: str = "1.0.0", high: str = "1.0.0") -> Adapter:
	return Adapter(
		adapter_id=f"probe-{app}",
		title="Probe",
		target_app=app,
		entry_template=f"{app}/www/{app}.html",
		hosting=STANDALONE,
		routes=(f"/{app}/*",),
		tested_versions=(low,),
		compatible_min=low,
		compatible_max=high,
		visual_ready=False,
	)
