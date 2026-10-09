"""The stable identity of one translatable string.

Frappe identifies a translation by (language, source_text, context). This app
only ever manages Persian, so (source_text, context) is the whole key. Both the
manager and every stored action derive from here, so they can never disagree
about what "the same string" means.
"""

import hashlib

SEPARATOR = "\x1f"


def translation_identity(source: str, context: str = "") -> str:
	return hashlib.sha256(f"{source}{SEPARATOR}{context or ''}".encode()).hexdigest()
