import frappe
from frappe.model.document import Document

# Desk, REST and the font manager all delete a family through these hooks, so
# the rules below hold whichever way the delete comes in.
SKIP_RESTORE_POINT = "persian_skip_restore_point"


class PersianFontFamily(Document):
	def on_trash(self):
		if self.is_active:
			frappe.throw(
				"این خانواده فونت فعال سیستم است. ابتدا «بازگشت به فونت پیش‌فرض» را بزنید.",
				frappe.ValidationError,
			)
		# A snapshot restore removes families inside an operation that already
		# recorded its own undo point; every other delete records one here.
		if not self.flags.get(SKIP_RESTORE_POINT):
			from smartprocee_erpnext_persiant.persian_translation import snapshots

			snapshots.capture(
				snapshots.PRE_FONT,
				f"پیش از حذف فونت «{self.family_name}»",
				note="برای برگرداندن وضعیت فونت به پیش از این تغییر.",
			)

	def after_delete(self):
		from smartprocee_erpnext_persiant.persian_translation import snapshots

		# After the commit, and only for files no face or snapshot still records.
		snapshots.release_font_files(face.file_url for face in self.faces)
