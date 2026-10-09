"""Whether this site's database matches the code that is running on it.

The manager pages are served from whatever app code sits on the bench, but a
DocType only exists in the database after ``bench migrate`` has created it. When
a site is upgraded in code but not migrated, the UI used to raise a raw
"DocType ... not found" from deep inside a query. This module is the one place
that answers "is the schema in step?" so the UI can say so in plain Persian
before it touches any table.

Every site on a bench loads the same app code, so this is the normal state of an
upgraded-but-not-yet-migrated site, not an exception. It is also what an
administrator sees when their browser is pointed at a different site than the
one they migrated.
"""

from __future__ import annotations

import functools

import frappe
from frappe.utils import escape_html

# The DocTypes the Translation Manager cannot work without. A Single still has a
# DocType record of its own, so it is checked the same way as the rest.
TRANSLATION_DOCTYPES = (
	"Persian Translation Source",
	"Persian Translation Operation",
	"Persian Translation Operation Error",
	"Persian Snapshot",
	"Persian Translation Ownership",
	"Persian Font Family",
)

# The DocTypes the RTL compatibility layer writes through. The runtime already
# tolerates their absence (see ``persian_rtl.settings``), but the settings screen
# and its diagnostics must say why they are empty instead of reporting a
# permission error.
RTL_DOCTYPES = (
	"Persian RTL Settings",
	"Persian RTL Adapter",
	"Persian RTL Exclusion",
)

REQUIRED_DOCTYPES = TRANSLATION_DOCTYPES + RTL_DOCTYPES

SCHEMA_TITLE = "ساختار پایگاه داده فارسی‌ساز نیاز به بروزرسانی دارد"
MIGRATE_HINT = "روی همین سایت دستور «bench migrate» را اجرا کنید تا جداول ساخته شوند."


def missing_doctypes(doctypes: tuple[str, ...] = REQUIRED_DOCTYPES) -> list[str]:
	"""The asked-about DocTypes this site does not have -- read once per request."""
	cache = getattr(frappe.local, "_persian_missing_doctypes", None)
	if cache is None:
		cache = frappe.local._persian_missing_doctypes = {}
	if doctypes not in cache:
		cache[doctypes] = [name for name in doctypes if not frappe.db.exists("DocType", name)]
	return cache[doctypes]


def is_ready(doctypes: tuple[str, ...] = REQUIRED_DOCTYPES) -> bool:
	return not missing_doctypes(doctypes)


def require_ready(doctypes: tuple[str, ...] = REQUIRED_DOCTYPES) -> None:
	"""Refuse with the real reason when the site has not been migrated."""
	absent = missing_doctypes(doctypes)
	if not absent:
		return
	listed = "، ".join(escape_html(name) for name in absent)
	frappe.throw(
		f"{SCHEMA_TITLE}.<br><br>DocTypeهای غایب: {listed}<br><br>{MIGRATE_HINT}",
		title=SCHEMA_TITLE,
	)


def guard(fn=None, *, doctypes: tuple[str, ...] = REQUIRED_DOCTYPES):
	"""Decorate a whitelisted endpoint so it refuses on an out-of-step schema.

	Usable bare (``@schema.guard``) for the whole schema, or scoped
	(``@schema.guard(doctypes=RTL_DOCTYPES)``) for one feature's tables.
	"""
	if fn is None:
		return functools.partial(guard, doctypes=doctypes)

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		require_ready(doctypes)
		return fn(*args, **kwargs)

	# A marker instead of `__wrapped__`: the framework's own decorators set that
	# attribute too, so it cannot tell our guard apart from `frappe.whitelist`.
	wrapper._persian_schema_guarded = True
	return wrapper
