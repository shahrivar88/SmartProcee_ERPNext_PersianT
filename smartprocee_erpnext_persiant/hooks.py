app_name = "smartprocee_erpnext_persiant"
app_title = "فارسی‌ساز"
app_publisher = "Smart Process"
app_description = "Persian translation, font, and RTL management for Frappe and ERPNext"
app_license = "GPL-3.0-or-later"
app_home = "/app/persian-translation-manager"
required_apps = ["frappe", "erpnext"]

add_to_apps_screen = [
	{
		"name": app_name,
		"title": "فارسی‌ساز",
		"route": app_home,
		"has_permission": "smartprocee_erpnext_persiant.permissions.has_app_permission",
	}
]

standard_navbar_items = [
	{
		"item_label": app_title,
		"item_type": "Action",
		"action": f"frappe.set_route('persian-translation-manager', {{sidebar: '{app_title}'}})",
		"condition": "frappe.user.has_role('System Manager')",
		"icon": "languages",
		"is_standard": 1,
	}
]

after_install = "smartprocee_erpnext_persiant.install.after_install"
before_uninstall = "smartprocee_erpnext_persiant.install.before_uninstall"
after_migrate = [
	"smartprocee_erpnext_persiant.install.ensure_restore_point",
	"smartprocee_erpnext_persiant.install.sync_public_assets",
	"smartprocee_erpnext_persiant.persian_translation.system_font.service.refresh_active_css",
	"smartprocee_erpnext_persiant.persian_rtl.settings.sync_from_registry",
]

# The only supported place to adjust a response built by another application.
# See persian_rtl/runtime.py for the guard order and persian_rtl/inject.py for
# the two additive edits it performs.
after_request = ["smartprocee_erpnext_persiant.persian_rtl.runtime.after_request"]
