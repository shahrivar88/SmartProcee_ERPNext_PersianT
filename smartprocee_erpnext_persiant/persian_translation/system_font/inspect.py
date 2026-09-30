"""Read Web Font bytes and propose a face mapping from internal metadata."""

from __future__ import annotations

import io
from pathlib import Path

CSS_WEIGHTS = (100, 200, 300, 400, 500, 600, 700, 800, 900)
STRETCHES = (
	"ultra-condensed",
	"extra-condensed",
	"condensed",
	"semi-condensed",
	"normal",
	"semi-expanded",
	"expanded",
	"extra-expanded",
	"ultra-expanded",
)
STYLES = ("normal", "italic", "oblique")
WIDTH_BY_CLASS = {index + 1: name for index, name in enumerate(STRETCHES)}

# Longer tokens first so "semibold" is not classified as "bold".
_WEIGHT_TOKENS = (
	("extrablack", 900),
	("ultrablack", 900),
	("extra black", 900),
	("ultra black", 900),
	("extrabold", 800),
	("ultra bold", 800),
	("ultrabold", 800),
	("extra bold", 800),
	("semibold", 600),
	("semi bold", 600),
	("demibold", 600),
	("demi bold", 600),
	("extralight", 200),
	("extra light", 200),
	("ultralight", 200),
	("ultra light", 200),
	("medium", 500),
	("light", 300),
	("black", 900),
	("heavy", 900),
	("bold", 700),
	("thin", 100),
	("regular", 400),
	("normal", 400),
	("book", 400),
)


class FontRejected(Exception):
	"""A file must not become a system web font."""


def inspect_font_bytes(filename: str, data: bytes) -> dict:
	original = safe_original_name(filename)
	font_format = detect_format(original, data)
	try:
		from fontTools.ttLib import TTFont
	except ImportError as error:
		raise FontRejected(
			"ابزار خواندن فراداده فونت در این محیط نصب نیست. جزئیات در Error Log ثبت شد."
		) from error
	try:
		font = TTFont(io.BytesIO(data))
		os2 = font["OS/2"]
		names = _name_map(font)
	except Exception as error:
		raise FontRejected(
			"این فایل یک Web Font معتبر نیست. لطفاً فایل WOFF2 یا WOFF معتبر انتخاب کنید."
		) from error

	family = _clean_text(names.get(16) or names.get(1))
	if not family:
		raise FontRejected(
			"این فایل یک Web Font معتبر نیست. لطفاً فایل WOFF2 یا WOFF معتبر انتخاب کنید."
		)
	subfamily = _clean_text(names.get(17) or names.get(2)) or "Regular"
	weight_class = int(getattr(os2, "usWeightClass", 400) or 400)
	css_weight = css_weight_from_class(weight_class)
	text_weight = weight_from_text(subfamily)
	width_class = int(getattr(os2, "usWidthClass", 5) or 5)
	stretch = WIDTH_BY_CLASS.get(width_class, "normal")
	style = detect_style(os2.fsSelection, subfamily)
	warnings = []
	if text_weight and text_weight != css_weight:
		warnings.append(
			f"فراداده عددی وزن {css_weight} است اما نام زیرخانواده «{subfamily}» وزن {text_weight} را نشان می‌دهد. "
			"نگاشت پیشنهادی بر اساس وزن عددی است."
		)
	warnings.extend(filename_warnings(original, css_weight, stretch))
	if stretch != "normal":
		warnings.append(
			"این فایل نسخه Condensed فونت است. برای متن عمومی رابط کاربری معمولاً نسخه Normal پیشنهاد می‌شود."
			if "condensed" in stretch
			else "این فایل نسخه Expanded فونت است. برای متن عمومی رابط کاربری معمولاً نسخه Normal پیشنهاد می‌شود."
		)
	return {
		"original_filename": original,
		"font_format": font_format,
		"family_name": family,
		"subfamily": subfamily,
		"full_name": _clean_text(names.get(4)) or family,
		"postscript_name": _clean_text(names.get(6)),
		"weight_class": weight_class,
		"css_weight": css_weight,
		"font_style": style,
		"detected_style": style,
		"font_stretch": stretch,
		"width_class": width_class,
		"warnings": warnings,
		"enabled": 1,
	}


