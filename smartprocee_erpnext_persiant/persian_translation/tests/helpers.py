"""Shared helpers for the Persianizer test suite."""

import io
import re
from contextlib import contextmanager

import frappe

SAMPLE_FAMILY = "PTM Test Sans"
FONT_FACE_RE = re.compile(r"@font-face\s*\{(?P<body>[^}]*)\}", re.S)
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)

MARKER = "__PTM_TEST__"


@contextmanager
def real_queue():
	"""Let the operation engine push a real job onto the shared queue.

	The engine stays out of the queue during a test by default, because a live
	worker would run the job against the site while the test still holds its
	transaction. Only a test that is deliberately exercising the real queue opens
	this.
	"""
	previous = getattr(frappe.flags, "ptm_real_queue", False)
	frappe.flags.ptm_real_queue = True
	try:
		yield
	finally:
		frappe.flags.ptm_real_queue = previous


def make_font(family: str = SAMPLE_FAMILY, weight: int = 400, flavor: str = "woff2") -> bytes:
	"""Build a minimal web font in memory, so no third-party font is needed."""
	from fontTools.fontBuilder import FontBuilder
	from fontTools.pens.ttGlyphPen import TTGlyphPen

	builder = FontBuilder(1000, isTTF=True)
	builder.setupGlyphOrder([".notdef", "space"])
	builder.setupCharacterMap({32: "space"})
	pen = TTGlyphPen(None)
	pen.moveTo((0, 0))
	pen.lineTo((0, 500))
	pen.lineTo((500, 500))
	pen.lineTo((500, 0))
	pen.closePath()
	builder.setupGlyf({".notdef": pen.glyph(), "space": TTGlyphPen(None).glyph()})
	builder.setupHorizontalMetrics({".notdef": (600, 0), "space": (300, 0)})
	builder.setupHorizontalHeader(ascent=800, descent=-200)
	builder.setupNameTable({"familyName": family, "styleName": "Regular"})
	builder.setupOS2(usWeightClass=weight)
	builder.setupPost()
	builder.font.flavor = flavor
	buffer = io.BytesIO()
	builder.save(buffer)
	return buffer.getvalue()


def sample_faces(weights=(400, 700)) -> list[dict]:
	"""Face rows shaped like the ones an upload registers."""
	return [
		{
			"file_url": f"/files/persian-font-sample-{weight}.woff2",
			"font_format": "WOFF2",
			"css_weight": weight,
			"font_style": "normal",
			"font_stretch": "normal",
			"enabled": 1,
		}
		for weight in weights
	]


def font_faces(css: str) -> list[tuple[str, int, str]]:
	"""Return (family, weight, style) for every @font-face block."""
	faces = []
	for match in FONT_FACE_RE.finditer(css):
		body = match.group("body")
		family = re.search(r'font-family:\s*"([^"]+)"', body)
		weight = re.search(r"font-weight:\s*(\d+)", body)
		style = re.search(r"font-style:\s*([a-z]+)", body)
		if family and weight:
			faces.append((family.group(1), int(weight.group(1)), (style.group(1) if style else "normal")))
	return faces


def rule_selectors(css: str) -> list[str]:
	"""Return every selector of a top-level rule, excluding @font-face and @-rules."""
	css = CSS_COMMENT_RE.sub("", css)
	css = FONT_FACE_RE.sub("", css)
	selectors = []
	for chunk in css.split("}"):
		if "{" not in chunk:
			continue
		head = chunk.split("{", 1)[0]
		for part in head.split(","):
			part = " ".join(part.split())
			if part and not part.startswith("@"):
				selectors.append(part)
	return selectors
