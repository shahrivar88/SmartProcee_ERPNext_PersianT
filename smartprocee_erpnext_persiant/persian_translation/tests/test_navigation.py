"""Navigation and install/uninstall lifecycle.

`فارسی‌ساز` stays on the Desktop Icon. It must not appear on the Apps screen,
the header Apps switcher, or the navbar. Opening the home icon must show the
contextual Sidebar. Persian RTL is code-only so the Modules switcher stays
hidden. The empty "Persian Translation" Workspace Sidebar must stay gone.
"""

import json
from pathlib import Path

import frappe
from frappe.core.doctype.navbar_settings.navbar_settings import sync_standard_items
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant import hooks
from smartprocee_erpnext_persiant.install import (
	delete_legacy_external_icon,
	remove_desk_navigation,
	restore_displaced_translations,
)
APP_NAME = "smartprocee_erpnext_persiant"
MENU_LABEL = "فارسی‌ساز"
LEGACY_SIDEBAR = "Persian Translation"
ICON = "Desktop Icon"
RTL_DOCTYPE = "Persian RTL Settings"


def navbar_labels() -> list[str]:
	return [row.item_label for row in frappe.get_single("Navbar Settings").settings_dropdown]


class TestPersianSidebar(IntegrationTestCase):
	def test_the_app_ships_no_workspace_sidebar(self):
		filters = {"app": APP_NAME} if frappe.db.has_column("Workspace Sidebar", "app") else {"name": MENU_LABEL}
		self.assertEqual(frappe.get_all("Workspace Sidebar", filters=filters, pluck="name"), [])
		self.assertFalse(frappe.db.exists("Workspace Sidebar", MENU_LABEL))

	def test_the_sidebar_fixture_is_not_shipped(self):
		path = Path(frappe.get_app_path(APP_NAME, "workspace_sidebar")) / f"{MENU_LABEL}.json"
		self.assertFalse(path.exists())

	def test_the_rtl_settings_page_exists_and_is_system_manager_only(self):
		self.assertTrue(frappe.db.exists("DocType", RTL_DOCTYPE))
		doc = frappe.get_doc("DocType", RTL_DOCTYPE)
		self.assertTrue(doc.issingle)
		self.assertEqual([row.role for row in doc.permissions], ["System Manager"])

	def test_the_sidebar_pages_exist_and_are_system_manager_only(self):
		for route in ("persian-translation-manager", "persian-system-font-manager"):
			self.assertTrue(frappe.db.exists("Page", route), route)
		page = frappe.get_doc("Page", "persian-translation-manager")
		self.assertEqual([row.role for row in page.roles], ["System Manager"])

	def test_no_empty_legacy_sidebar_is_left_behind(self):
		self.assertFalse(frappe.db.exists("Workspace Sidebar", LEGACY_SIDEBAR))

	def test_the_legacy_sidebar_patch_removes_only_an_empty_owned_sidebar(self):
		from smartprocee_erpnext_persiant.patches.v1_2 import remove_legacy_module_sidebar as patch

		self.assertEqual(patch.LEGACY_SIDEBAR, LEGACY_SIDEBAR)
		self.assertEqual(patch.CURRENT_SIDEBAR, MENU_LABEL)
		# Running it on an already clean site must be a no-op.
		patch.execute()
		self.assertFalse(frappe.db.exists("Workspace Sidebar", LEGACY_SIDEBAR))

	def test_the_sidebar_removal_patch_deletes_this_app_sidebar_only(self):
		from smartprocee_erpnext_persiant.patches.v1_2 import remove_persianizer_workspace_sidebar as patch

		patch.execute()
		self.assertFalse(frappe.db.exists("Workspace Sidebar", MENU_LABEL))
		self.assertFalse(frappe.db.exists("Workspace Sidebar", LEGACY_SIDEBAR))


