"""Navigation and install/uninstall lifecycle.

`فارسی‌ساز` stays on the Desktop Icon, the Apps screen and the navbar. It must
not appear in the right Workspace Sidebar. Translation Manager and Font Manager
remain reachable as System Manager pages. The empty "Persian Translation"
sidebar was an obsolete artifact and must stay gone.
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

	def test_the_home_icon_fixture_is_a_top_level_external_link(self):
		path = Path(frappe.get_app_path(APP_NAME, "desktop_icon")) / f"{MENU_LABEL}.json"
		fixture = json.loads(path.read_text(encoding="utf-8"))
		self.assertEqual(fixture["link_type"], "External")
		self.assertEqual(fixture["link"], "/app/persian-translation-manager")
		self.assertFalse(fixture.get("parent_icon"))
		self.assertEqual(fixture["standard"], 1)

	def test_apps_screen_entry_uses_the_permission_hook(self):
		entries = [entry for entry in hooks.add_to_apps_screen if entry["name"] == APP_NAME]
		self.assertEqual(len(entries), 1)
		entry = entries[0]
		self.assertEqual(entry["title"], MENU_LABEL)
		self.assertEqual(entry["route"], hooks.app_home)
		from smartprocee_erpnext_persiant.permissions import has_app_permission

		self.assertTrue(has_app_permission())

	def test_navbar_item_is_registered_exactly_once(self):
		self.assertEqual(navbar_labels().count(MENU_LABEL), 1)

	def test_navbar_sync_is_idempotent(self):
		sync_standard_items()
		sync_standard_items()
		self.assertEqual(navbar_labels().count(MENU_LABEL), 1)


class TestInstallLifecycle(IntegrationTestCase):
	def test_repeated_install_steps_do_not_duplicate_artifacts(self):
		sync_standard_items()
		sync_standard_items()
		self.assertEqual(navbar_labels().count(MENU_LABEL), 1)
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
