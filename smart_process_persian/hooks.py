app_name = "smart_process_persian"
app_title = "Smart Process Persian"
app_publisher = "Smart Process"
app_description = "Portable Persian translations and Yekan Bakh UI font for Frappe and ERPNext"
app_email = "info@smartprocess.local"
app_license = "mit"
required_apps = ["frappe", "erpnext"]

after_install = "smart_process_persian.install.after_install"
before_uninstall = "smart_process_persian.install.before_uninstall"
after_migrate = ["smart_process_persian.install.sync_public_assets"]

app_include_css = ["/assets/smart_process_persian/css/yekan_bakh.css?v=1"]
web_include_css = ["/assets/smart_process_persian/css/yekan_bakh.css?v=1"]
