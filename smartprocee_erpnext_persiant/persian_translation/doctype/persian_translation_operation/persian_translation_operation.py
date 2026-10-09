"""Controller for the durable record of one Excel preview or apply operation."""

import frappe
from frappe.model.document import Document
from frappe.utils import now


class PersianTranslationOperation(Document):
	def validate(self):
		if self.status in ("Completed", "Partial", "Failed", "Cancelled"):
			self.finished_at = self.finished_at or now()
