"""Controller for the record of one string this app has written.

The record is a bookkeeping row: it exists so a restore knows which Persian rows
this app created, and what it last wrote there. It has no workflow of its own.
"""

from frappe.model.document import Document


class PersianTranslationOwnership(Document):
	pass