class TestDeskEntryPoints(IntegrationTestCase):
	def test_desktop_icon_points_at_the_manager_page(self):
		from smartprocee_erpnext_persiant.desk_icon import HOME_LINK, PAGE_ROUTE, ensure_home_icon

		ensure_home_icon()
		icon = frappe.get_doc(ICON, MENU_LABEL)
		self.assertEqual(icon.label, MENU_LABEL)
		self.assertIn(icon.link_type, ("Page", "External"))
		if icon.link_type == "Page":
			self.assertEqual(icon.link_to, PAGE_ROUTE)
		self.assertEqual(icon.link, HOME_LINK)
		self.assertFalse(icon.parent_icon)
		self.assertEqual(icon.standard, 1)
		self.assertFalse(icon.hidden)
		self.assertEqual([row.role for row in icon.roles], ["System Manager"])
		self.assertFalse(frappe.db.exists("Workspace Sidebar", MENU_LABEL))
		if frappe.get_meta(ICON).has_field("icon_type"):
			options = (frappe.get_meta(ICON).get_field("icon_type").options or "").split("\n")
			if "Link" in options:
				self.assertEqual(icon.icon_type, "Link")

	def test_the_home_icon_fixture_is_a_top_level_external_link(self):
		path = Path(frappe.get_app_path(APP_NAME, "desktop_icon")) / f"{MENU_LABEL}.json"
		fixture = json.loads(path.read_text(encoding="utf-8"))
		self.assertEqual(fixture["link_type"], "External")
		self.assertEqual(fixture["link"], "/app/persian-translation-manager")
		self.assertFalse(fixture.get("parent_icon"))
		self.assertEqual(fixture["standard"], 1)

	def test_the_app_is_not_on_the_apps_screen(self):
		self.assertFalse(getattr(hooks, "add_to_apps_screen", None))

	def test_navbar_item_is_not_registered(self):
		from smartprocee_erpnext_persiant.install import remove_navbar_item

		remove_navbar_item()
		self.assertEqual(navbar_labels().count(MENU_LABEL), 0)

	def test_navbar_sync_does_not_bring_the_item_back(self):
		from smartprocee_erpnext_persiant.install import remove_navbar_item

		remove_navbar_item()
		sync_standard_items()
		sync_standard_items()
		self.assertEqual(navbar_labels().count(MENU_LABEL), 0)

	def test_only_the_rtl_module_is_code_only(self):
		self.assertEqual(set(hooks.code_only_modules), {"Persian RTL"})
		try:
			from frappe.desk.doctype.sidebar.sidebar import get_navigable_modules
			from frappe.utils.modules import get_code_only_modules
		except ImportError:
			return
		code_only = get_code_only_modules()
		self.assertNotIn("Persian Translation", code_only)
		self.assertIn("Persian RTL", code_only)
		navigable = get_navigable_modules()
		self.assertIn("Persian Translation", navigable)
		self.assertNotIn("Persian RTL", navigable)

	def test_the_app_ships_the_contextual_sidebar(self):
		path = Path(frappe.get_app_path(APP_NAME, "persian_translation", "sidebar", MENU_LABEL)) / f"{MENU_LABEL}.json"
		self.assertTrue(path.exists(), path)
		fixture = json.loads(path.read_text(encoding="utf-8"))
		self.assertEqual(fixture["module"], "Persian Translation")
		self.assertEqual(fixture["title"], MENU_LABEL)
		labels = [row["label"] for row in fixture["items"]]
		self.assertEqual(
			labels,
			["مدیریت ترجمه فارسی", "مدیریت فونت سیستم", "سازگاری راست‌به‌چپ"],
		)
		self.assertFalse((Path(frappe.get_app_path(APP_NAME)) / "persian_rtl" / "sidebar").exists())


class TestInstallLifecycle(IntegrationTestCase):
	def test_repeated_install_steps_do_not_duplicate_artifacts(self):
		from smartprocee_erpnext_persiant.install import remove_navbar_item

		remove_navbar_item()
		sync_standard_items()
		sync_standard_items()
		self.assertEqual(navbar_labels().count(MENU_LABEL), 0)
		self.assertEqual(frappe.db.count("Persian Font Family", {"source": "Bundled"}), 0)
		self.assertEqual(frappe.db.count(ICON, {"name": MENU_LABEL}), 1)
		if frappe.db.has_column("Workspace Sidebar", "app"):
			self.assertEqual(frappe.db.count("Workspace Sidebar", {"app": APP_NAME}), 0)
		self.assertFalse(frappe.db.exists("Workspace Sidebar", MENU_LABEL))

	def test_install_does_not_create_a_persianizer_sidebar(self):
		self.assertFalse(frappe.db.exists("Workspace Sidebar", MENU_LABEL))


class TestUninstallCleanup(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.clear_cache)

	def test_remove_desk_navigation_clears_every_artifact_of_this_app(self):
		remove_desk_navigation()
		self.assertFalse(frappe.db.exists("Workspace Sidebar", MENU_LABEL))
		self.assertFalse(frappe.db.exists("Workspace Sidebar", LEGACY_SIDEBAR))
		self.assertFalse(frappe.db.exists(ICON, MENU_LABEL))
		self.assertNotIn(MENU_LABEL, navbar_labels())
		if frappe.db.exists("DocType", "Sidebar") and frappe.db.table_exists("Sidebar"):
			self.assertFalse(frappe.db.exists("Sidebar", MENU_LABEL))
			self.assertEqual(
				frappe.get_all(
					"Sidebar",
					filters={"module": ["in", ["Persian Translation", "Persian RTL"]]},
					pluck="name",
				),
				[],
			)
		# Nothing that belongs to Frappe or another app is touched.
		self.assertTrue(frappe.db.exists(ICON, "Framework"))
		self.assertTrue(frappe.db.exists(ICON, "System"))
		self.assertTrue(navbar_labels())

	def test_legacy_external_shortcut_is_removed(self):
		icon = frappe.get_doc(
			{
				"doctype": ICON,
				"label": "Old Persianizer Shortcut",
				"link_type": "External",
				"link": "/app/persian-translation-manager",
				"standard": 0,
			}
		).insert()
		delete_legacy_external_icon()
		self.assertFalse(frappe.db.exists(ICON, icon.name))

	def test_restore_displaced_translations_repairs_a_missing_row(self):
		from smartprocee_erpnext_persiant.persian_translation.tests.helpers import MARKER

		source = f"{MARKER} RESTORED"
		backup = frappe.get_doc(
			{
				"doctype": "Persian Translation Backup",
				"language": "fa",
				"source_text": source,
				"translated_text": "بازگردانده شد",
				"context": "",
			}
		).insert()
		self.addCleanup(self._drop_restored, source)
		restore_displaced_translations()
		self.assertEqual(
			frappe.db.get_value(
				"Translation", {"language": "fa", "source_text": source, "context": ""}, "translated_text"
			),
			"بازگردانده شد",
		)
		self.assertTrue(frappe.db.exists("Persian Translation Backup", backup.name))

	@staticmethod
	def _drop_restored(source):
		for name in frappe.get_all(
			"Translation", filters={"source_text": source}, pluck="name", limit_page_length=0
		):
			frappe.delete_doc("Translation", name, force=1)
		for name in frappe.get_all(
			"Persian Translation Backup", filters={"source_text": source}, pluck="name", limit_page_length=0
		):
			frappe.delete_doc("Persian Translation Backup", name, force=1)
