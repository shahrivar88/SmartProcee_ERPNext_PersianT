# Changelog

All notable changes to this project are documented in this file.

## [1.2.2]

### Desk navigation

- The Desk home icon stays. The app is no longer on the Apps screen or in the header Apps switcher (`add_to_apps_screen` is not declared).
- The header navbar row is removed. The home icon and the page routes remain the entry points.
- `Persian RTL` is `code_only_modules`. This app then has one navigable module, so the Frappe 16.53 Modules switcher stays hidden.
- `Persian Translation` stays navigable and ships a contextual `Sidebar` with Translation Manager, Font Manager and RTL Settings.

### Documentation

- Architecture, developer handoff, testing, administration and a Persian user guide now live under `docs/`.
- Public docs no longer name machine paths, site names, ports or internal hosts.

## [1.2.1]

### Translation Manager

- Text scan no longer fails on Frappe sites whose Workspace, Workspace Sidebar, or Desktop Icon tables have no `app` column. The scanner reads only columns that exist and still classifies each row by module or explicit app.
- If a required Persianizer column is missing, the manager explains the missing schema in Persian and asks for `bench migrate` on that site.

### Native Desk UI

- After install, a Persian session shows this app's own module and DocType names in Persian. The labels ship as Gettext (`locale/fa.po`) and are compiled on install and migrate. They are not added to the public `fa.csv` catalogue.

### Account display

- The Account Category translation flag is written only when the site has no Property Setter for it. An existing customization is left unchanged.

### Desk navigation

- Persianizer no longer ships a right-hand Workspace Sidebar. The home icon, Apps screen entry and navbar shortcut stay and open Translation Manager.
- The home icon is a top-level External Desktop Icon. Nested `Page` + `Framework` icons disappear on Frappe 16.53.
- A Persian boot session translates dock and sidebar display labels. Module identifiers stay English.

### Excel workflow

- A full translation export runs as a `long` background operation. The browser receives an operation id, then an owner-only private download.
- Export workbooks are private, unattached Files. Frappe's File download path and this app's File permission hook both refuse any user who is not the owner.

### Display labels

- Role titles that this catalogue cannot own (`Insights User`, `Raven Admin`, `Employee Self Service`) and CRM `Call Logs` ship as Translation rows. `Role`, `Customer` and `Supplier` get `translated_doctype` only when the site has no Property Setter for that flag.

### CRM

- The CRM RTL adapter accepts CRM 1.85.x through 1.89.x. Version 1.89.1 is no longer skipped as a mismatch.
- CRM 1.89.1 moved sidebar labels to `frontend/src/utils/navigation.js`. The scanner reads that file as well as the older `AppSidebar.vue` list.
- RTL and font injection follow the signed-in user's language when the CRM page request language is not Persian.
- The UserDropdown Apps submenu follows the document direction. The submenu caret points toward the panel.
- The Apps screen entry for this app now ships a logo.

### Known limitations

- CRM list cells that print `Incoming` and the frappe-ui `Load More` footer stay English. Those strings have catalogue rows, but the upstream UI does not call the translation lookup. This release does not rewrite CRM or frappe-ui.

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
