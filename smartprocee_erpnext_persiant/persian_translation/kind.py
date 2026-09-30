"""Classify a discovered string from the origin Frappe actually recorded.

Extractor comments such as "Label of a field" are not runtime translation
context. They are only used here to name the kind of text.
"""

GENERIC_KINDS = {"پیام", "سند", "نامشخص"}

KIND_OPTIONS = (
	"منو",
	"میزکار",
	"متن میزکار",
	"میانبر",
	"نمودار",
	"کارت عددی",
	"فهرست سریع",
	"آیکون",
	"نوار بالا",
	"نام سند",
	"فیلد",
	"توضیح",
	"گزینه",
	"دکمه",
	"گزارش",
	"ستون گزارش",
	"صفحه",
	"فرم وب",
	"راهنما",
	"پیام",
	"سند",
	"نامشخص",
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


def is_extractor_comment(text: str) -> bool:
	lowered = (text or "").strip().casefold()
	return lowered.startswith(_COMMENT_PREFIXES)


def comment_text(value) -> str:
	if isinstance(value, (list, tuple)):
		parts = [str(item).strip() for item in value if str(item).strip()]
		return "; ".join(parts)
	if isinstance(value, str) and is_extractor_comment(value):
		return value.strip()
	return ""


def text_kinds(source_path: str, context: str = "") -> list[str]:
	found = []

	def add(label):
		if label and label not in found:
			found.append(label)

	ctx = (context or "").casefold()
	if "button" in ctx:
		add("دکمه")
	if "column of report" in ctx:
		add("ستون گزارش")

	for segment in (source_path or "").split("|"):
		segment = segment.strip()
		if not segment:
			continue
		lowered = segment.casefold()
		head = segment.split(":", 1)[0].strip().casefold()

		if head.startswith("workspace sidebar"):
			add("منو")
		elif head == "navbar":
			add("نوار بالا")
		elif head == "desktop icon":
			add("آیکون")
		elif head == "workspace link description":
			add("توضیح")
		elif head == "workspace link":
			add("منو")
		elif head == "workspace shortcut":
			add("میانبر")
		elif head == "workspace chart":
			add("نمودار")
		elif head == "workspace number card":
			add("کارت عددی")
		elif head == "workspace quick list":
			add("فهرست سریع")
		elif head == "workspace content":
			add("متن میزکار")
		elif head in ("workspace", "workspace title"):
			add("میزکار")
		elif "name of a doctype" in lowered:
			add("نام سند")
		elif "description of a doctype" in lowered:
			add("توضیح")
		elif "field in doctype" in lowered and "label of" in lowered:
			add("فیلد")
		elif "field in doctype" in lowered and ("description of" in lowered or "placeholder" in lowered):
			add("توضیح")
		elif "option for" in lowered:
			add("گزینه")
		elif "label of an action" in lowered or "action in the" in lowered:
			add("دکمه")
		elif "name of a report" in lowered:
			add("گزارش")
		elif "name of a workspace" in lowered or "title of a workspace" in lowered:
			add("میزکار")
		elif "workspace link" in lowered or "label of a link in" in lowered:
			add("منو")
		elif "sidebar" in lowered:
			add("منو")
		elif "navbar" in lowered:
			add("نوار بالا")
		elif "web form" in lowered:
			add("فرم وب")
		elif "onboarding" in lowered:
			add("راهنما")
		elif "number card" in lowered:
			add("کارت عددی")
		elif head == "doctype":
			add("سند")
		elif "/report/" in lowered:
			add("گزارش")
		elif "/page/" in lowered or "/www/" in lowered:
			add("صفحه")
		elif any(token in lowered for token in (".py", ".js", ".html", ".vue")):
			add("پیام")

	specific = [label for label in found if label not in GENERIC_KINDS]
	labels = specific or found or ["نامشخص"]
	return labels


def text_kind(source_path: str, context: str = "") -> str:
	return "، ".join(text_kinds(source_path, context))
