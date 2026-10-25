"""Injection must be additive, idempotent and narrow.

The dangerous failure mode is not "RTL did not apply"; it is "RTL applied where
it should not". So most of these tests assert that nothing happened: on a POST,
on an error, on JSON, on another language, on an unclaimed route, on an API URL.
"""

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from werkzeug.wrappers import Request, Response

from smartprocee_erpnext_persiant.persian_rtl import inject, registry, runtime, settings
from smartprocee_erpnext_persiant.persian_rtl.adapters import base
from smartprocee_erpnext_persiant.persian_rtl.tests import helpers
from smartprocee_erpnext_persiant.persian_rtl.tests.helpers import RTLStateMixin
from smartprocee_erpnext_persiant.persian_translation.system_font import css as font_css
from smartprocee_erpnext_persiant.persian_translation.system_font import storage

CRM_HTML = (
	'<!doctype html>\n<html class="h-full" lang="en">\n<head>\n'
	'<link rel="stylesheet" href="/assets/crm/frontend/style.css">\n</head>\n'
	'<body class="sm:overscroll-y-none">\n<div id="app" class="h-full"></div>\n</body>\n</html>'
)
CRM_URL = "/assets/smartprocee_erpnext_persiant/css/rtl/crm/adapter.css"


def crm_adapter():
	return registry.all_adapters()["crm"]


class TestDocumentEdits(UnitTestCase):
	def test_root_direction_is_added_and_every_other_attribute_is_kept(self):
		updated = inject.set_root_direction(CRM_HTML, "rtl")
		self.assertIn('<html class="h-full" lang="en" dir="rtl">', updated)

	def test_lang_is_never_rewritten(self):
		"""Changing lang would change font fallback and typography inside CRM."""
		self.assertNotIn('lang="fa"', inject.set_root_direction(CRM_HTML, "rtl"))

	def test_an_existing_direction_is_replaced_not_duplicated(self):
		self.assertEqual(inject.set_root_direction('<html dir="ltr" lang="en">', "rtl"), '<html dir="rtl" lang="en">')

	def test_a_document_without_a_root_tag_is_left_alone(self):
		self.assertEqual(inject.set_root_direction("<p>hi</p>", "rtl"), "<p>hi</p>")

	def test_link_is_inserted_before_the_head_close(self):
		updated = inject.inject(CRM_HTML, crm_adapter())
		self.assertIn(CRM_URL, updated)
		self.assertLess(updated.index(CRM_URL), updated.index("</head>"))

	def test_the_adapter_stylesheet_is_cache_busted(self):
		href = inject.link_tag(crm_adapter())
		self.assertIn(CRM_URL + "?v=", href)

	def test_the_list_resize_script_is_inserted_for_crm(self):
		updated = inject.inject(CRM_HTML, crm_adapter())
		self.assertIn(crm_adapter().script_url, updated)
		self.assertLess(updated.index(crm_adapter().script_url), updated.index("</head>"))

	def test_adapter_stylesheet_loads_after_the_app_s_own_css(self):
		"""Our override layer must win the cascade, so it goes last in <head>."""
		updated = inject.inject(CRM_HTML, crm_adapter())
		self.assertLess(updated.index("/assets/crm/frontend/style.css"), updated.index(CRM_URL))

	def test_injection_is_idempotent(self):
		once = inject.inject(CRM_HTML, crm_adapter())
		self.assertEqual(inject.inject(once, crm_adapter()), once)

	def test_body_is_used_when_there_is_no_head(self):
		updated = inject.inject('<html lang="en"><body>x</body></html>', crm_adapter())
		self.assertIn(CRM_URL, updated)

	def test_exactly_two_edits_are_made_and_nothing_else_changes(self):
		adapter = crm_adapter()
		updated = inject.inject(CRM_HTML, adapter)
		payload = "\n".join(
			part
			for part in (
				inject.link_tag(adapter),
				inject.script_tag(adapter),
				inject.font_link_tag(adapter),
				inject.style_tag(adapter),
			)
			if part
		)
		reverted = updated.replace(payload + "\n", "").replace(' dir="rtl"', "")
		self.assertEqual(reverted, CRM_HTML)


