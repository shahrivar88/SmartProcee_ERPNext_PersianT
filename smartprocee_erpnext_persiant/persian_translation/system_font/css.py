"""Build the active Desk stylesheet from registered faces."""

from __future__ import annotations

FALLBACK_STACK = (
	'"Yekan Bakh", "Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", '
	'"Roboto", "Helvetica Neue", Arial, sans-serif'
)
_ASSET_PREFIX = "/assets/smartprocee_erpnext_persiant/fonts/"
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
	# A distinct name keeps these faces apart from the legacy "Yekan Bakh" rules in yekan_bakh.css.
	return f"Persianizer {sanitize_css_family(family)}"[:90]


def render_family_css(family: str, faces: list[dict]) -> str:
	css_family = managed_family(family)
	blocks = [_face_block(css_family, key, group) for key, group in _groups(faces).items()]
	if not blocks:
		raise ValueError("no faces")
	stack = f'"{css_family}", {FALLBACK_STACK}'
	rules = "\n\n".join(blocks)
	return (
		f"{rules}\n\n"
		f":root {{\n\t--font-stack: {stack};\n}}\n\n"
		"body,\n.navbar,\n.page-head,\n.modal,\n.dropdown-menu,\n.form-control,\n"
		".input-with-feedback,\nbutton,\ninput,\nselect,\ntextarea,\n.btn,\n.ql-editor,\n"
		".layout-side-section,\n.list-row,\n.datatable,\n.report-wrapper,\n.widget {\n"
		"\tfont-family: var(--font-stack);\n}\n\n"
		"code,\nkbd,\npre,\nsamp,\n.code-field,\n.ace_editor {\n"
		"\tfont-family: var(--font-monospace, SFMono-Regular, Menlo, Consolas, monospace);\n}\n"
	)


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
	if value.startswith(_ASSET_PREFIX) or value.startswith(_UPLOAD_PREFIX):
		if any(token in value for token in ('"', "'", "\\", ")", "(", "<", ">", " ")):
			raise ValueError("unsafe font url")
		return value
	raise ValueError("unsafe font url")
