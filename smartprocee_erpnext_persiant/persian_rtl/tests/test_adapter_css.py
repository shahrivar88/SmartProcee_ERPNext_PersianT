"""The adapter stylesheet is the fragile part, so it is linted, not trusted.

Two properties are enforced mechanically:

* coverage -- every utility the adapter declares in ``signature_physical`` has a
  mirroring rule, so a declared signature can never overstate what is handled
* logical pairing -- a rule may zero a physical property, but it must also state
  the mirrored logical property; a physical declaration may never be the only
  outcome of a rule
"""

import re

from frappe.tests import UnitTestCase

from smartprocee_erpnext_persiant.persian_rtl import detection, registry

RULE = re.compile(r"\[dir=\"rtl\"\]\s+([^{]+)\{([^}]*)\}")
CLASS_TOKEN = re.compile(r"\.((?:\\.|[-\w\[\]./])+)")
ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]|^/home/|^/Users/|^/var/|^/opt/")

# A physical declaration must be accompanied by the logical counterpart.
MIRROR_OF = {
	"margin-left:0": "margin-inline-start:",
	"margin-right:0": "margin-inline-end:",
	"padding-left:0": "padding-inline-start:",
	"padding-right:0": "padding-inline-end:",
	"left:auto": "inset-inline-start:",
	"right:auto": "inset-inline-end:",
	"border-left-width": "border-inline-start-width:",
	"border-right-width": "border-inline-end-width:",
	"border-top-left-radius:0": "border-start-start-radius:",
	"border-bottom-left-radius:0": "border-end-start-radius:",
	"border-top-right-radius:0": "border-start-end-radius:",
	"border-bottom-right-radius:0": "border-end-end-radius:",
	"text-align:left": "text-align:start",
	"text-align:right": "text-align:end",
}


def adapter_css(adapter_id="crm") -> str:
	adapter = registry.all_adapters()[adapter_id]
	target = detection.stylesheet_path(adapter.asset_url)
	return target.read_text(encoding="utf-8")


def css_rules(adapter_id="crm"):
	for selector, body in RULE.findall(adapter_css(adapter_id)):
		yield selector.strip(), body.strip()


def covered_classes(adapter_id="crm") -> set[str]:
	found = set()
	for selector, _body in css_rules(adapter_id):
		for match in CLASS_TOKEN.finditer(selector):
			found.add(match.group(1).replace("\\", ""))
	return found


class TestAdapterStylesheet(UnitTestCase):
	def test_the_stylesheet_is_where_the_adapter_says_it_is(self):
		for adapter in registry.all_adapters().values():
			if not adapter.asset_url:
				continue
			with self.subTest(adapter.adapter_id):
				self.assertTrue(detection.stylesheet_path(adapter.asset_url).exists(), adapter.asset_url)

	def test_every_declared_signature_utility_has_a_rule(self):
		adapter = registry.all_adapters()["crm"]
		covered = covered_classes()
		missing = sorted(item for item in adapter.signature_physical if item not in covered)
		self.assertEqual(missing, [], f"no mirroring rule for: {missing}")

	def test_each_physical_declaration_is_paired_with_a_logical_one(self):
		for selector, body in css_rules():
			for physical, logical in MIRROR_OF.items():
				if physical not in body:
					continue
				with self.subTest(f"{selector} :: {physical}"):
					self.assertIn(logical, body, f"{selector} zeroes {physical} without {logical}")

	def test_the_stylesheet_never_uses_important(self):
		self.assertNotIn("!important", adapter_css())

	def test_floats_are_mirrored_physically(self):
		"""CSS has no portable logical float, so the two floats must swap."""
		expected = {"float-left": "float:right", "float-right": "float:left"}
		for selector, body in css_rules():
			for utility, mirror in expected.items():
				if utility not in selector:
					continue
				with self.subTest(f"{selector} -> {mirror}"):
					self.assertIn(mirror, body)

	def test_the_stylesheet_does_not_rely_on_a_machine_specific_path(self):
		for line in adapter_css().splitlines():
			if line.strip().startswith(("/*", "*", "http")):
				continue
			self.assertIsNone(ABSOLUTE_PATH.search(line.strip()), line)

	def test_the_stylesheet_does_not_reference_a_hashed_asset_name(self):
		self.assertIsNone(re.search(r"[-.][A-Za-z0-9_]{8}\.(js|css|mjs)", adapter_css()))

	def test_rules_are_scoped_to_the_rtl_document(self):
		for selector, _body in css_rules():
			self.assertTrue(selector.startswith(".") or selector.startswith(".group"), selector)

	def test_symmetric_utilities_are_left_alone(self):
		"""`inset-x-*` sets both sides equally, so mirroring it would be a bug."""
		for selector, _body in css_rules():
			self.assertNotIn("inset-x-", selector)

	def test_the_centring_offset_is_not_mirrored(self):
		for selector, _body in css_rules():
			self.assertNotIn("left-1\\/2", selector)

	def test_crm_is_the_only_adapter_with_a_stylesheet(self):
		with_stylesheet = {a.adapter_id for a in registry.all_adapters().values() if a.stylesheet}
		self.assertEqual(with_stylesheet, {"crm"})

	def test_the_list_column_handle_is_mirrored(self):
		self.assertIn(".-right-2", adapter_css())
		self.assertIn("inset-inline-end:-.5rem", adapter_css())

	def test_the_apps_submenu_follows_document_direction(self):
		css = adapter_css()
		self.assertIn(".menu-content{direction:rtl;text-align:start}", css)
		self.assertIn(".menu-content .lucide-chevron-right{transform:scaleX(-1)}", css)

	def test_the_app_logo_asset_exists(self):
		from pathlib import Path

		public = Path(__file__).resolve().parents[2] / "public" / "images" / "logo.svg"
		self.assertTrue(public.is_file(), public)
