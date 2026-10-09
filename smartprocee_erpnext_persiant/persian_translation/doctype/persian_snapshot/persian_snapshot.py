"""Controller for one snapshot of Persianizer-owned state.

Immutability is enforced here, on the document, so it holds for every caller:
the manager page, the Desk form, the REST API and `frappe.db`. A snapshot that
is flagged immutable can be created once and then only read.

A plain delete stops at Frappe's link check while any operation names the
snapshot. A forced delete, which is what pruning does, is refused only while an
operation that still reads it is queued or running: a finished operation keeps
the name as history and never needs the snapshot to exist.
"""

import frappe
from frappe.model.document import Document

# Every field that carries the snapshot's content. An immutable snapshot may not
# change any of them; `modified` is the only field a save is allowed to touch.
CONTENT_FIELDS = (
	"kind",
	"label",
	"immutable",
	"captured_at",
	"captured_by",
	"schema_version",
	"translations_count",
	"fonts_count",
	"rtl_enabled",
	"note",
	"summary",
	"payload",
)


class PersianSnapshot(Document):
	def validate(self):
		before = self.get_doc_before_save()
		if self.is_new() or not before or not before.immutable:
			return
		if self.has_value_changed("immutable") and not self.immutable:
			frappe.throw("نسخهٔ پشتیبان تغییرناپذیر است و نمی‌توان قفل آن را باز کرد.")
		changed = [field for field in CONTENT_FIELDS if self.has_value_changed(field)]
		if changed:
			frappe.throw(
				"نسخهٔ پشتیبان تغییرناپذیر است و قابل ویرایش نیست: " + "، ".join(sorted(changed)[:5])
			)

	def on_trash(self):
		if self.immutable:
			frappe.throw("نسخهٔ پشتیبان تغییرناپذیر است و حذف نمی‌شود.")
		from smartprocee_erpnext_persiant.persian_translation import snapshots

		active = snapshots.active_operations_using(self.name)
		if active:
			frappe.throw(
				f"عملیات {active[0]} هنوز از این نسخهٔ پشتیبان استفاده می‌کند؛ پس از پایان آن حذف کنید."
			)

	def after_delete(self):
		# Runs for every delete, also one that skipped `on_trash`, so a font file
		# that only this snapshot kept is never left behind.
		from smartprocee_erpnext_persiant.persian_translation import snapshots

		snapshots.release_font_files(snapshots.font_urls_of_payload(self.payload))