class TestExclusions(UnitTestCase):
	def test_a_selector_that_could_escape_the_style_block_is_dropped(self):
		for bad in ("} body { background: red", "<script>", ".x {}", "a /* b */"):
			with self.subTest(bad):
				self.assertEqual(inject.sanitize_selector(bad), "")

	def test_a_normal_selector_survives(self):
		self.assertEqual(inject.sanitize_selector(".ql-editor"), ".ql-editor")

	def test_ltr_island_css_forces_direction_and_isolation(self):
		css = inject.exclusions_css(crm_adapter())
		self.assertIn('[dir="rtl"] .ql-editor', css)
		self.assertIn("unicode-bidi: isolate", css)

	def test_exclusions_are_scoped_to_the_rtl_document(self):
		"""Every selector of a list, not only the first, stays inside the RTL root."""
		for line in filter(None, inject.exclusions_css(crm_adapter()).splitlines()):
			selector = line.split(" {", 1)[0]
			for part in inject.split_selector_list(selector):
				self.assertTrue(part.startswith('[dir="rtl"] '), line)

	def test_every_selector_in_a_list_is_scoped(self):
		self.assertEqual(
			inject.scope_selector(".foo, .bar,.baz"),
			'[dir="rtl"] .foo, [dir="rtl"] .bar, [dir="rtl"] .baz',
		)

	def test_whitespace_and_empty_items_are_handled(self):
		self.assertEqual(
			inject.scope_selector("  .foo ,\n\t.bar  , "),
			'[dir="rtl"] .foo, [dir="rtl"] .bar',
		)

	def test_commas_inside_a_selector_are_not_split(self):
		selector = '.a:is(.b, .c) > .d::before, [data-x="1,2"] ~ .e:not(.f, .g), .h + .i'
		self.assertEqual(
			inject.split_selector_list(selector),
			['.a:is(.b, .c) > .d::before', '[data-x="1,2"] ~ .e:not(.f, .g)', ".h + .i"],
		)
		self.assertEqual(
			inject.scope_selector(selector),
			'[dir="rtl"] .a:is(.b, .c) > .d::before, '
			'[dir="rtl"] [data-x="1,2"] ~ .e:not(.f, .g), '
			'[dir="rtl"] .h + .i',
		)

	def test_an_administrator_selector_list_is_scoped_item_by_item(self):
		settings_rows = [{"selector": ".x, .y", "mode": base.LTR_ISLAND, "source": "admin"}]
		with patch.object(settings, "exclusions_for", return_value=settings_rows):
			css = inject.exclusions_css(crm_adapter())
		self.assertEqual(css, '[dir="rtl"] .x, [dir="rtl"] .y { direction: ltr; unicode-bidi: isolate; }')


