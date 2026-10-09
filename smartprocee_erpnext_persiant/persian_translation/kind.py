"""The vocabulary that names the kind of a piece of text.

Every label below is decided from evidence, never from a guess: the translation
context Frappe passed to ``_()``, the note Frappe's own extractor wrote next to
the string, or the document the string belongs to. ``persian_translation.location``
applies those rules; this module only holds the words and the phrase tables.
"""

from __future__ import annotations

FIELD = "فیلد"
OPTION = "گزینه"
DESCRIPTION = "توضیح"
DOCUMENT = "نام سند"
ROLE = "نقش کاربر"
BUTTON = "دکمه"
MENU = "منو"
REPORT = "گزارش"
PAGE = "صفحه"
WEB_FORM = "فرم وب"
CODE = "متن برنامه"
OTHER = "سایر"
UNKNOWN = "نامشخص"

# The filter of the manager lists these in this order.
KIND_LABELS = (
	FIELD,
	OPTION,
	DESCRIPTION,
	MENU,
	BUTTON,
	REPORT,
	PAGE,
	WEB_FORM,
	DOCUMENT,
	ROLE,
	CODE,
	OTHER,
	UNKNOWN,
)

# What the context Frappe passed to `_()` states about the role of the string.
CONTEXT_PHRASES = (
	("button", BUTTON),
	("column of report", REPORT),
)

# What the extractor note states. The note is a fact Frappe wrote down, so it is
# read before any shape of the file path is taken into account.
NOTE_PHRASES = (
	("label of a field", FIELD),
	("option in a select field", OPTION),
	("option for", OPTION),
	("label of name column in report", REPORT),
	("name of a report", REPORT),
	("description of", DESCRIPTION),
	("help text", DESCRIPTION),
	("name of a workspace", MENU),
	("label of a workspace sidebar item", MENU),
	("label of a link", MENU),
	("label of a shortcut", MENU),
	("label of a desktop icon", MENU),
	("title of an onboarding step", PAGE),
)

_COMMENT_PREFIXES = (
	"name of ",
	"label of ",
	"description of ",
	"option for ",
	"title of ",
	"placeholder ",
	"help text",
)


def from_context(context: str) -> str:
	return _from_phrases(context, CONTEXT_PHRASES)


def from_note(note: str) -> str:
	return _from_phrases(note, NOTE_PHRASES)


def is_extractor_comment(text: str) -> bool:
	lowered = (text or "").strip().casefold()
	return lowered.startswith(_COMMENT_PREFIXES)


def comment_text(value) -> str:
	"""The extractor note of one scanned message, or an empty string.

	``frappe.gettext`` passes either a runtime context or a note describing the
	kind of text. Only the note is kept; the scan writes it beside the path, so a
	note never becomes ``Translation.context``.
	"""
	if isinstance(value, (list, tuple)):
		parts = [str(item).strip() for item in value if str(item).strip()]
		return "; ".join(parts)
	if isinstance(value, str) and is_extractor_comment(value):
		return value.strip()
	return ""


def _from_phrases(text: str, phrases) -> str:
	lowered = (text or "").strip().casefold()
	if not lowered:
		return ""
	for phrase, label in phrases:
		if phrase in lowered:
			return label
	return ""
