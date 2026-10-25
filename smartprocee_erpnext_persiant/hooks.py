app_name = "smartprocee_erpnext_persiant"
app_title = "فارسی‌ساز"
app_publisher = "Smart Process"
app_description = "Persian translation, font, and RTL management for Frappe and ERPNext"
app_license = "GPL-3.0-or-later"
app_home = "/app/persian-translation-manager"
required_apps = ["frappe", "erpnext"]

# Not on the Apps screen or the header Apps switcher. The Desk home icon and
# the contextual Sidebar are the entry points. `on_apps_screen` is True only
# when this hook is present.
#
# Persian RTL stays code-only so this app has one navigable module. The
# Frappe 16.53 header then hides the Modules switcher. RTL Settings stay on
# the Persian Translation Sidebar. Older Frappe ignores this hook.
code_only_modules = {
	"Persian RTL": [],
}

after_install = "smartprocee_erpnext_persiant.install.after_install"
before_uninstall = "smartprocee_erpnext_persiant.install.before_uninstall"
after_migrate = [
	"smartprocee_erpnext_persiant.install.compile_native_translations",
	"smartprocee_erpnext_persiant.install.ensure_restore_point",
	"smartprocee_erpnext_persiant.install.sync_public_assets",
	"smartprocee_erpnext_persiant.desk_icon.ensure_home_icon",
	"smartprocee_erpnext_persiant.install.remove_navbar_item",
	"smartprocee_erpnext_persiant.persian_translation.account_display.ensure_display_translations",
	"smartprocee_erpnext_persiant.persian_translation.system_font.service.refresh_active_css",
	"smartprocee_erpnext_persiant.persian_rtl.settings.sync_from_registry",
]
boot_session = "smartprocee_erpnext_persiant.desk_boot.apply_boot_display_translations"

# Narrow File gate for Excel exports only. Unrelated Files are not restricted.
has_permission = {
	"File": "smartprocee_erpnext_persiant.permissions.file_has_permission",
}
permission_query_conditions = {
	"File": "smartprocee_erpnext_persiant.permissions.file_query_conditions",
}

# Account-only display helpers. Not desk-wide: no app_include_js / page_js.
doctype_js = {"Account": "public/js/account_display.js"}
doctype_list_js = {"Account": "public/js/account_display.js"}
doctype_tree_js = {"Account": "public/js/account_display.js"}

# The only supported place to adjust a response built by another application.
# See persian_rtl/runtime.py for the guard order and persian_rtl/inject.py for
# the additive edits it performs.
after_request = ["smartprocee_erpnext_persiant.persian_rtl.runtime.after_request"]
