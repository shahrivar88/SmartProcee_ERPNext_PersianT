"""The only code that writes into somebody else's page, and it is deliberately dull.

Two edits, both additive, both idempotent:

* one ``<link>`` to this app's adapter stylesheet, placed just before ``</head>``
* ``dir="rtl"`` on the document root, keeping every other root attribute untouched

``lang`` is never changed. Enabling RTL must not quietly reflow typography or
change font fallback inside the target application; the Persian system font is
linked only when the administrator opts a supporting adapter into it.
"""

from __future__ import annotations

import re

from smartprocee_erpnext_persiant.persian_rtl import registry, settings
from smartprocee_erpnext_persiant.persian_rtl.adapters import base

MARKER = "data-persian-rtl"
HTML_TAG = re.compile(r"<html\b[^>]*>", re.IGNORECASE)
HEAD_CLOSE = re.compile(r"</head\s*>", re.IGNORECASE)
BODY_CLOSE = re.compile(r"</body\s*>", re.IGNORECASE)
DIR_ATTRIBUTE = re.compile(r"(\s)dir(\s*=\s*)(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
UNSAFE_SELECTOR = re.compile(r"[{}<>]|/\*|\*/")
RTL_SCOPE = '[dir="rtl"]'

ISLAND_RULE = "{selector} {{ direction: ltr; unicode-bidi: isolate; }}"
AUTO_RULE = "{selector} {{ unicode-bidi: plaintext; }}"


def sanitize_selector(selector: str) -> str:
	"""Reject anything that could break out of the injected ``<style>`` block."""
	selector = (selector or "").strip()
	if not selector or UNSAFE_SELECTOR.search(selector):
		return ""
	return selector


def split_selector_list(selector: str) -> list[str]:
	"""Split a selector list on its top-level commas only.

	A comma inside ``:is(...)``, ``[data-x="a,b"]`` or a quoted string belongs to
	that one selector and is kept with it.
	"""
	parts, depth, quote, start = [], 0, "", 0
	for index, char in enumerate(selector):
		if quote:
			if char == quote and selector[index - 1] != "\\":
				quote = ""
		elif char in "\"'":
			quote = char
		elif char in "([":
			depth += 1
		elif char in ")]":
			depth = max(depth - 1, 0)
		elif char == "," and depth == 0:
			parts.append(selector[start:index])
			start = index + 1
	parts.append(selector[start:])
	return [part.strip() for part in parts if part.strip()]


def scope_selector(selector: str) -> str:
	"""Put every selector of the list under the RTL root, not only the first one."""
	return ", ".join(f"{RTL_SCOPE} {part}" for part in split_selector_list(selector))


def choose_adapter(path: str) -> base.Adapter | None:
	"""The single adapter that may handle this path, or ``None``.

	When two adapters claim a path the first one in registry order wins and the
	ambiguity is surfaced by diagnostics rather than silently layered.
	"""
	if registry.is_path_ignored(path):
		return None
	matches = registry.matching_adapters(path)
	if not matches:
		return None
	if len(matches) > 1:
		from frappe import logger

		logger().warning(
			"Persian RTL: %s matches more than one adapter (%s); using %s",
			path,
			", ".join(item.adapter_id for item in matches),
			matches[0].adapter_id,
		)
	return matches[0]


def is_eligible(adapter: base.Adapter, states: dict | None = None) -> tuple[bool, str]:
	"""Whether this adapter may run right now, with the reason when it may not."""
	states = states if states is not None else settings.adapter_states()
	state = states.get(adapter.adapter_id, {})
	if not state.get("enabled"):
		return False, "disabled"
	version_state = registry.version_state(adapter)
	if version_state == registry.NOT_INSTALLED:
		return False, f"{adapter.target_app} is not installed"
	if version_state == registry.MISMATCH and not state.get("override_version_check"):
		return False, f"version {registry.installed_version(adapter.target_app)} is outside {adapter.compatible_min} - {adapter.compatible_max}"
	if not adapter.visual_ready:
		return False, "no visual adapter has been written yet"
	return True, "ok"


def exclusions_css(adapter: base.Adapter) -> str:
	"""CSS for the adapter's exclusions plus the administrator's own additions."""
	blocks = []
	for item in settings.exclusions_for(adapter.adapter_id):
		selector = sanitize_selector(item["selector"])
		if not selector:
			continue
		template = AUTO_RULE if item["mode"] == base.AUTO_DIRECTION else ISLAND_RULE
		blocks.append(template.format(selector=scope_selector(selector)))
	return "\n".join(blocks)


def link_tag(adapter: base.Adapter) -> str:
	url = adapter.asset_url
	if not url:
		return ""
	return f'<link rel="stylesheet" href="{url}" {MARKER}="{adapter.adapter_id}">'


def uses_system_font(adapter: base.Adapter, states: dict | None = None) -> bool:
	"""Whether the administrator opted this adapter into the active Persian font."""
	if not adapter.supports_system_font:
		return False
	states = states if states is not None else settings.adapter_states()
	return bool(states.get(adapter.adapter_id, {}).get("use_system_font"))


def font_link_tag(adapter: base.Adapter, states: dict | None = None) -> str:
	"""The active Persian font stylesheet, when this adapter opted into it.

	The Desk already loads it through ``app_include_css``. A standalone SPA never
	does, so the adapter links the stylesheet generated for the RTL scope from the
	activated custom family. With no family activated, or the option off, the app
	keeps its own font.
	"""
	from smartprocee_erpnext_persiant.persian_translation.system_font.storage import adapter_font_url

	if not uses_system_font(adapter, states):
		return ""
	url = adapter_font_url()
	if not url:
		return ""
	return f'<link rel="stylesheet" href="{url}" {MARKER}-font="1">'


def style_tag(adapter: base.Adapter) -> str:
	css = exclusions_css(adapter)
	if not css:
		return ""
	return f"<style {MARKER}-exclusions>\n{css}\n</style>"


def set_root_direction(html: str, direction: str = "rtl") -> str:
	"""Force ``dir`` on the first ``<html>`` tag without touching any other attribute."""
	match = HTML_TAG.search(html)
	if not match:
		return html
	tag = match.group(0)
	if DIR_ATTRIBUTE.search(tag):
		replaced = DIR_ATTRIBUTE.sub(lambda item: f'{item.group(1)}dir="{direction}"', tag, count=1)
		if replaced == tag:
			return html
		return html[: match.start()] + replaced + html[match.end() :]
	rebuilt = tag[:-1].rstrip() + f' dir="{direction}">'
	return html[: match.start()] + rebuilt + html[match.end() :]


def inject(html: str, adapter: base.Adapter, states: dict | None = None) -> str:
	"""Return ``html`` with the adapter applied, or the original text untouched."""
	if MARKER in html:
		return html
	parts = (link_tag(adapter), font_link_tag(adapter, states), style_tag(adapter))
	payload = "\n".join(part for part in parts if part)
	if not payload:
		return html
	html = set_root_direction(html, "rtl")
	for pattern in (HEAD_CLOSE, BODY_CLOSE):
		match = pattern.search(html)
		if match:
			return html[: match.start()] + payload + "\n" + html[match.start() :]
	return html + "\n" + payload
