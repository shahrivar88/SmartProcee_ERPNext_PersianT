# Frappe compatibility

Declared range in `pyproject.toml`:

- Frappe `>=16.0.0,<17.0.0`
- ERPNext `>=16.0.0,<17.0.0`

`required_apps = ["frappe", "erpnext"]`

Frappe 14, 15 and 17 are unsupported.

Do not treat a later v16 release as supported until this matrix records a real run.

## Compatibility matrix

| Environment | Frappe | ERPNext | CRM | Status |
|---|---|---|---|---|
| Docker development bench | 16.35.0 | 16.35.0 | 1.85.1 when installed | Source and automated tests for 1.2.1 |
| Owner Ubuntu operational bench | 16.53.0 | 16.52.1 | 1.89.1 (`frappe/crm` tag `v1.89.1`, commit `5e1df8c`) | Target. This release does not include an Ubuntu deploy. Live browser on Ubuntu is `NOT VERIFIED` |
| Docker `SmartProcessERP` | 16.53.0 | 16.52.1 | 1.89.1 | Migrated and browser-checked for 1.2.1. Automated tests ran on `ptm_clean_test2` |
| Earlier Ubuntu report | 16.52.0 | 16.51.1 | unknown | Superseded as the operational target |
| Frappe Cloud | — | — | — | `NOT VERIFIED` |
| Website / portal outside Desk | — | — | — | `NOT VERIFIED` |

Optional apps:

| App | Role | Adapter range in code | Page change |
|---|---|---|---|
| CRM | RTL | `1.85.0`–`1.89.99` | Yes, when enabled and the user language is `fa` |
| Insights | Detect only | `3.14.0`–`3.15.99` | No |
| Raven | Detect only | `3.0.0`–`3.0.99` | No |

## Confirmed incompatibility class

v1.2.0 selected `app` on Workspace, Workspace Sidebar and Desktop Icon. Some Frappe 16 sites do not have that column. Result: `Unknown column 'app' in 'SELECT'`.

This is an application schema assumption. Do not add `app` to those core tables. Scan only columns that exist.

## Version-sensitive APIs and schema

| Item | Assumption | Safe handling |
|---|---|---|
| Workspace / Sidebar / Desktop Icon `app` | Present on some 16.x sites, absent on others | `has_column`; never SELECT a missing field |
| Desk DocType title | `__(name)` only if `translated_doctype` | Ship `translated_doctype: 1` on this app's DocTypes |
| Gettext | Boot reads MO, not PO | Compile `locale/fa.po` on install and migrate |
| Account list | Frappe 16.35 list view uses `formatters[fieldname]`, not singular `formatter` | Do not treat the unused singular formatter as an HTML sink |
| CRM list resize | CRM 1.85 / 1.89 `ListHeaderItem` still uses `clientX` | RTL-only, drag-only invert of `clientX` |
| CRM nav labels | 1.85: `const links` in `AppSidebar.vue`. 1.89: `navigationItems` in `frontend/src/utils/navigation.js` | Scan both files |
| CRM HTML entry | 1.85 and 1.89 have no `crm/www/crm.html`. Page is `crm/www/crm.py` | Detect `crm.py` or `frontend/index.html`. Inject via `after_request` |
| Account Category | `translated_doctype` Property Setter | Write only when none exists |
| Desktop Icon `link_type` | 16.53 accepts Workspace Sidebar or External. `Page` is obsolete | Ship External + `/app/persian-translation-manager`. Keep Page only when that option still exists |
| Desktop Icon nesting | 16.53 hides children whose `parent_icon` is not a visible top-level icon | Persianizer icon is top-level (`parent_icon` empty) |
| Dock labels | `dock.js` renders `entry.label` without `__()` | `boot_session` translates display `label`/`title` when `lang` is `fa` |
| Private File download | `/private/files/` uses `File.is_downloadable` → attached document `read` | Excel exports stay unattached and a File `has_permission` hook refuses non-owners |

## Required integration evidence for a release

- Fresh install on a disposable database without this app's historical index
- Native Persian Desk labels before any scan
- Real text scan
- Excel export and preview
- Font Manager and RTL settings pages
- English session isolation
- Upgrade from `v1.2.0`
- Repeated migrate
- Uninstall safety for the changed surface

Mark each item Verified, Simulated or Not tested. Do not claim Ubuntu 16.52 compatibility without a live run on that bench.

## Dependencies

Python: `openpyxl>=3.1`, `fonttools>=4.50`, `brotli>=1.1`.

No bundled fonts. User-uploaded fonts are site files.
