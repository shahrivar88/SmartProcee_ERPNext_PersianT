"""The Persian font must stay scoped to the Persian UI.

The app ships no font and no static font stylesheet. The only font stylesheet is
the one Persian Font Manager generates for an uploaded family, and it may not
apply outside `html[lang="fa"]`.
"""

from frappe.tests import UnitTestCase

from smartprocee_erpnext_persiant.persian_translation.language import is_persian, style_scope
from smartprocee_erpnext_persiant.persian_translation.system_font.css import render_family_css
from smartprocee_erpnext_persiant.persian_translation.tests.helpers import (
	font_faces,
	rule_selectors,
	sample_faces,
)


class TestLanguageScope(UnitTestCase):
	def test_style_scope_targets_fa(self):
		self.assertEqual(style_scope(), 'html[lang="fa"]')

	def test_is_persian(self):
		for lang in ("fa", "fa-IR", "FA"):
			self.assertTrue(is_persian(lang), lang)
		for lang in ("en", "ar", "", None, "fr"):
			self.assertFalse(is_persian(lang), lang)

	def test_generated_css_is_language_scoped(self):
		css = render_family_css("Example Family", sample_faces())
		for selector in rule_selectors(css):
			self.assertTrue(
				selector.startswith('html[lang="fa"]'),
				f"unscoped selector in generated css: {selector}",
			)

	def test_generated_css_declares_font_stack_only_inside_scope(self):
		css = render_family_css("Example Family", sample_faces())
		self.assertIn('html[lang="fa"] {', css)
		self.assertNotIn(":root {\n\t--font-stack", css)

	def test_generated_css_keeps_monospace_and_print(self):
		css = render_family_css("Example Family", sample_faces())
		self.assertIn("--font-monospace", css)
		self.assertIn("@media print", css)

	def test_generated_css_declares_one_face_per_weight(self):
		css = render_family_css("Example Family", sample_faces((300, 400, 700)))
		self.assertEqual(sorted(weight for _family, weight, _style in font_faces(css)), [300, 400, 700])

	def test_generated_css_stack_prefers_managed_family(self):
		css = render_family_css("Example Family", sample_faces())
		self.assertIn('--font-stack: "Persianizer Example Family"', css)

	def test_hooks_ship_no_static_font_stylesheet(self):
		from smartprocee_erpnext_persiant import hooks

		self.assertFalse(getattr(hooks, "app_include_css", None))
		self.assertFalse(getattr(hooks, "web_include_css", None))
