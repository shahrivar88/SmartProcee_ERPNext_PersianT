"""The CRM list-column resize script stays scoped to RTL list handles."""

from frappe.tests import UnitTestCase

from smartprocee_erpnext_persiant.persian_rtl import detection, registry


def resize_script() -> str:
	adapter = registry.all_adapters()["crm"]
	return detection.stylesheet_path(adapter.script_url).read_text(encoding="utf-8")


class TestListResizeScript(UnitTestCase):
	def test_the_script_is_where_the_adapter_says_it_is(self):
		adapter = registry.all_adapters()["crm"]
		self.assertTrue(adapter.script_url)
		self.assertTrue(detection.stylesheet_path(adapter.script_url).exists())

	def test_other_adapters_do_not_ship_a_script(self):
		with_script = {item.adapter_id for item in registry.all_adapters().values() if item.script}
		self.assertEqual(with_script, {"crm"})

	def test_ltr_and_sidebar_handles_are_ignored(self):
		source = resize_script()
		self.assertIn('getAttribute("dir") === "rtl"', source)
		self.assertIn(" -right-2 ", source)
		self.assertIn("originX - (event.clientX - originX)", source)
		self.assertNotIn("MouseEvent.prototype", source)
		self.assertNotIn("addEventListener('pointer", source)
