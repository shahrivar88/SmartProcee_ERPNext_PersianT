app_name = "smart_process_persian"
app_title = "Smart Process Persian"
app_publisher = "Smart Process"
app_description = "Portable Persian translations for Frappe and ERPNext"
app_email = "info@smartprocess.local"
app_license = "mit"
required_apps = ["frappe", "erpnext"]

after_install = "smart_process_persian.install.after_install"
before_uninstall = "smart_process_persian.install.before_uninstall"