class TestRuntimeGuards(RTLStateMixin, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.lang = "fa"
		_enable_crm()

	def tearDown(self):
		frappe.local.lang = "en"
		super().tearDown()

	def _call(self, path="/crm/leads", method="GET", status=200, body=CRM_HTML, content_type="text/html"):
		response = Response(body, status=status, content_type=content_type)
		request = Request.from_values(path, method=method)
		runtime.after_request(response=response, request=request)
		return response.get_data(as_text=True)

	def test_enabled_persian_get_is_injected(self):
		body = self._call()
		self.assertIn(CRM_URL, body)
		self.assertIn(crm_adapter().script_url, body)

	def test_non_persian_language_is_untouched(self):
		frappe.local.lang = "en"
		with patch.object(frappe, "get_cached_value", return_value="en"):
			self.assertEqual(self._call(), CRM_HTML)

	def test_signed_in_persian_user_is_injected_when_request_lang_is_english(self):
		frappe.local.lang = "en"
		with patch.object(frappe, "get_cached_value", return_value="fa"):
			body = self._call()
		self.assertIn(CRM_URL, body)

	def test_post_is_untouched(self):
		self.assertEqual(self._call(method="POST"), CRM_HTML)

	def test_error_response_is_untouched(self):
		self.assertEqual(self._call(status=500), CRM_HTML)

	def test_json_response_is_untouched(self):
		self.assertEqual(self._call(content_type="application/json", body='{"ok":true}'), '{"ok":true}')

	def test_unclaimed_route_is_untouched(self):
		self.assertEqual(self._call(path="/app/sales-invoice"), CRM_HTML)

	def test_api_path_is_untouched(self):
		self.assertEqual(self._call(path="/api/method/ping"), CRM_HTML)

	def test_disabled_switch_prevents_injection(self):
		_set_settings(enabled=0)
		self.assertEqual(self._call(), CRM_HTML)

	def test_disabled_adapter_prevents_injection(self):
		_set_settings(enabled=1, adapter_enabled=0)
		self.assertEqual(self._call(), CRM_HTML)

	def test_missing_request_object_is_ignored(self):
		response = Response(CRM_HTML, status=200, content_type="text/html")
		runtime.after_request(response=response, request=None)
		self.assertEqual(response.get_data(as_text=True), CRM_HTML)


class TestEligibility(RTLStateMixin, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		_enable_crm()

	def test_an_unimplemented_visual_adapter_is_never_eligible(self):
		adapter = registry.all_adapters()["insights"]
		eligible, reason = inject.is_eligible(adapter, {"insights": {"enabled": 1}})
		self.assertFalse(eligible)
		self.assertIn("visual adapter", reason)

	def test_a_version_outside_the_range_needs_an_explicit_override(self):
		adapter = _narrow_adapter()
		eligible, reason = inject.is_eligible(adapter, {adapter.adapter_id: {"enabled": 1}})
		self.assertFalse(eligible)
		self.assertIn("outside", reason)

	def test_the_override_switch_makes_an_untested_version_eligible(self):
		adapter = _narrow_adapter()
		eligible, reason = inject.is_eligible(
			adapter, {adapter.adapter_id: {"enabled": 1, "override_version_check": 1}}
		)
		self.assertTrue(eligible, reason)

	def test_a_disabled_target_app_is_never_a_silent_success(self):
		adapter = registry.all_adapters()["insights"]
		adapter = _retarget(adapter, "definitely_not_installed")
		eligible, reason = inject.is_eligible(
			adapter, {adapter.adapter_id: {"enabled": 1, "override_version_check": 1}}
		)
		self.assertFalse(eligible)
		self.assertIn("not installed", reason)


class TestSiteStateIsRestored(RTLStateMixin, IntegrationTestCase):
	"""Regression guard for the leak that used to follow this module.

	The two classes above switch the switch on. This one proves the captured state
	is written back, and it is the reason a full `bench run-tests` cannot leave the
	test site RTL-enabled for the next run.
	"""

	def test_capturing_and_restoring_puts_the_switch_back(self):
		before = helpers.capture()
		self.assertIsNotNone(before, "the Single must exist on a migrated site")

		_set_settings(enabled=1, adapter_enabled=1, override=1)
		self.assertTrue(helpers.is_enabled())

		helpers.restore(before)
		self.assertEqual(helpers.is_enabled(), bool(before["enabled"]))
		after = helpers.capture()
		self.assertEqual(after["enabled"], before["enabled"])
		self.assertEqual(after["adapters"], before["adapters"])

	def test_a_test_restore_point_is_removed_again(self):
		from smartprocee_erpnext_persiant.persian_translation import snapshots

		existing = helpers.snapshot_names()
		created = snapshots.capture(snapshots.MANUAL, "__PTM_STATE_TEST__")["name"]
		self.assertIn(created, helpers.snapshot_names())

		helpers.drop_new_snapshots(existing)

		self.assertNotIn(created, helpers.snapshot_names())


FONT_LINK = "data-persian-rtl-font"


def _faces(name="ptm-test-a"):
	return [
		{
			"file_url": f"/files/persian-font-{name}.woff2",
			"font_format": "WOFF2",
			"css_weight": 400,
			"font_style": "normal",
			"font_stretch": "normal",
			"enabled": 1,
		}
	]


class TestAdapterFont(RTLStateMixin, IntegrationTestCase):
	"""A standalone app keeps its own `<html lang="en">`, so the Desk font rules
	never reach it. The adapter links the generated family through the direction
	scope instead -- only when the administrator opted the adapter in, and only
	while a Persian font is active."""

	def setUp(self):
		super().setUp()
		self._font_files = storage.read_active_css()
		self.addCleanup(self._restore_font_files)
		frappe.local.lang = "fa"
		_enable_crm()

	def _restore_font_files(self):
		desk_css, adapter_css = self._font_files
		if desk_css is None:
			storage.clear_active_css()
		else:
			storage.write_active_css(desk_css, adapter_css)
		frappe.local._persian_adapter_font_url = None
		frappe.local.lang = "en"

	def _activate(self, family="Test A", name="ptm-test-a"):
		storage.write_active_css("/* desk */", font_css.render_adapter_css(family, _faces(name)))
		frappe.local._persian_adapter_font_url = None

	def _call(self, path="/crm/leads"):
		response = Response(CRM_HTML, status=200, content_type="text/html")
		request = Request.from_values(path, method="GET")
		runtime.after_request(response=response, request=request)
		return response.get_data(as_text=True)

	def _font_href(self, body):
		import re

		found = re.findall(r'<link rel="stylesheet" href="([^"]+)" data-persian-rtl-font="1">', body)
		self.assertEqual(len(found), 1, body)
		return found[0]

	def test_the_option_is_off_by_default_so_crm_keeps_its_own_font(self):
		self._activate()
		self.assertFalse(settings.adapter_states()["crm"]["use_system_font"])
		body = self._call()
		self.assertIn(CRM_URL, body, "RTL itself still applies")
		self.assertNotIn(FONT_LINK, body)

	def test_with_the_option_on_the_active_font_is_linked_once(self):
		self._activate()
		_set_settings(use_system_font=1)
		href = self._font_href(self._call())
		self.assertTrue(href.startswith(f"/files/{storage.ADAPTER_CSS}?v="))

	def test_with_no_custom_family_no_font_is_linked(self):
		"""No font is shipped, so CRM keeps its own font while RTL still applies."""
		storage.clear_active_css()
		frappe.local._persian_adapter_font_url = None
		_set_settings(use_system_font=1)
		body = self._call()
		self.assertIn(CRM_URL, body, "RTL itself still applies")
		self.assertNotIn(FONT_LINK, body)
		self.assertNotIn("/assets/smartprocee_erpnext_persiant/fonts/", body)

	def test_the_option_survives_save_and_reload_and_drives_injection(self):
		self._activate()
		doc = frappe.get_doc("Persian RTL Settings")
		next(row for row in doc.adapters if row.adapter_id == "crm").use_system_font = 1
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("Persian RTL Settings", "Persian RTL Settings")

		reloaded = {row.adapter_id: row for row in frappe.get_doc("Persian RTL Settings").adapters}
		self.assertEqual(reloaded["crm"].use_system_font, 1)
		self.assertEqual(reloaded["crm"].enabled, 1)
		self.assertTrue(settings.adapter_states()["crm"]["use_system_font"])
		self.assertIn(FONT_LINK, self._call())

		doc = frappe.get_doc("Persian RTL Settings")
		next(row for row in doc.adapters if row.adapter_id == "crm").use_system_font = 0
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("Persian RTL Settings", "Persian RTL Settings")
		self.assertNotIn(FONT_LINK, self._call())

	def test_a_non_persian_session_gets_nothing(self):
		self._activate()
		_set_settings(use_system_font=1)
		frappe.local.lang = "en"
		self.assertEqual(self._call(), CRM_HTML)

	def test_a_font_change_reaches_crm_with_a_new_cache_key(self):
		self._activate("Test A", "ptm-test-a")
		_set_settings(use_system_font=1)
		first = self._font_href(self._call())
		self._activate("Test B", "ptm-test-b")
		second = self._font_href(self._call())
		self.assertNotEqual(first, second)
		self.assertIn("Persianizer Test B", Path(frappe.get_site_path("public", "files", storage.ADAPTER_CSS)).read_text())

	def test_reverting_to_the_default_font_switches_crm_back_to_its_own_font(self):
		self._activate()
		_set_settings(use_system_font=1)
		self.assertIn(storage.ADAPTER_CSS, self._font_href(self._call()))
		storage.clear_active_css()
		frappe.local._persian_adapter_font_url = None
		body = self._call()
		self.assertIn(CRM_URL, body, "RTL itself still applies")
		self.assertNotIn(FONT_LINK, body)

	def test_switching_the_option_or_the_adapter_off_restores_the_original(self):
		self._activate()
		_set_settings(use_system_font=1)
		self.assertIn(FONT_LINK, self._call())
		_set_settings(use_system_font=0)
		self.assertNotIn(FONT_LINK, self._call())
		_set_settings(adapter_enabled=0, use_system_font=1)
		self.assertEqual(self._call(), CRM_HTML)

	def test_an_adapter_without_support_never_links_the_font(self):
		insights = registry.all_adapters()["insights"]
		self.assertFalse(insights.supports_system_font)
		self.assertFalse(inject.uses_system_font(insights, {"insights": {"use_system_font": True}}))
		self.assertEqual(inject.font_link_tag(insights, {"insights": {"use_system_font": True}}), "")

	def test_an_unsupported_adapter_is_forced_off_without_touching_its_switch(self):
		doc = frappe.get_doc("Persian RTL Settings")
		for row in doc.adapters:
			if row.adapter_id in ("insights", "raven"):
				row.enabled = 1
				row.use_system_font = 1
				row.supports_system_font = 1
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("Persian RTL Settings", "Persian RTL Settings")
		rows = {row.adapter_id: row for row in frappe.get_doc("Persian RTL Settings").adapters}
		self.assertEqual(rows["crm"].supports_system_font, 1)
		for adapter_id in ("insights", "raven"):
			with self.subTest(adapter_id):
				self.assertEqual(rows[adapter_id].supports_system_font, 0)
				self.assertEqual(rows[adapter_id].use_system_font, 0)
				self.assertEqual(rows[adapter_id].enabled, 1, "فعال is independent of font support")
				self.assertFalse(settings.adapter_states()[adapter_id]["use_system_font"])


class TestFontOptionControl(UnitTestCase):
	"""The option must stay a visible control on every row, never vanish on edit."""

	def setUp(self):
		self.fields = {df.fieldname: df for df in frappe.get_meta("Persian RTL Adapter").fields}

	def test_the_control_is_never_hidden_by_a_dependency(self):
		"""Frappe's grid hides a `depends_on` field when the row enters edit mode."""
		df = self.fields["use_system_font"]
		self.assertFalse(df.depends_on)
		self.assertTrue(df.in_list_view)
		self.assertEqual(df.read_only_depends_on, "eval:!doc.supports_system_font")

	def test_support_is_a_read_only_mirror(self):
		self.assertTrue(self.fields["supports_system_font"].read_only)

	def test_the_enabled_switch_does_not_depend_on_font_support(self):
		df = self.fields["enabled"]
		self.assertFalse(df.depends_on)
		self.assertFalse(df.read_only_depends_on)
		self.assertFalse(df.read_only)

	def test_the_form_labels_unsupported_rows(self):
		script = Path(
			frappe.get_app_path(
				"smartprocee_erpnext_persiant",
				"persian_rtl",
				"doctype",
				"persian_rtl_settings",
				"persian_rtl_settings.js",
			)
		).read_text(encoding="utf-8")
		self.assertIn('grid.update_docfield_property("use_system_font", "formatter"', script)
		self.assertIn('fieldtype: "HTML"', script)
		self.assertIn("پشتیبانی نمی‌شود", script)


class TestAdapterFontRules(UnitTestCase):
	"""The adapter font must not reach icons, code or anything naming its own family."""

	def setUp(self):
		self.css = font_css.render_adapter_css("Test A", _faces())

	def test_rules_hang_off_the_rtl_root_through_one_variable(self):
		self.assertIn('html[dir="rtl"] {\n\t--persianizer-font-stack: "Persianizer Test A"', self.css)
		self.assertIn("font-family: var(--persianizer-font-stack);", self.css)
		self.assertNotIn('html[lang="fa"]', self.css)

	def test_only_the_root_and_the_app_s_own_font_utilities_are_targeted(self):
		self.assertIn('html[dir="rtl"],\nhtml[dir="rtl"] .font-sans,\nhtml[dir="rtl"] [data-sonner-toaster] {', self.css)

	def test_no_blanket_or_forced_rule(self):
		self.assertNotIn("!important", self.css)
		self.assertNotIn("*", self.css)

	def test_monospace_and_icon_selectors_are_left_alone(self):
		for selector in ("code", "pre", "kbd", "samp", ".font-mono", ".ace_editor", "icon", "svg", "canvas"):
			with self.subTest(selector):
				self.assertNotIn(selector, self.css.split("@font-face")[-1].split("}", 1)[1])


def _narrow_adapter():
	return _retarget(registry.all_adapters()["crm"], "crm", low="9.9.9", high="9.9.9")


def _retarget(adapter, app, low=None, high=None):
	from dataclasses import replace

	updates = {"target_app": app}
	if low:
		updates.update({"compatible_min": low, "compatible_max": high, "tested_versions": (low,)})
	return replace(adapter, **updates)


def _set_settings(enabled=1, adapter_enabled=1, override=1, use_system_font=0):
	doc = frappe.get_doc("Persian RTL Settings")
	doc.enabled = enabled
	for row in doc.adapters:
		if row.adapter_id == "crm":
			row.enabled = adapter_enabled
			row.override_version_check = override
			row.use_system_font = use_system_font
	doc.save(ignore_permissions=True)
	frappe.clear_document_cache("Persian RTL Settings", "Persian RTL Settings")


def _enable_crm():
	settings.sync_from_registry()
	_set_settings(enabled=1, adapter_enabled=1)
