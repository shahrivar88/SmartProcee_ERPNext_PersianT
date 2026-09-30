import re

PLACEHOLDER_RE = re.compile(
	r"\{[0-9]+\}"
	r"|\{[A-Za-z_][A-Za-z0-9_]*\}"
	r"|%\([^)]+\)[#0-9.+\-]*[sdifr]"
	r"|%[sdifr]"
	r"|\$\{[^}]*\}"
)
TAG_RE = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9]*)\b")
FORBIDDEN_HTML_RE = re.compile(
	r"<\s*/?\s*(script|iframe|object|embed|link|meta)\b|javascript\s*:|on[a-z]+\s*=",
	re.IGNORECASE,
)
MAX_TRANSLATION_LENGTH = 20000
MAX_CONTEXT_LENGTH = 140


def placeholder_tokens(text: str) -> list[str]:
	found = []
	for token in PLACEHOLDER_RE.findall(text or ""):
		if token.startswith("{") and token.endswith("}") and not token.startswith("${"):
			inner = token[1:-1].strip()
			if inner.isdigit() or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", inner):
				token = "{" + inner + "}"
		found.append(token)
	return found


def html_tags(text: str) -> list[str]:
	return [match.group(1).lower() for match in TAG_RE.finditer(text or "")]


def translation_error(source: str, translated: str, context: str = "") -> str | None:
	"""Return a Persian error when a translation would break Frappe formatting."""
	source = source or ""
	translated = translated or ""
	context = context or ""
	if not translated.strip():
		return "ترجمه فارسی خالی ذخیره نمی‌شود."
	if len(translated) > MAX_TRANSLATION_LENGTH:
		return "ترجمه فارسی بیش از حد طولانی است."
	if len(context) > MAX_CONTEXT_LENGTH:
		return "زمینه (Context) طولانی‌تر از ۱۴۰ نویسه است و در DocType استاندارد Translation جا نمی‌شود."
	if FORBIDDEN_HTML_RE.search(translated):
		return "ترجمه فارسی شامل HTML غیرمجاز است."

	source_tokens = placeholder_tokens(source)
	translated_tokens = placeholder_tokens(translated)
	if sorted(source_tokens) != sorted(translated_tokens):
		missing = sorted(set(source_tokens) - set(translated_tokens))
		extra = sorted(set(translated_tokens) - set(source_tokens))
		detail = ""
		if missing:
			detail += " حذف‌شده: " + "، ".join(missing)
		if extra:
			detail += " اضافه‌شده: " + "، ".join(extra)
		return "نویسه‌های جایگزین ترجمه با متن اصلی هم‌خوان نیست." + detail

	source_tags = html_tags(source)
	if source_tags and sorted(source_tags) != sorted(html_tags(translated)):
		return "ساختار HTML ترجمه با متن اصلی هم‌خوان نیست."
	return None
