"""A readable answer to "where is this text used, and what is it?".

The scan stores *every* place a string was found, joined into one
``source_path`` field. Those places mix three different kinds of fact:

* a name Frappe itself wrote -- ``DocType: Sales Invoice``, ``Sidebar: Stock``
* an extractor note describing the role -- ``(Label of a field in ...)``
* a build path -- ``apps/crm/crm/public/frontend/assets/Persona-a1b2c3.js``

Only the first two become a location. A build path is turned into a document,
report, page or web-form name when that record still exists on this bench, and it
is reported as an unreadable code file when it does not: a guess is never
presented as a fact, and no absolute path or hashed asset name ever reaches the
screen.

The same evidence decides the kind of the text, so the two columns can never
disagree about the same string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import frappe

from smartprocee_erpnext_persiant.persian_translation import kind, metadata

# Ranks are a preference order between the places one string was found in: a
# field of a document is a better answer than "some file in the document folder".
FIELD_RANK = 10
DOCTYPE_RANK = 12
REPORT_RANK = 20
PAGE_RANK = 25
WEB_FORM_RANK = 28
DOCTYPE_CODE_RANK = 30
WORKSPACE_RANK = 40
SIDEBAR_RANK = 45
DESK_RANK = 50
CLIENT_RANK = 80
SERVER_RANK = 85

FRONTEND_HINTS = ("/public/", "/dist/", "/assets/", "/build/", "/node_modules/")
FILE_SUFFIXES = (".py", ".js", ".ts", ".html", ".vue", ".json", ".css", ".jsx", ".tsx")

DOCTYPE_ORIGIN = re.compile(r"^DocType:\s*(?P<name>.+)$")
DOCTYPE_FOLDER = re.compile(r"/doctype/(?P<name>[^/]+)/")
REPORT_NAME = re.compile(r"/report/(?P<name>[^/]+)/")
PAGE_NAME = re.compile(r"/(?:page|www)/(?P<name>[^/]+)")
WEB_FORM_NAME = re.compile(r"/web_form/(?P<name>[^/]+)")
WWW_NAME = re.compile(r"/www/(?P<name>[^/]+)")

# Origin prefixes this app writes itself, mapped to the label and kind to show.
HEAD_LABELS = (
	("workspace sidebar item", ("Sidebar", SIDEBAR_RANK, kind.MENU)),
	("workspace sidebar title", ("Sidebar", SIDEBAR_RANK, kind.MENU)),
	("workspace sidebar", ("Sidebar", SIDEBAR_RANK, kind.MENU)),
	("workspace link description", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("workspace link", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("workspace shortcut", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("workspace chart", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("workspace number card", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("workspace quick list", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("workspace content", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("workspace title", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("workspace", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("desktop icon", ("Desktop Icon", DESK_RANK, kind.MENU)),
	("navbar", ("Navbar", DESK_RANK, kind.MENU)),
)

# Desk folders whose files this app scans directly.
DESK_FOLDERS = (
	("workspace_sidebar", ("Sidebar", SIDEBAR_RANK, kind.MENU)),
	("workspace", ("Workspace", WORKSPACE_RANK, kind.MENU)),
	("desktop_icon", ("Desktop Icon", DESK_RANK, kind.MENU)),
	("web_form", ("Web Form", WEB_FORM_RANK, kind.WEB_FORM)),
	("module_onboarding", ("Onboarding", PAGE_RANK, kind.PAGE)),
	("onboarding_step", ("Onboarding", PAGE_RANK, kind.PAGE)),
)


@dataclass(frozen=True)
class Place:
	"""Where one string is used, and the kind of text it is."""

	label: str = ""
	kind: str = kind.UNKNOWN
	others: int = 0

	@property
	def readable(self) -> bool:
		return bool(self.label)


@dataclass(frozen=True)
class _Candidate:
	rank: int
	label: str
	kind: str


def resolve(source_path: str, source_text: str = "", context: str = "") -> Place:
	"""The best place this string could be proven to be used, plus its kind."""
	candidates = [place for place in (_candidate(origin, note, source_text) for origin, note in origins(source_path)) if place]
	best = min(candidates, key=lambda item: item.rank) if candidates else None
	label = best.label if best else ""
	label_kind = kind.from_context(context) or kind.from_note(note_of(source_path))
	if not label_kind:
		label_kind = best.kind if best else _kind_without_place(source_path)
	return Place(label=label, kind=label_kind, others=len({item.label for item in candidates if item.label != label}))


def prefetch(source_paths) -> None:
	"""Load the document metadata a whole page of rows is about to ask for."""
	names = set()
	for path in source_paths:
		names.update(doctype_names(path))
	if names:
		metadata.profiles(names)


def doctype_names(source_path: str) -> set[str]:
	"""Every document this origin list refers to, named as Frappe names it."""
	names = set()
	for origin, _note in origins(source_path):
		found = DOCTYPE_ORIGIN.match(origin)
		if found:
			names.add(found.group("name").split("(")[0].strip())
			continue
		slug = _first(DOCTYPE_FOLDER, origin)
		if slug:
			names.add(unscrub(slug))
	return {name for name in names if name}


def origins(source_path: str):
	"""Yield ``(path, note)`` for every recorded origin, splitting the joined field."""
	for segment in (source_path or "").split("|"):
		segment = segment.strip()
		if not segment:
			continue
		path, note = _split_note(segment)
		if path:
			yield path, note


def note_of(source_path: str) -> str:
	for _path, note in origins(source_path):
		if note:
			return note
	return ""


def location_for(source_path: str) -> tuple[str, int]:
	"""``(label, count of unreadable origins)``. Kept for diagnostics and tests."""
	place = resolve(source_path)
	unreadable = sum(1 for origin, note in origins(source_path) if _candidate(origin, note, "") is None)
	return place.label, unreadable


def readable(source_path: str) -> bool:
	return bool(resolve(source_path).label)


def unscrub(name: str) -> str:
	"""``sales_invoice`` -> ``Sales Invoice``, using Frappe's own convention."""
	return frappe.unscrub(name) if name else ""


