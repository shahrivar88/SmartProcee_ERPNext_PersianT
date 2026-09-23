app_name = "smartprocee_erpnext_persiant"
app_title = "SmartProcee_ERPNext_PersianT"
app_publisher = "Smart Process"
app_description = "Portable Persian translations and Yekan Bakh UI font for Frappe and ERPNext"
app_email = "info@smartprocess.local"
app_license = "mit"
required_apps = ["frappe", "erpnext"]

after_install = "smartprocee_erpnext_persiant.install.after_install"
before_uninstall = "smartprocee_erpnext_persiant.install.before_uninstall"
after_migrate = ["smartprocee_erpnext_persiant.install.sync_public_assets"]

app_include_css = ["/assets/smartprocee_erpnext_persiant/css/yekan_bakh.css?v=1"]
web_include_css = ["/assets/smartprocee_erpnext_persiant/css/yekan_bakh.css?v=1"]
