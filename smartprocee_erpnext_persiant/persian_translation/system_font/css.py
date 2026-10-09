"""Build the active Desk stylesheet from registered faces.

The stylesheet is scoped to a Persian UI root, so a non-Persian user never
receives the font. Browsers only download a web font when a rendered element
uses that family, so scoping also stops the font binaries from being fetched
for other languages.
"""

from __future__ import annotations

from smartprocee_erpnext_persiant.persian_translation.language import style_scope

FALLBACK_STACK = (
	'"Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", '
	'"Roboto", "Helvetica Neue", Arial, sans-serif'
)
# The scope a standalone app's font stylesheet hangs off. The adapter sets
# `dir="rtl"` on the app root and links this file, so Persian is the only
# language that ever selects it.
ADAPTER_SCOPE = 'html[dir="rtl"]'
ADAPTER_FONT_VARIABLE = "--persianizer-font-stack"
# A frappe-ui app sets its font on the root and repeats it on these two; every
# other element inherits it, form controls included. Monospace elements and
# `.font-mono` declare their own family, so they are deliberately not listed.
ADAPTER_FONT_SELECTORS = ("", ".font-sans", "[data-sonner-toaster]")
FONT_FAMILY_SELECTORS = (
	"body",
	".navbar",
	".page-head",
	".modal",
	".dropdown-menu",
	".form-control",
	".input-with-feedback",
	"button",
	"input",
	"select",
	"textarea",
	".btn",
	".ql-editor",
	".layout-side-section",
	".list-row",
	".datatable",
	".report-wrapper",
	".widget",
)
MONOSPACE_SELECTORS = ("code", "kbd", "pre", "samp", ".code-field", ".ace_editor")
MONOSPACE_STACK = "var(--font-monospace, SFMono-Regular, Menlo, Consolas, monospace)"
_UPLOAD_PREFIX = "/files/persian-font-"


def sanitize_css_family(value: str) -> str:
	cleaned = []
	for char in str(value or ""):
		if char in '\\"<>{}();:@\n\r\t':
			continue
		cleaned.append(char)
	family = " ".join("".join(cleaned).split())
	if not family:
		raise ValueError("empty font family")
	return family[:80]


def managed_family(family: str) -> str:
	# A distinct name keeps these faces apart from a same-named font the browser may already know.
	return f"Persianizer {sanitize_css_family(family)}"[:90]


def font_family_rules(scope: str | None = None, stack: str = "var(--font-stack)") -> str:
	"""Return the scoped `font-family` rules shared by every generated stylesheet."""
	prefix = f"{scope} " if scope else ""
	rules = [
		_scoped_rule(prefix, FONT_FAMILY_SELECTORS, f"font-family: {stack} !important;"),
		_scoped_rule(prefix, MONOSPACE_SELECTORS, f"font-family: {MONOSPACE_STACK} !important;"),
		"@media print {\n" + _scoped_rule(prefix, ("body", ".print-format"), f"font-family: {stack} !important;") + "\n}",
	]
	return "\n\n".join(rules)


def render_family_css(family: str, faces: list[dict]) -> str:
	"""Build the Desk stylesheet, scoped to the Persian language root."""
	faces_css, stack = _faces_and_stack(family, faces)
	scope = style_scope()
	return (
		f"{faces_css}\n\n"
		f"{scope} {{\n\t--font-stack: {stack};\n}}\n\n"
		f"{font_family_rules(scope)}\n"
	)


def render_adapter_css(family: str, faces: list[dict]) -> str:
	"""Build the stylesheet a standalone app links when its adapter opts in.

	A standalone SPA keeps its own ``<html lang="en">`` and never receives
	``app_include_css``, so this hangs off the direction the adapter sets. It is
	built from the same faces as the Desk file, so the active Persian font stays
	the single source of truth. Unlike the Desk rules it sets the family only
	where the app itself does, without ``!important``: monospace elements, icon
	fonts and anything else that names its own family keep it.
	"""
	faces_css, stack = _faces_and_stack(family, faces)
	selectors = ",\n".join(f"{ADAPTER_SCOPE} {item}".rstrip() for item in ADAPTER_FONT_SELECTORS)
	return (
		f"{faces_css}\n\n"
		f"{ADAPTER_SCOPE} {{\n\t{ADAPTER_FONT_VARIABLE}: {stack};\n}}\n\n"
		f"{selectors} {{\n\tfont-family: var({ADAPTER_FONT_VARIABLE});\n}}\n"
	)


def _faces_and_stack(family: str, faces: list[dict]) -> tuple[str, str]:
	css_family = managed_family(family)
	blocks = [_face_block(css_family, key, group) for key, group in _groups(faces).items()]
	if not blocks:
		raise ValueError("no faces")
	return "\n\n".join(blocks), f'"{css_family}", {FALLBACK_STACK}'


def _scoped_rule(scope: str, selectors, declaration: str) -> str:
	# `scope` is either "" or a selector followed by a single space.
	head = ",\n".join(f"{scope}{selector}" for selector in selectors)
	return f"{head} {{\n\t{declaration}\n}}"


def _groups(faces: list[dict]) -> dict[tuple, list[dict]]:
	grouped: dict[tuple, list[dict]] = {}
	for face in faces:
		if not face.get("enabled", 1):
			continue
		key = (int(face["css_weight"]), face["font_style"], face["font_stretch"])
		grouped.setdefault(key, []).append(face)
	return dict(sorted(grouped.items()))


def _face_block(family: str, key: tuple, group: list[dict]) -> str:
	weight, style, stretch = key
	sources = []
	for face in sorted(group, key=lambda item: 0 if item.get("font_format") == "WOFF2" else 1):
		sources.append(_source(face["file_url"], face["font_format"]))
		if face.get("fallback_url"):
			fallback_format = "WOFF" if face["font_format"] == "WOFF2" else "WOFF2"
			sources.append(_source(face["fallback_url"], fallback_format))
	src = ",\n\t\t".join(sources)
	return (
		"@font-face {\n"
		f'\tfont-family: "{family}";\n'
		f"\tfont-style: {style};\n"
		f"\tfont-weight: {weight};\n"
		f"\tfont-stretch: {stretch};\n"
		"\tfont-display: swap;\n"
		f"\tsrc: {src};\n"
		"}"
	)


def _source(url: str, font_format: str) -> str:
	safe = _safe_url(url)
	fmt = "woff2" if font_format == "WOFF2" else "woff"
	return f'url("{safe}") format("{fmt}")'


def _safe_url(url: str) -> str:
	value = str(url or "")
	if value.startswith(_UPLOAD_PREFIX):
		if any(token in value for token in ('"', "'", "\\", ")", "(", "<", ">", " ")):
			raise ValueError("unsafe font url")
		return value
	raise ValueError("unsafe font url")
