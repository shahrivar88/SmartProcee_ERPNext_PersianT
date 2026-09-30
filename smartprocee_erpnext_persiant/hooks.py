app_name = "smartprocee_erpnext_persiant"
app_title = "فارسی‌ساز"
app_publisher = "Smart Process"
app_description = "Portable Persian translations and Yekan Bakh UI font for Frappe and ERPNext"
app_email = "info@smartprocess.local"
app_license = "mit"
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
	"smartprocee_erpnext_persiant.install.sync_public_assets",
	"smartprocee_erpnext_persiant.persian_translation.system_font.bundled.register_bundled_family",
]

app_include_css = ["/assets/smartprocee_erpnext_persiant/css/yekan_bakh.css?v=1"]
web_include_css = ["/assets/smartprocee_erpnext_persiant/css/yekan_bakh.css?v=1"]
