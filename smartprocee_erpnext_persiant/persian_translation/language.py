"""Effective-UI-language gating for Persian-only front-end customizations.

Frappe renders the effective UI language on the <html> element for both Desk
(`frappe/www/desk.html`) and Website (`frappe/templates/base.html`). Scoping a
stylesheet with `style_scope()` therefore keeps it inactive for every other
language without a template override, a client-side check or an after-request
hook.
"""

PERSIAN_LANGS = ("fa",)


def style_scope(langs=PERSIAN_LANGS) -> str:
	"""Return a CSS selector that matches a Persian UI root."""
	return ", ".join(f'html[lang="{lang}"]' for lang in langs)


def is_persian(lang: str | None = None) -> bool:
	"""Whether the given or the current effective UI language is Persian."""
	if lang is None:
		import frappe

		lang = getattr(frappe.local, "lang", None)
	return str(lang or "").lower().split("-")[0] in PERSIAN_LANGS
