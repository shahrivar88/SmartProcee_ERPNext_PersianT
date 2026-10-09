# Changelog

All notable changes to this project are documented in this file.

## [1.2.0]

### Translation Manager

- The list can be sorted.
- Every write goes through one validated path that also records ownership. A value that breaks the placeholders, HTML, or template syntax of its source text is refused.

### Excel workflow

- Import previews and imports run as background operations. See "Background operations".
- Rows that were not applied can be downloaded as an error workbook, with the reason for each row.
- Exported and error workbooks store each cell as text, so a value that starts with `=` can never become a live spreadsheet formula.

### Background operations

- Import previews, imports, restore previews, and restores run as background jobs. Progress is stored on the server and survives a closed browser tab.
- Only one import or restore can write at a time. A database lease enforces this.
- An interrupted operation can be resumed. It continues from its stored plan, so no row is skipped or applied twice.

### Snapshots and restore

- New restore points: an immutable install baseline, an immutable adopted state for upgraded sites, manual snapshots, and automatic snapshots before each import, font change, RTL change, and restore.
- A restore can be previewed. It has a **Values** mode and a **Full** mode.
- Automatic snapshots are pruned to the latest 20 of each kind. Baseline, adopted-state, and manual snapshots are never pruned.

### Ownership safety

- The app records each translation that it writes and the value that it wrote.
- A full restore removes only rows that this app wrote and that still hold that value. A translation that a person added or changed is kept and reported.

### Font Manager

- Deleting a font family takes a restore point first. The active family cannot be deleted by any path.
- Font files are released only when no other family uses them.
- The active font stylesheet is regenerated on each migration.

### RTL infrastructure

- New `Persian RTL Settings` with RTL adapters for standalone Frappe apps.
- The Frappe CRM adapter adds RTL direction and a mirrored stylesheet to CRM for Persian users. It can also apply the Persian UI font to CRM.
- The Insights and Raven adapters detect and diagnose their apps. They do not change those pages yet.
- Adapter version checks, custom exclusions, and a diagnostic mode.

### Security hardening

- APIs that change data accept only POST requests.
- The destructive `checks.run` harness refuses to run unless the site explicitly allows it.

### Migration and uninstall

- Upgrade patches remove the empty legacy `Persian Translation` sidebar, the unused `Persian Translation Final` table when it is empty, and an unused operation column. Migration can be run again safely.
- Uninstall also removes the font files that the app wrote and the font stylesheet link, and RTL injection stops at once. Persian `Translation` rows are kept. See the README.

### License

- The project is now licensed under `GPL-3.0-or-later`. Earlier releases were published under the MIT License.

### Removed

- The app no longer includes the Yekan Bakh font files or their stylesheets. A migration patch removes the font family that earlier releases registered from them. If that family was active, the site returns to the default font stack. Upload a font that you hold a license for to use it again.

### Known limitations

- RTL layout is available only for Frappe CRM.
- Import workbooks that the same version of the app exported.

## [1.1.1]

- The `فارسی‌ساز` item shows in the Desk sidebar header menu.

## [1.1.0]

- Persian Translation Manager with per-app Excel export and import.
- System Font Manager with the bundled Yekan Bakh family and a reset action.
- The `فارسی‌ساز` desktop icon and workspace sidebar.
- `release_check` blocks catalogue rows whose owner is not Frappe or ERPNext.

## [1.0.0]

- The app was renamed to `smartprocee_erpnext_persiant`, and the Yekan Bakh font assets were bundled.
