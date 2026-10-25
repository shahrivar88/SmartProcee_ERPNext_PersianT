# Administration

Install and upgrade commands also live in [README.md](../README.md). This file covers site operations. End-user steps live in [USER_GUIDE.fa.md](USER_GUIDE.fa.md).

Replace `<site-name>` with your site. The examples do not name a real host, port or container.

## Who can use the app

Only a System Manager can open the pages or call the APIs.

Ordinary Desk users do not need a new role. They see the Persian UI after a System Manager applies translations and, if wanted, a font or RTL setting.

## Install

```bash
bench get-app <repository-url>
bench --site <site-name> install-app smartprocee_erpnext_persiant
bench --site <site-name> migrate
```

Restart the web and worker processes. The first install writes an immutable `install_baseline` snapshot of the Persian state.

On a Gunicorn bench that uses `--preload`, a cache clear is not enough after a `hooks.py` change. Restart the web workers so they import the new hooks. Then ask users to reload Desk. A stale `bootinfo` cache can keep an old dock list until that restart.

## Upgrade

Take and verify a site backup first.

```bash
cd apps/smartprocee_erpnext_persiant && git fetch --tags && git checkout <tag>
cd ../..
bench --site <site-name> clear-cache
bench --site <site-name> migrate
```

Restart the web and worker processes.

- Persian `Translation` rows stay in place
- A site that had an earlier version gets an immutable `adopted_state` snapshot on the first migration of this line
- This app ships one contextual Sidebar. Uninstall removes leftover Sidebar rows for its modules
- When you upgrade from 1.0.0, clear the cache before migrate

Do not skip backup. Do not migrate several sites at once until the first site is verified.

## After install or upgrade

1. Log in as System Manager.
2. Open `فارسی‌ساز` from the home icon.
3. Run a scan.
4. Use the contextual Sidebar for Font Manager and RTL Settings.

## Backup

A Frappe site backup is the recovery path for the whole site.

Persianizer snapshots are not a site backup. They store only:

- Persian (`fa`) `Translation` rows
- font families and the active font
- `Persian RTL Settings`

Restore a snapshot only after you preview it. Use **Full** mode only when you intend to drop rows that this app wrote after that snapshot.

## Uninstall

Restore `install_baseline` in Full mode before uninstall if you want the Persian state from before install.

```bash
bench --site <site-name> uninstall-app smartprocee_erpnext_persiant
bench --site <site-name> clear-cache
```

Uninstall keeps Persian `Translation` rows. It removes this app's DocTypes, pages, home icon, navbar item, managed font files, and leftover Sidebar rows for its modules.

The shared folder `sites/assets/smartprocee_erpnext_persiant` is bench-wide. Delete it by hand after every site on the bench has uninstalled the app.

## Assets on split frontend containers

Some Docker layouts keep Desk assets in a frontend container. See `docker-compose.assets.example.yaml`. Point `SMARTPROCEE_ERPNEXT_PERSIANT_PATH` at the app checkout on that host. Do not commit a compose file that names a real machine path.

## What must not enter the repository

Do not commit site backups, snapshots, operational Excel exports, uploaded fonts, `site_config.json`, logs, or translations taken from third-party or custom apps on a live site.