def detect_format(filename: str, data: bytes) -> str:
	if not data or len(data) < 12:
		raise FontRejected(
			"این فایل یک Web Font معتبر نیست. لطفاً فایل WOFF2 یا WOFF معتبر انتخاب کنید."
		)
	if data.startswith(b"wOF2"):
		return "WOFF2"
	if data.startswith(b"wOFF"):
		return "WOFF"
	extension = Path(filename or "").suffix.lower()
	if data.startswith((b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1")) or extension in {".ttf", ".otf"}:
		raise FontRejected(
			"این فایل TTF/OTF است. برای بهترین سازگاری و سرعت در ERPNext، نسخه WOFF2 این فونت را انتخاب کنید."
		)
	if extension not in {".woff", ".woff2"} or data.startswith(b"PK"):
		raise FontRejected(
			"فرمت این فایل برای فونت وب پشتیبانی نمی‌شود. فرمت پیشنهادی WOFF2 و فرمت جایگزین WOFF است."
		)
	raise FontRejected(
		"این فایل یک Web Font معتبر نیست. لطفاً فایل WOFF2 یا WOFF معتبر انتخاب کنید."
	)


def css_weight_from_class(value: int) -> int:
	if value in CSS_WEIGHTS:
		return value
	snapped = int(round(int(value) / 100.0) * 100)
	return min(900, max(100, snapped))


def weight_from_text(value: str) -> int | None:
	text = " ".join((value or "").lower().replace("-", " ").replace("_", " ").split())
	for token, weight in _WEIGHT_TOKENS:
		if token in text:
			return weight
	return None


def detect_style(fs_selection: int, subfamily: str) -> str:
	text = (subfamily or "").lower()
	if fs_selection & 512 or "oblique" in text:
		return "oblique"
	if fs_selection & 1 or "italic" in text:
		return "italic"
	return "normal"


def apply_correction(face: dict, correction: dict) -> dict:
	"""Validate an explicit admin mapping against the stored metadata."""
	updated = dict(face)
	enabled = correction.get("enabled", face.get("enabled", 1))
	updated["enabled"] = 0 if str(enabled).lower() in {"0", "false"} else 1
	for key, allowed in (
		("css_weight", set(CSS_WEIGHTS)),
		("font_style", set(STYLES)),
		("font_stretch", set(STRETCHES)),
	):
		if correction.get(key) in (None, ""):
			continue
		value = int(correction[key]) if key == "css_weight" else str(correction[key])
		if value not in allowed:
			raise FontRejected("نگاشت درخواستی برای این فایل معتبر نیست.")
		updated[key] = value
	_reject_unsafe_remap(face, updated)
	updated["mapping_note"] = mapping_note(face, updated)
	return updated


def mapping_note(face: dict, updated: dict) -> str:
	detected = {
		"css_weight": css_weight_from_class(int(face.get("weight_class") or 400)),
		"font_style": face.get("detected_style") or "normal",
		"font_stretch": WIDTH_BY_CLASS.get(int(face.get("width_class") or 5), "normal"),
	}
	notes = []
	for key, label in (("css_weight", "وزن"), ("font_style", "حالت"), ("font_stretch", "عرض")):
		if str(updated.get(key)) != str(detected[key]):
			notes.append(
				f"فراداده {label} را «{detected[key]}» نشان می‌دهد اما نگاشت درخواستی «{updated.get(key)}» است."
			)
	return "\n".join(notes)


def duplicate_messages(faces: list[dict]) -> list[str]:
	groups: dict[tuple, list[str]] = {}
	for face in faces:
		if not face.get("enabled", 1):
			continue
		key = (int(face["css_weight"]), face["font_style"], face["font_stretch"], face["font_format"])
		groups.setdefault(key, []).append(face["original_filename"])
	messages = []
	for (weight, style, stretch, _fmt), names in groups.items():
		if len(names) < 2:
			continue
		messages.append(
			f"برای وزن {weight} با حالت {_label(style)} و عرض {_label(stretch)} "
			"بیش از یک فایل شناسایی شد. لطفاً یکی از فایل‌ها را انتخاب کنید."
		)
	return messages


def missing_regular_warning(faces: list[dict]) -> str | None:
	for face in faces:
		if not face.get("enabled", 1):
			continue
		if int(face["css_weight"]) == 400 and face["font_style"] == "normal" and face["font_stretch"] == "normal":
			return None
	return (
		"برای این خانواده وزن Regular (400) با عرض Normal شناسایی نشد. "
		"برای نمایش استاندارد رابط کاربری پیشنهاد می‌شود فایل Regular این فونت را اضافه کنید."
	)


def safe_original_name(filename: str) -> str:
	name = Path(str(filename or "font")).name.replace("\x00", "")
	name = " ".join(name.split())
	return (name or "font")[:180]


def filename_warnings(filename: str, css_weight: int, stretch: str) -> list[str]:
	stem = Path(filename).stem.lower().replace("_", " ").replace("-", " ")
	hints = []
	hint = weight_from_text(stem)
	if hint and hint != css_weight:
		hints.append(
			f"نام فایل وزن {hint} را نشان می‌دهد اما فراداده داخلی وزن {css_weight} است."
		)
	file_is_condensed = "condensed" in stem
	meta_is_condensed = "condensed" in stretch
	if file_is_condensed != meta_is_condensed:
		hints.append(
			f"نام فایل و فراداده درباره عرض فونت یکسان نیستند. فراداده عرض {stretch} است."
		)
	return hints


def _reject_unsafe_remap(original: dict, updated: dict):
	# Small corrections cover vendor quirks; larger jumps would fake a different face.
	metadata_weight = css_weight_from_class(int(original.get("weight_class") or 400))
	target = int(updated["css_weight"])
	if metadata_weight - target > 200:
		raise FontRejected(
			f"این فایل وزن ضخیم {metadata_weight} است و نباید به عنوان وزن {target} (مثلاً Regular) استفاده شود. "
			"آن را به وزن واقعی خود نگاشت کنید."
		)
	if target - metadata_weight > 200:
		raise FontRejected(
			f"فراداده این فایل وزن نازک {metadata_weight} را نشان می‌دهد و نمی‌تواند به وزن {target} نگاشت شود."
		)
	if updated["font_stretch"] == "normal" and int(original.get("width_class") or 5) != 5:
		raise FontRejected(
			"این فایل نسخه Condensed فونت است. برای متن عمومی رابط کاربری معمولاً نسخه Normal پیشنهاد می‌شود. "
			"عرض آن را نمی‌توان Normal ثبت کرد."
		)


def _name_map(font) -> dict[int, str]:
	found = {}
	for record in font["name"].names:
		if record.nameID in found or record.nameID not in {1, 2, 4, 6, 16, 17}:
			continue
		try:
			found[record.nameID] = record.toUnicode()
		except Exception:
			continue
	return found


def _clean_text(value: str | None) -> str:
	if not value:
		return ""
	return " ".join(str(value).replace("\x00", " ").split())


def _label(value: str) -> str:
	return str(value).replace("-", " ").title()
