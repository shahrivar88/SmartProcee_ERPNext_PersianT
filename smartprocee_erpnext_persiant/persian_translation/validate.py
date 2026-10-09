"""What makes a Persian value safe to store in Frappe's own `Translation` row.

Frappe's `Translation.validate` runs `frappe.utils.sanitize_html` over
`translated_text`. Anything that function would change is therefore *not* what
the translator typed, and it must never be changed silently. This module
predicts that exact behaviour and reports it, together with placeholders, Jinja
expressions and the HTML structure the source text already has.

`check_translation` returns a :class:`Finding`, never a bare string, so a caller
can show the reason *and* the suggested action *and* the before/after HTML.
`translation_error` keeps the old string shape for the callers that only ask
"is this value acceptable".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PLACEHOLDER_RE = re.compile(
	r"\{[0-9]+\}"
	r"|\{[A-Za-z_][A-Za-z0-9_]*\}"
	r"|%\([^)]+\)[#0-9.+\-]*[sdifr]"
	r"|%[sdifr]"
	r"|\$\{[^}]*\}"
)
JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
TAG_RE = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9]*)\b")
FORBIDDEN_HTML_RE = re.compile(
	r"<\s*/?\s*(script|iframe|object|embed|link|meta)\b|javascript\s*:|on[a-z]+\s*=",
	re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")
MAX_TRANSLATION_LENGTH = 20000
MAX_CONTEXT_LENGTH = 140

# Why a value was refused. Kept stable so tests and the UI can rely on it.
EMPTY = "empty"
TOO_LONG = "too_long"
CONTEXT_TOO_LONG = "context_too_long"
FORBIDDEN_HTML = "forbidden_html"
PLACEHOLDER_MISMATCH = "placeholder_mismatch"
JINJA_MISMATCH = "jinja_mismatch"
HTML_STRUCTURE = "html_structure"
HTML_SANITIZED = "html_sanitized"


@dataclass(frozen=True)
class Finding:
	"""One reason a value cannot be stored, with what the caller can do about it."""

	code: str
	reason: str
	action: str = ""
	before: str = ""
	after: str = ""


def jinja_tokens(text: str) -> list[str]:
	"""The part of a string Frappe's Jinja has to receive back unchanged."""
	return [WHITESPACE_RE.sub(" ", token).strip() for token in JINJA_RE.findall(text or "")]


def placeholder_tokens(text: str) -> list[str]:
	"""Named and positional substitution tokens, with any Jinja expression removed.

	Jinja is compared separately, so `{{ item }}` must not also be read as the
	named placeholder `{item}`.
	"""
	cleaned = JINJA_RE.sub(" ", text or "")
	found = []
	for token in PLACEHOLDER_RE.findall(cleaned):
		if token.startswith("{") and token.endswith("}") and not token.startswith("${"):
			inner = token[1:-1].strip()
			if inner.isdigit() or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", inner):
				token = "{" + inner + "}"
		found.append(token)
	return found


def html_tags(text: str) -> list[str]:
	return [match.group(1).lower() for match in TAG_RE.finditer(text or "")]


def sanitized(text: str) -> str:
	"""What Frappe will actually store, using Frappe's own function."""
	from frappe.utils import sanitize_html

	result = sanitize_html(text or "")
	return result if isinstance(result, str) else text or ""


def visible_text(text: str) -> str:
	"""The words a reader sees, with every tag and entity resolved.

	Used to tell "the sanitizer only re-wrote the markup" apart from "the
	sanitizer removed content the translator wrote".
	"""
	text = text or ""
	if "<" not in text and "&" not in text:
		return WHITESPACE_RE.sub(" ", text).strip()
	try:
		from bs4 import BeautifulSoup

		soup = BeautifulSoup(text, "html.parser")
		return WHITESPACE_RE.sub(" ", soup.get_text(" ")).strip()
	except Exception:
		return WHITESPACE_RE.sub(" ", text).strip()


