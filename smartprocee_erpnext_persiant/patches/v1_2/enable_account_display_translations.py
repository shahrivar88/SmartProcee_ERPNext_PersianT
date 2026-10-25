from smartprocee_erpnext_persiant.persian_translation.account_display import (
	ensure_account_category_translated,
	ensure_call_logs_translation,
)


def execute():
	ensure_account_category_translated()
	ensure_call_logs_translation()
