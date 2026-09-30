# Persian Translation

Persian catalogue, Yekan Bakh font, and Persian Translation Manager for Frappe and ERPNext 16.

The install name is `smartprocee_erpnext_persiant`. The Frappe module name is `Persian Translation`.

## Requirements

- Frappe 16
- ERPNext 16
- Python 3.10 or newer

## Install

```bash
bench get-app https://github.com/shahrivar88/SmartProcee_ERPNext_PersianT
bench --site <site-name> install-app smartprocee_erpnext_persiant
bench --site <site-name> migrate
```

Restart web and workers after install. The Desk home and sidebar label is `فارسی‌ساز`. It opens the page `persian-translation-manager`. Only a System Manager can open that page or call its APIs.

## Update

```bash
cd apps/smartprocee_erpnext_persiant && git pull
cd ../..
bench --site <site-name> clear-cache
bench --site <site-name> migrate
```

Clear the cache before migrate when you update from version 1.0.0. That release used a module name Frappe cannot map to a Python package. The cache keeps the old name until you clear it. User Translation rows stay in place. Migrate refreshes the font copy under `sites/assets`.

## Uninstall

```bash
bench --site <site-name> uninstall-app smartprocee_erpnext_persiant
bench --site <site-name> clear-cache
```

Uninstall removes this app's DocTypes, page, sidebar, and home icon. It does not delete Frappe Translation rows. It restores older backup rows only when that same key is missing. It keeps the font copy under `sites/assets`, because all sites on the bench share that folder.

## Font license

Yekan Bakh is a commercial font. Redistribute the font files only under the license you hold.
