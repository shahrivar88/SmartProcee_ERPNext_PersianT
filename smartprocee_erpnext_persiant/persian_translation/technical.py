"""A conservative flag for strings that are clearly machine text, not UI wording.

The flag exists so a translator can skip rows that no human should ever
translate: minified bundles, build asset names, content hashes, raw CSS rules
and symbol-only fragments. It is deliberately *very* narrow, because a false
positive costs a real translation. Nothing here removes a row, edits a value or
influences what is published: it only writes a note beside the row.

Strings carrying placeholders, Jinja, HTML or ordinary words are never flagged.
"""

from __future__ import annotations

import re

LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
PERSIAN_RE = re.compile(r"[\u0600-\u06FF]")
WORD_RE = re.compile(r"[A-Za-z]{2,}")

MINIFIED_RE = re.compile(r"(function\s*\(|=>\s*\{|\}\s*\)\s*;|!function|;\s*var\s|\breturn\s+\w+\s*;)")
CSS_RULE_RE = re.compile(r"[.#@][-\w]+\s*\{[^{}]*:[^{}]*;?\s*\}")
ASSET_NAME_RE = re.compile(r"^[\w.\-]+-[A-Za-z0-9_]{6,}\.(js|mjs|css|woff2?|ttf|png|svg)$")
HASH_RE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
BASE64_RE = re.compile(r"^[A-Za-z0-9+/]{32,}={0,2}$")
LONG_TOKEN_RE = re.compile(r"^\S{60,}$")
PATH_RE = re.compile(r"^(\.{0,2}/|/)?[\w.\-/@]+\.(py|js|ts|tsx|vue|json|css|html|md|yml|yaml|txt)$")
URL_RE = re.compile(r"^[a-z]+://\S+$", re.IGNORECASE)
ICON_CLASS_RE = re.compile(r"^icon-[-\w]+$")
PLACEHOLDER_ONLY_RE = re.compile(r"^[\s{}0-9$%().,:_\-]*$")


def technical_reason(text: str) -> str:
	"""Why this string looks machine-generated, or an empty string."""
	text = (text or "").strip()
	if not text:
		return ""
	if PERSIAN_RE.search(text):
		return ""
	# Anything a translator has to keep intact is UI wording, not machine text.
	if "{" in text or "%" in text or "<" in text:
		return ""
	if not LETTER_RE.search(text):
		return "متن فقط از عدد و نماد ساخته شده است."
	if MINIFIED_RE.search(text):
		return "قطعه‌ای از کد فشرده‌شده (minified) به‌نظر می‌رسد."
	if CSS_RULE_RE.search(text):
		return "قاعدهٔ خام CSS به‌نظر می‌رسد."
	if ASSET_NAME_RE.match(text):
		return "نام فایل ساخته‌شدهٔ frontend است."
	if HASH_RE.match(text):
		return "هش فنی است و متن رابط کاربری نیست."
	if BASE64_RE.match(text):
		return "رشتهٔ base64 است."
	if URL_RE.match(text):
		return "نشانی اینترنتی است."
	if ICON_CLASS_RE.match(text):
		return "نام کلاس آیکون است."
	if PATH_RE.match(text):
		return "مسیر فایل است."
	if LONG_TOKEN_RE.match(text) and len(WORD_RE.findall(text)) < 2:
		return "یک توکن بلند و بدون فاصله است."
	if PLACEHOLDER_ONLY_RE.match(text):
		return "متن قابل‌ترجمه‌ای ندارد."
	return ""


def is_clearly_technical(text: str) -> bool:
	return bool(technical_reason(text))
