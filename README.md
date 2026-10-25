# Persianizer (فارسی‌ساز)

Persian translation, font, and right-to-left (RTL) management for Frappe and ERPNext 16.

Persianizer is a Frappe app. Its install name is `smartprocee_erpnext_persiant`. Inside Desk it shows as `فارسی‌ساز`. It lets a System Manager review and edit the Persian translation of a site, move translations through Excel, choose the Persian UI font, and apply RTL layout to supported standalone Frappe apps. It keeps restore points, so each change can be reverted.

## Core capabilities

- **Persian Translation Manager.** One page that lists the translatable strings of the installed apps, with their current Persian value, status, app, and kind. You can search, filter, and edit Persian values in place.
- **Excel export and import.** Export the filtered list to a workbook, translate it offline, and import it again. The import shows a preview before it writes anything.
- **Background apply operations.** Long previews, imports, and restores run as background jobs. Progress is stored on the server, so a closed browser tab does not stop or break an operation.
- **Error reporting.** Each rejected or failed row is recorded with its reason. You can download the rows that were not applied as an error workbook, correct them, and import them again.
- **Snapshots and restore.** The app takes a restore point before each change that it makes. You can also take a snapshot manually, preview a restore, and then restore.
- **Persian font management.** The Font Manager lets you upload WOFF2 or WOFF font families that you have the right to use, review them, and activate one as the Persian UI font. The app does not include font files.
- **RTL compatibility management.** Adapters apply RTL layout to standalone Frappe apps that do not support RTL themselves. Frappe CRM is supported in this release.
- **No core modifications.** The app does not change Frappe, ERPNext, or other app files. It uses only documented Frappe hooks.

## Requirements

- Frappe Framework 16
- ERPNext 16
- The Python version that your Frappe 16 bench requires
- Python packages `openpyxl`, `fonttools`, and `brotli`. `bench get-app` installs them.
- Optional: Frappe CRM, for the CRM RTL adapter

See [docs/FRAPPE_COMPATIBILITY.md](docs/FRAPPE_COMPATIBILITY.md) for the Frappe and ERPNext versions this release claims, and for checks that are still `NOT VERIFIED`.

## Documentation

