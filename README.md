# Smart Process Persian

Portable Persian translation and UI-font app for Frappe and ERPNext 16.

The app contains 16,779 Persian translations and the Yekan Bakh font used by Desk, website and login pages. It also contains a reversible backup mechanism for pre-existing site-level Persian Translation records that would otherwise override the app catalogue. It does not patch Frappe or ERPNext source files.

Static font assets are copied to the shared `sites/assets` directory after installation and after every migration. This also supports Docker deployments where the web and backend processes run in different containers. Uninstall removes only this app's asset directory and restores the previous translations.

## Install

```bash
bench get-app /path/to/smart_process_persian
bench --site <site-name> install-app smart_process_persian
bench --site <site-name> migrate
bench --site <site-name> clear-cache
```

Restart the web and worker processes after installation.

### frappe_docker

Some `frappe_docker` layouts keep `/home/frappe/frappe-bench/assets` local to each container. In that layout, add `docker-compose.assets.example.yaml` to the Compose files, set `SMART_PROCESS_PERSIAN_PATH` to the host path of this repository, and recreate the `frontend` service. The read-only mount makes the CSS and font binaries available directly to nginx after every container recreation.

Example:

```bash
export SMART_PROCESS_PERSIAN_PATH=/absolute/path/to/smart_process_persian
docker compose -f compose.yaml -f docker-compose.assets.example.yaml up -d --force-recreate frontend
```

## Uninstall

```bash
bench --site <site-name> uninstall-app smart_process_persian
bench --site <site-name> clear-cache
```

Before uninstalling, the app restores any site-level Persian Translation records that existed before installation and were temporarily backed up because they conflicted with this catalogue.

## Font license

Yekan Bakh is a commercial font and must be used and redistributed according to the license held by the system owner. Keep a repository containing these binaries private unless that license explicitly permits public redistribution.
