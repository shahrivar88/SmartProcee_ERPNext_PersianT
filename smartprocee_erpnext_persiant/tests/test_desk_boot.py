"""Desk boot translates display labels only, and only for a Persian session."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant.desk_boot import apply_boot_display_translations


class TestDeskBootTranslations(IntegrationTestCase):
	def test_persian_session_translates_dock_titles_not_link_to(self):
		bootinfo = {
			"module_sidebars": {"accounts": {"label": "Accounts", "module": "Accounts"}},
			"app_data": [
				{
					"title": "ERPNext",
					"dock": [{"title": "Selling", "label": "Buying", "link_to": "Stock"}],
				}
			],
		}
		with patch.object(frappe.local, "lang", "fa"), patch(
			"smartprocee_erpnext_persiant.desk_boot._",
			side_effect=lambda value: f"FA:{value}",
		):
			apply_boot_display_translations(bootinfo)
		self.assertEqual(bootinfo["module_sidebars"]["accounts"]["label"], "FA:Accounts")
		self.assertEqual(bootinfo["module_sidebars"]["accounts"]["module"], "Accounts")
		self.assertEqual(bootinfo["app_data"][0]["dock"][0]["title"], "FA:Selling")
		self.assertEqual(bootinfo["app_data"][0]["dock"][0]["label"], "FA:Buying")
		self.assertEqual(bootinfo["app_data"][0]["dock"][0]["link_to"], "Stock")

	def test_english_session_is_left_alone(self):
		bootinfo = {"app_data": [{"dock": [{"title": "Stock"}]}]}
		with patch.object(frappe.local, "lang", "en"):
			apply_boot_display_translations(bootinfo)
		self.assertEqual(bootinfo["app_data"][0]["dock"][0]["title"], "Stock")