| Audience | Document |
|---|---|
| End users (Persian) | [docs/USER_GUIDE.fa.md](docs/USER_GUIDE.fa.md) |
| Site administrators | [docs/ADMINISTRATION.md](docs/ADMINISTRATION.md) |
| Developers and AI agents | [AGENTS.md](AGENTS.md), [docs/DEVELOPER.md](docs/DEVELOPER.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Testers | [docs/TESTING.md](docs/TESTING.md) |
| Version matrix | [docs/FRAPPE_COMPATIBILITY.md](docs/FRAPPE_COMPATIBILITY.md) |
| Security reports | [SECURITY.md](SECURITY.md) |

`AGENTS.md` is the engineering contract. Do not copy it into other tool files.

## Installation

```bash
bench get-app https://github.com/shahrivar88/SmartProcee_ERPNext_PersianT
bench --site <site-name> install-app smartprocee_erpnext_persiant
bench --site <site-name> migrate
```

Restart the web and worker processes after the installation. On the first installation, the app records an immutable `install_baseline` snapshot of the Persian state of the site.

## Upgrade

Take a site backup before you upgrade.

```bash
cd apps/smartprocee_erpnext_persiant && git pull
cd ../..
bench --site <site-name> clear-cache
bench --site <site-name> migrate
```

Restart the web and worker processes after the migration.

- Your Persian `Translation` rows stay in place.
- On a site that had an earlier version, the first migration records an immutable `adopted_state` snapshot. This snapshot is the state when this version started to manage the site. It is not a pre-install baseline.
- The upgrade patches remove only objects of earlier versions that are no longer used: an empty legacy sidebar, an empty legacy table, and an unused column. A legacy sidebar or table that still holds data is kept. A second migration does not change anything.
- When you upgrade from 1.0.0, clear the cache before the migration, as shown above.

## Basic usage

1. Log in as a System Manager.
2. Open `فارسی‌ساز` from the Desk home icon. The Apps switcher and the header Modules menu do not list this app. The contextual Sidebar then offers Translation Manager, Font Manager and RTL Settings.
3. Start a scan to load the translatable strings of the installed apps.
4. Search and filter the list. Edit a Persian value, then save.
5. Use the backup section to see restore points, take a manual snapshot, or restore.

Only a System Manager can open the pages or call the APIs of this app.

## Excel workflow

1. Filter the list, then export it to Excel. A full export runs as a `long` background job. The download is a private file that only the owner can read. The workbook has one sheet for each app.
2. Edit only the Persian translation column. The other columns give context. The two technical columns at the end identify each row. Do not change them.
3. Import the workbook. The app first shows a preview with the number of rows that will be applied, that are unchanged, and that are rejected.
4. Apply the import. The app takes a restore point, then applies the rows in batches in the background.
5. If some rows are rejected or fail, download the error workbook. It shows the reason for each row.

A row is rejected when its identity does not match its source text and context, or when the Persian value breaks the placeholders, HTML, or template syntax of the source text. Cell values that a spreadsheet could run as formulas are neutralized in exported workbooks.

Import a workbook that the same version of the app exported.

## Font Manager

The Font Manager page controls the Persian UI font of Desk.

- The app does not include font files. When no family is active, Desk uses its default font stack.
- You can upload a font family as WOFF2 or WOFF files. TTF and OTF files are refused with a message. Convert them to WOFF2 first.
- After an upload, review the detected weights and styles, then activate the family.
- `بازگشت به فونت پیش‌فرض` (reset to the default font) deactivates the uploaded family. Desk then uses its default font stack.
- The active family cannot be deleted. Reset or activate another family first.
- The app takes a restore point before each font change.

The font stylesheets apply only to pages whose language is Persian (`fa`). Other languages keep their own fonts. RTL layout does not depend on the font.

Releases before 1.2.0 included a font and registered it as a font family. When you upgrade, a migration patch removes that family. If it was the active font, Desk returns to its default font stack. To use a font again, upload a font that you hold a license for.

**Font licenses.** Upload only fonts that you have the right to use and serve from your site. Many font licenses limit web embedding and redistribution. This project does not grant a license for any third-party font. You are responsible for complying with the license of each font that you upload.

## RTL compatibility

Some standalone Frappe apps render their own page and do not support RTL. RTL adapters add the RTL direction and a mirrored stylesheet to these pages.

- Open the `Persian RTL Settings` document to turn RTL support on, and to turn each adapter on or off.
- The **CRM** adapter is supported.
- The **Insights** and **Raven** adapters detect and diagnose their apps, but they do not change those pages yet.
- An adapter changes a page only when the user language is Persian, the adapter is on, and the installed app version is one that the adapter was checked against. You can override the version check for one adapter.
- You can add CSS selectors that the RTL stylesheet must not change.
- Diagnostic mode shows why an adapter did or did not apply to a page.

## Backup and restore

A snapshot records only the state that this app manages:

- all Persian (`fa`) `Translation` rows,
- the font families and the active font,
- the `Persian RTL Settings`.

Business documents, other languages, and data of other apps are never read into a snapshot and are never changed by a restore.

| Snapshot | When it is made | Pruned |
| --- | --- | --- |
| `install_baseline` | First installation | Never |
| `adopted_state` | First migration of a site that had an earlier version | Never |
| `manual` | When you take a snapshot | Never |
| `pre_apply`, `pre_font`, `pre_rtl`, `pre_restore` | Automatically, before each change | The latest 20 of each kind are kept |

A restore has two modes:

- **Values** restores the values in the snapshot and keeps rows that were added after it.
- **Full** also removes rows that were added after the snapshot, but only rows that this app wrote and that still hold the value that the app wrote. A translation that a person entered or changed is kept and shown in the report.

Font families are removed by a restore only when you select that option. Always preview a restore before you run it.

## Permissions and security

- All pages and APIs require the System Manager role. No API of this app is open to guests.
- APIs that change data accept only POST requests, so Frappe's CSRF protection applies.
- Imported values are validated before they are written.
- Uploaded fonts must be valid WOFF2 or WOFF files. Upload size and file count are limited. Font files are stored with fixed, app-managed names in the site's public files folder.
- Only one apply or restore can write at a time. The database enforces this with a lease.
- The automated tests and the `checks.run` harness create and remove data. Do not run them on a production site. `checks.run` refuses to run unless the site configuration contains both `allow_tests` and `persianizer_allow_destructive_checks`.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## Uninstall

```bash
bench --site <site-name> uninstall-app smartprocee_erpnext_persiant
bench --site <site-name> clear-cache
```

Uninstall removes:

- the app's DocTypes and their tables, which include all snapshots and operation history,
- the pages, home icon, and Desk menu item,
- the font files that the app wrote to the site, and the font stylesheet link in the site configuration,
- the RTL injection and the font stylesheets. They stop at once.

Uninstall keeps:

- **Persian `Translation` rows.** They are normal Frappe data and the site continues to use them. To return to the Persian state before installation, restore the `install_baseline` snapshot in **Full** mode *before* you uninstall.
- **The shared asset copy under `sites/assets/smartprocee_erpnext_persiant`.** All sites on the bench share this folder, so one site's uninstall does not delete it. Delete it manually after you remove the app from the bench.
- **Frappe's patch log entries** for this app. Frappe keeps them for every app.

Uninstall also restores translation rows that earlier versions had backed up, but only when the same key is missing.

## Known limitations

- The user interface of the app is in Persian.
- RTL layout is available only for Frappe CRM. Insights and Raven are not styled yet.
- The CRM adapter overrides CRM's stylesheet. It cannot rewrite it. When one element has two left/right utilities of the same kind, the result can be wrong. Check CRM visually after each CRM upgrade.
- CRM `Incoming` call-log cells and the frappe-ui `Load More` footer may stay English. The catalogue has those strings. The upstream UI does not look them up.
- Automatic restore points are taken while the request runs. On a site with a very large Persian catalogue, a font or RTL change can take a few seconds longer.
- The app manages Persian (`fa`) only.

## Compatibility and upgrade policy

**Version 1.x** is a maturity and testing period. The architecture can still change. Each change of stored data comes with a migration patch, and the changelog describes it.

**Version 2.0.0** is the planned architecture-stability milestone. It is not released yet. From version 2.0.0:

- the core architectural contracts become stable,
- each later breaking change is disclosed explicitly,
- the migration impact of each change is documented,
- an incompatible architectural change comes with clear release notes and, when appropriate, a new major version.

See [CHANGELOG.md](CHANGELOG.md) for the changes in each release.

## License

Copyright (C) Smart Process.

This program is free software, licensed under the GNU General Public License version 3 or any later version (`GPL-3.0-or-later`). See [LICENSE](LICENSE) for the full text.

You may use, study, modify, and distribute this software, including for commercial purposes, under the terms of that license. If you distribute the software or a modified version, you must do so under the same license and make the source code available.

Releases before 1.2.0 were published under the MIT License.

**Fonts.** This project does not include font files and does not grant a license for any third-party font. Fonts that you upload stay under their own licenses. See "Font licenses" in the [Font Manager](#font-manager) section.

## Credits

This software was commissioned by Smart Process (شرکت پردازش هوشمند).

AI-assisted tools and models, including ChatGPT, DeepSeek, Cursor, and Claude, were used during the analysis, development, review, and testing of this software. The providers of these tools did not sponsor, endorse, or author this project. All product names are trademarks of their owners.

## Disclaimer

This software is provided "as is", without warranty of any kind, express or implied, as stated in the GNU General Public License.

You are responsible for testing the software in your own environment, for taking backups, and for validating its results before you use it in production.

To the extent permitted by applicable law, the authors, the commissioning organization, and the contributors are not liable for data loss, business interruption, or any direct or indirect damages that result from the use of, or the inability to use, this software.