def check_translation(source: str, translated: str, context: str = "") -> Finding | None:
	"""The first reason `translated` cannot be stored for `source`, or ``None``."""
	source = source or ""
	translated = translated or ""
	context = context or ""

	if not translated.strip():
		return Finding(EMPTY, "ترجمه فارسی خالی ذخیره نمی‌شود.", "یک مقدار فارسی وارد کنید.")
	if len(translated) > MAX_TRANSLATION_LENGTH:
		return Finding(
			TOO_LONG,
			"ترجمه فارسی بیش از حد طولانی است.",
			f"مقدار را کوتاه‌تر از {MAX_TRANSLATION_LENGTH} نویسه کنید.",
		)
	if len(context) > MAX_CONTEXT_LENGTH:
		return Finding(
			CONTEXT_TOO_LONG,
			"زمینه (Context) طولانی‌تر از ۱۴۰ نویسه است و در DocType استاندارد Translation جا نمی‌شود.",
			"زمینه را کوتاه کنید.",
		)
	if FORBIDDEN_HTML_RE.search(translated):
		return Finding(
			FORBIDDEN_HTML,
			"ترجمه فارسی شامل HTML غیرمجاز است.",
			"اسکریپت، iframe، رویدادهای on… و آدرس‌های javascript: را حذف کنید.",
			before=translated,
		)

	finding = _token_finding(source, translated)
	if finding:
		return finding

	if sorted(html_tags(source)) != sorted(html_tags(translated)):
		return Finding(
			HTML_STRUCTURE,
			"ساختار HTML ترجمه با متن اصلی هم‌خوان نیست.",
			"تگ‌های HTML را عیناً مانند متن اصلی نگه دارید.",
			before=translated,
		)

	return _sanitize_finding(translated)


def translation_error(source: str, translated: str, context: str = "") -> str | None:
	"""The reason as one line, or ``None`` when the value is safe to store."""
	finding = check_translation(source, translated, context)
	return finding.reason if finding else None


def _token_finding(source: str, translated: str) -> Finding | None:
	for label, extractor in (("جینجا", jinja_tokens), ("جایگزین", placeholder_tokens)):
		expected = extractor(source)
		actual = extractor(translated)
		if sorted(expected) == sorted(actual):
			continue
		missing = _difference(expected, actual)
		extra = _difference(actual, expected)
		detail = ""
		if missing:
			detail += " حذف‌شده: " + "، ".join(missing)
		if extra:
			detail += " اضافه‌شده: " + "، ".join(extra)
		if label == "جینجا":
			return Finding(
				JINJA_MISMATCH,
				"عبارت‌های جینجا (Jinja) ترجمه با متن اصلی هم‌خوان نیست." + detail,
				"عبارت‌های {{ }} و {% %} را دست‌نخورده نگه دارید.",
			)
		return Finding(
			PLACEHOLDER_MISMATCH,
			"نویسه‌های جایگزین ترجمه با متن اصلی هم‌خوان نیست." + detail,
			"همان جایگزین‌های متن اصلی را عیناً در ترجمه بگذارید.",
		)
	return None


def _sanitize_finding(translated: str) -> Finding | None:
	"""Predict Frappe's own `sanitize_html` so nothing is rewritten behind the user."""
	cleaned = sanitized(translated)
	if cleaned == translated:
		return None
	lost = visible_text(cleaned) != visible_text(translated)
	reason = (
		"پاک‌سازی HTML استاندارد Frappe بخشی از متن ترجمه را حذف می‌کند."
		if lost
		else "پاک‌سازی HTML استاندارد Frappe شکل ترجمه را تغییر می‌دهد."
	)
	return Finding(
		HTML_SANITIZED,
		reason,
		"مقدار پیشنهادی زیر همان چیزی است که Frappe ذخیره می‌کند؛ آن را تأیید و جای‌گذاری کنید.",
		before=translated,
		after=cleaned,
	)


def _difference(left: list[str], right: list[str]) -> list[str]:
	remaining = list(right)
	extra = []
	for item in left:
		if item in remaining:
			remaining.remove(item)
		else:
			extra.append(item)
	return sorted(set(extra))
