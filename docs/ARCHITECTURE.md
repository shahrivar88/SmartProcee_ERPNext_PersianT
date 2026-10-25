# Architecture

This file maps the app. Development rules live in [AGENTS.md](../AGENTS.md). Version-sensitive APIs live in [FRAPPE_COMPATIBILITY.md](FRAPPE_COMPATIBILITY.md).

## Purpose

Persianizer is a Frappe app. It helps a System Manager manage Persian (`fa`) translations, the Persian UI font, and RTL layout for supported standalone apps. It does not post accounting or stock ledgers. It does not edit Frappe, ERPNext, CRM, Insights, Raven or any other app.

Install name: `smartprocee_erpnext_persiant`. Desk title: `فارسی‌ساز`.

## Modules

| Module Def | What it owns | Desk navigation |
|---|---|---|
| `Persian Translation` | Translation Manager, Font Manager, snapshots, operations, catalogue helpers | Navigable. Ships the contextual Sidebar `فارسی‌ساز` |
| `Persian RTL` | RTL settings and adapters | Code-only on Frappe 16.53+. Reachable from that Sidebar and by route |

Access is the home Desktop Icon and these routes:

- `/app/persian-translation-manager`
- `/app/persian-system-font-manager`
- `Persian RTL Settings` (Single DocType)

## Why three navigation surfaces exist

Frappe 16.53 keeps these sources apart:

| Surface | Source | This app |
|---|---|---|
| Desk home icon | `Desktop Icon` with `icon_type=Link` | Kept |
| Apps screen and header Apps switcher | `add_to_apps_screen` sets `on_apps_screen` | Not declared |
| Header Modules switcher | Shown only when the current app has more than one navigable module | Hidden by making `Persian RTL` code-only |
| Contextual Sidebar | `Sidebar` document under the navigable module | Shipped as `فارسی‌ساز` |
| Header navbar row | `standard_navbar_items` | Not declared |

`code_only_modules` on every module of this app would also drop the contextual Sidebar. That is why only `Persian RTL` is code-only.

Uninstall removes leftover Sidebar rows for these modules.

## Entry points

| Entry | Hook or artifact | Audience |
|---|---|---|
| Home icon | `desktop_icon/` fixture + `desk_icon.ensure_home_icon` | System Manager |
| Contextual Sidebar | `persian_translation/sidebar/فارسی‌ساز/` | System Manager |
| Page roles | Page and DocType permissions | System Manager |

Do not hide these entries with CSS or DOM edits.

## Runtime layers

| Layer | Path | Role |
|---|---|---|
| Translation Manager | `persian_translation/` | Scan, edit, Excel, snapshots, ownership |
| Public catalogue | `translations/fa.csv` | Frappe and ERPNext strings only |
| Native UI labels | `locale/fa.po` | This app's own Desk labels |
| Font Manager | `persian_translation/system_font/` | Upload and activate site fonts |
| RTL adapters | `persian_rtl/` | Additive `after_request` injection |
| Desk boot | `desk_boot.py` | Display-only label translation for `fa` |

## Data this app may write

- Its own DocTypes
- Persian `Translation` rows it is allowed to own
- Font files it created under the site files folder
- RTL settings it owns
- The standard home icon it installs

It must not write operational exports, customer workbooks, uploaded font binaries, site settings, snapshots, database dumps, backups, secrets or private logs into git.

## Frappe-native limits

These are not Persianizer bugs:

- CRM `Incoming` call-log cells and the frappe-ui `Load More` footer bypass `__()`
- Insights and Raven adapters detect only. They do not change those pages
- `code_only_modules` is ignored on Frappe builds that do not read the hook
- Hiding every module of this app also hides the contextual Sidebar. That coupling is native
- The Apps switcher and the home icon are separate when the icon is `icon_type=Link` and `add_to_apps_screen` is absent