def _split_note(segment: str) -> tuple[str, str]:
	"""``apps/x/y.json (Label of a field)`` -> ``('apps/x/y.json', 'Label of a field')``."""
	if not segment.endswith(")") or " (" not in segment:
		return segment, ""
	path, _separator, rest = segment.rpartition(" (")
	return path.strip(), rest[:-1].strip()


def _candidate(origin: str, note: str, source_text: str) -> _Candidate | None:
	structural = _structural(origin, source_text)
	if structural:
		return structural
	return _from_path(origin, source_text)


def _structural(origin: str, source_text: str) -> _Candidate | None:
	"""Names Frappe wrote directly, so they are facts rather than conclusions."""
	found = DOCTYPE_ORIGIN.match(origin)
	if found:
		name = found.group("name").strip()
		# A document that no longer exists is still a fact the scan recorded.
		return _document(name, source_text, DOCTYPE_RANK, kind.OTHER) or _Candidate(
			DOCTYPE_RANK, name, kind.OTHER
		)
	head, _separator, tail = origin.partition(":")
	head = head.strip().casefold()
	tail = tail.strip()
	for prefix, (label, rank, label_kind) in HEAD_LABELS:
		if head == prefix:
			return _Candidate(rank, f"{label}: {tail}" if tail else label, label_kind)
	return None


def _from_path(origin: str, source_text: str) -> _Candidate | None:
	name = _first(DOCTYPE_FOLDER, origin)
	if name:
		document = _document(unscrub(name), source_text, DOCTYPE_CODE_RANK, kind.CODE)
		if document:
			return document
	name = _first(REPORT_NAME, origin)
	if name and unscrub(name) in _known("Report"):
		return _Candidate(REPORT_RANK, f"Report: {unscrub(name)}", kind.REPORT)
	name = _first(WEB_FORM_NAME, origin)
	if name:
		return _Candidate(WEB_FORM_RANK, f"Web Form: {unscrub(name)}", kind.WEB_FORM)
	name = _first(PAGE_NAME, origin)
	if name and name in _known("Page"):
		return _Candidate(PAGE_RANK, f"Page: {name}", kind.PAGE)
	name = _first(WWW_NAME, origin)
	if name:
		return _Candidate(PAGE_RANK, f"Web Page: {_without_suffix(name)}", kind.PAGE)
	folder = _desk_folder(origin)
	if folder:
		return folder
	if _looks_like_source_file(origin):
		return _code_area(origin)
	return None


