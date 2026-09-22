# Smart Process Persian

Portable Persian translation app for Frappe and ERPNext 16.

The app contains translation resources and a reversible backup mechanism for pre-existing site-level Persian Translation records that would otherwise override the app catalogue. It does not patch or modify Frappe, ERPNext, or other custom-app source files.

## Install

```bash
bench get-app /path/to/smart_process_persian
bench --site <site-name> install-app smart_process_persian
bench --site <site-name> clear-cache
```

Restart the web and worker processes after installation.

## Uninstall

```bash
bench --site <site-name> uninstall-app smart_process_persian
bench --site <site-name> clear-cache
```

Before uninstalling, the app restores any site-level Persian Translation records that existed before installation and were temporarily backed up because they conflicted with this catalogue.
