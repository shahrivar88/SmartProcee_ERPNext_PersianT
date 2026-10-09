"""Frappe's own metadata, used to name what one translatable string is.

A string the scan recorded under ``DocType: Sales Invoice`` -- or under a file in
``.../doctype/sales_invoice/`` -- can be named exactly, because Frappe keeps the
answer: it is the label of a field, one option of a Select, a description, the
name of the document itself, or a permission role. Nothing here is guessed.

The lookups are batched per request. A page of the manager asks for the profiles
of the documents it is about to show and gets them in a fixed number of queries
instead of one query per row. Every value is read from the site's own records, so
the answer does not depend on the bench layout, on a build path, or on which
optional apps are installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import frappe

BATCH = 200
PROFILE_ATTR = "_persian_metadata_profiles"
ROLE_ATTR = "_persian_metadata_roles"

FIELD_TYPE = "Select"
HTML_TYPE = "HTML"


@dataclass
class Profile:
	"""One document, keyed the way the exact lookups below need it."""

	name: str
	module: str = ""
	description: str = ""
	labels: dict[str, set[str]] = field(default_factory=dict)
	options: set[str] = field(default_factory=set)
	descriptions: set[str] = field(default_factory=set)
	html_blocks: set[str] = field(default_factory=set)
	roles: set[str] = field(default_factory=set)

	def add_field(self, row) -> None:
		"""Record one ``DocField`` or ``Custom Field`` row."""
		label = (row.label or "").strip()
		if label:
			self.labels.setdefault(label, set()).add(row.fieldname or "")
		description = (row.description or "").strip()
		if description:
			self.descriptions.add(description)
		if row.fieldtype == FIELD_TYPE:
			self.options.update(select_options(row.options))
		elif row.fieldtype == HTML_TYPE and row.options:
			self.html_blocks.add(str(row.options).strip())

	def fieldnames(self, text: str) -> set[str]:
		"""Fieldnames whose label is exactly ``text``. Empty when it is not a label."""
		return {name for name in self.labels.get(text, set()) if name}

	def is_described(self, text: str) -> bool:
		return bool(text) and (
			text == self.description or text in self.descriptions or text in self.html_blocks
		)


def select_options(options) -> set[str]:
	"""The lines of a Select field that are real options.

	Frappe allows a first line such as ``$frappe.get_meta(...)`` and workflow
	states whose options are icon classnames; neither is translatable text.
	"""
	found = set()
	for line in str(options or "").splitlines():
		line = line.strip()
		if not line or line.startswith("$") or line.startswith("icon-"):
			continue
		found.add(line)
	return found


def profiles(names) -> dict[str, Profile]:
	"""Profiles for the given document names, reading only the ones not cached yet.

	Every name that has been asked about is remembered, including the ones this
	site has no document for. A folder slug that is not a DocType, or a doctype
	belonging to an app that is not installed, is a normal answer rather than an
	error -- and ``prefetch`` asks about every origin of every row, so a name that
	is not remembered here is re-queried once per row that mentions it.
	"""
	store = _store()
	wanted = {name for name in names if name}
	missing = sorted(name for name in wanted if name not in store)
	for start in range(0, len(missing), BATCH):
		_load(missing[start : start + BATCH], store)
	return {name: store[name] for name in wanted if store.get(name)}


def is_role(text: str) -> bool:
	"""Whether the string is the name of an existing Role."""
	return bool(text) and text in _role_names()


def _store() -> dict[str, Profile | None]:
	store = getattr(frappe.local, PROFILE_ATTR, None)
	if store is None:
		store = {}
		setattr(frappe.local, PROFILE_ATTR, store)
	return store


def _role_names() -> set[str]:
	names = getattr(frappe.local, ROLE_ATTR, None)
	if names is None:
		names = set(_pluck("Role"))
		setattr(frappe.local, ROLE_ATTR, names)
	return names


def _load(names: list[str], store: dict[str, Profile | None]) -> None:
	# Remember the question before answering it. A name with no document on this
	# site stays in the store as ``None``, so the next row that mentions it reads
	# that answer instead of repeating the four queries that produced it.
	for name in names:
		store.setdefault(name, None)
	for row in _rows("DocType", {"name": ["in", names]}, ["name", "module", "description"]):
		store[row.name] = Profile(
			name=row.name,
			module=row.module or "",
			description=(row.description or "").strip(),
		)
	for row in _rows(
		"DocField",
		{"parent": ["in", names]},
		["parent", "fieldname", "label", "options", "fieldtype", "description"],
	):
		profile = store.get(row.parent)
		if profile:
			profile.add_field(row)
	for row in _rows(
		"Custom Field",
		{"dt": ["in", names]},
		["dt", "fieldname", "label", "options", "fieldtype", "description"],
	):
		profile = store.get(row.dt)
		if profile:
			profile.add_field(row)
	for row in _rows("DocPerm", {"parent": ["in", names]}, ["parent", "role"]):
		profile = store.get(row.parent)
		if profile and row.role:
			profile.roles.add(row.role)


def _rows(doctype: str, filters: dict, fields: list[str]):
	"""Read metadata rows, treating a missing table on an odd install as "nothing known".

	Naming a string must never be the reason a page fails to render.
	"""
	try:
		return frappe.get_all(doctype, filters=filters, fields=fields, limit_page_length=0)
	except Exception:
		return []


def _pluck(doctype: str) -> list[str]:
	try:
		return frappe.get_all(doctype, pluck="name", limit_page_length=0)
	except Exception:
		return []