def _document(name: str, source_text: str, rank: int, fallback: str) -> _Candidate | None:
	"""Where a string belonging to one document sits, or ``None`` when unknown.

	``fallback`` is the kind to use when the document exists but the string is not
	one of its labels, options or descriptions: the document's own code, or an
	undecided string.
	"""
	profile = metadata.profiles([name]).get(name)
	if profile is None:
		return None
	if source_text and source_text in (name, unscrub(name)):
		return _Candidate(rank, name, kind.DOCUMENT)
	role = _role_in(profile, name, source_text)
	if role:
		return role
	return _Candidate(rank, name, fallback)


def _role_in(profile: metadata.Profile, name: str, source_text: str) -> _Candidate | None:
	"""The role of one string inside one document, when Frappe's metadata decides it."""
	if not source_text:
		return None
	fields = profile.fieldnames(source_text)
	if fields:
		# A label shared by two fields of the same document is still a field, but
		# it cannot be narrowed to one fieldname.
		label = f"{name}.{next(iter(fields))}" if len(fields) == 1 else name
		return _Candidate(FIELD_RANK if len(fields) == 1 else DOCTYPE_RANK, label, kind.FIELD)
	if source_text in profile.options:
		return _Candidate(DOCTYPE_RANK, name, kind.OPTION)
	if profile.is_described(source_text):
		return _Candidate(DOCTYPE_RANK, name, kind.DESCRIPTION)
	if source_text in profile.roles and metadata.is_role(source_text):
		return _Candidate(DOCTYPE_RANK, name, kind.ROLE)
	return None


def _desk_folder(origin: str) -> _Candidate | None:
	"""A scanned desk file such as ``erpnext/workspace_sidebar/selling.json``."""
	for folder, (label, rank, label_kind) in DESK_FOLDERS:
		found = re.search(rf"/{folder}/(?P<name>[^/]+)", origin)
		if found:
			name = _without_suffix(found.group("name"))
			return _Candidate(rank, f"{label}: {unscrub(name)}", label_kind)
	return None


def _code_area(origin: str) -> _Candidate:
	"""The honest answer for code that names no record: say which layer it is."""
	if any(hint in origin.casefold() for hint in FRONTEND_HINTS):
		return _Candidate(CLIENT_RANK, "کد رابط کاربری", kind.CODE)
	return _Candidate(SERVER_RANK, "کد سرور", kind.CODE)


def _kind_without_place(source_path: str) -> str:
	"""No origin could be read. An unreadable path is not the same as no path at all."""
	return kind.OTHER if (source_path or "").strip() else kind.UNKNOWN


def _first(pattern: re.Pattern, origin: str) -> str:
	found = pattern.search(origin)
	return found.group("name").strip() if found else ""


def _looks_like_source_file(origin: str) -> bool:
	return origin.casefold().endswith(FILE_SUFFIXES)


def _without_suffix(name: str) -> str:
	stem, dot, _suffix = name.rpartition(".")
	return stem if dot and stem else name


def _known(doctype: str) -> set[str]:
	"""Names that exist on this bench, read once per request.

	The lookup goes through the site's own records, so nothing depends on the
	bench layout and an uninstalled app simply answers "not known".
	"""
	store = getattr(frappe.local, "_persian_place_names", None)
	if store is None:
		store = {}
		setattr(frappe.local, "_persian_place_names", store)
	if doctype not in store:
		try:
			store[doctype] = set(frappe.get_all(doctype, pluck="name", limit_page_length=0))
		except Exception:
			store[doctype] = set()
	return store[doctype]
