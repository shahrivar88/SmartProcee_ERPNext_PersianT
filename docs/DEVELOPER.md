# Developer handoff

Read [AGENTS.md](../AGENTS.md) first. That file is the contract for humans and for AI coding agents. This file is the map. Do not copy the contract here.

## What you are looking at

A Frappe 16 app. Python package name and install name: `smartprocee_erpnext_persiant`. Version is dynamic from `smartprocee_erpnext_persiant/__init__.py` through `pyproject.toml`.

Tool entry points:

| Tool | File | Role |
|---|---|---|
| Every agent | `AGENTS.md` | Contract |
| Claude Code | `CLAUDE.md` | Pointer only |
| Cursor | `.cursor/rules/persianizer-engineering.mdc` | Pointer and short hard limits |

Do not add a project Skill that restates `AGENTS.md`.

## First-hour checklist

1. Confirm you are in this repository, not a stale copy.
2. Read `AGENTS.md`, then `docs/FRAPPE_COMPATIBILITY.md`.
3. Use only owner-approved existing sites. Do not create a bench, site or container.
4. Do not edit `frappe`, `erpnext`, CRM, Insights, Raven or another app.
5. Do not write machine paths, site names, ports, emails or secrets into the tree.

## File map

| Path | Responsibility |
|---|---|
| `smartprocee_erpnext_persiant/hooks.py` | Install name, `code_only_modules`, migrate hooks |
| `smartprocee_erpnext_persiant/desk_icon.py` | Home icon repair |
| `smartprocee_erpnext_persiant/install.py` | Install, uninstall, navigation cleanup |
| `smartprocee_erpnext_persiant/permissions.py` | Apps-screen gate and Excel File gate |
| `smartprocee_erpnext_persiant/persian_translation/` | Manager, Excel, snapshots, catalogue |
| `smartprocee_erpnext_persiant/persian_rtl/` | RTL adapters and `after_request` |
| `smartprocee_erpnext_persiant/patches/` | Versioned schema and managed-data changes |
| `smartprocee_erpnext_persiant/translations/fa.csv` | Public Frappe/ERPNext catalogue |
| `smartprocee_erpnext_persiant/locale/` | Gettext for this app's own labels |
| `docs/` | Human documentation |

## Supported environments

Declared range: Frappe `>=16.0.0,<17.0.0` and ERPNext `>=16.0.0,<17.0.0`.

Name the execution context before you run a command: Windows host, Linux host, backend container, frontend container, disposable test site, or operational site.

`bench` often lives in a container. Route commands through that container and always pass `--site`.

## Change method

`Inspect → Plan → Smallest Safe Implementation → Test → User verification`

Reuse this order: standard ERPNext, standard Frappe, official Frappe app, mature open-source app, supported customization, extend this app, fork, new app.

Do not add a monkey patch, a DocType class override or a core edit.

## Migration

Use a versioned patch under `patches/` for schema or managed-data changes. Make reruns safe. Do not migrate an operational site as a side effect of development.

`after_migrate` compiles Gettext, repairs the home icon, removes the leftover navbar row, syncs public assets, and refreshes font and RTL settings.

## Tests

See [TESTING.md](TESTING.md). A green `install-app` is not proof. After install, run a real text scan on a disposable site.

## Security

Write APIs must enforce HTTP method, login, System Manager and document permissions on the server. Review the list in `AGENTS.md` section 7 before a release.

Do not store credentials or private customer data in git.

## Release

Follow Semantic Versioning. Working version 1.2.x must stay compatible with the last published 1.x tag wherever practical.

A release needs: the version in `__init__.py`, relevant tests, a security review, a migration review, `CHANGELOG.md`, `README.md`, and an explicit owner request to commit, tag, push or publish.

Release steps after that approval:

1. Confirm the working tree matches the intended source change against the last tag.
2. Run a local privacy and secret scan on every release-bound file.
3. Run focused tests on a disposable site. Do not migrate an operational site.
4. Commit only the approved files. Create an annotated tag. Push the commit and the tag.
5. Publish a GitHub Release for that tag. Do not move an older tag.

Do not modify the published `v1.2.1` tag or its history.

Before you ask for a publish approval, run:

```bash
# from the bench, disposable site
bench --site <site-name> execute smartprocee_erpnext_persiant.persian_translation.release_check.run
```

That gate allows only Frappe and ERPNext owned rows in `translations/fa.csv`.

## License

`GPL-3.0-or-later`. Runtime Python: `openpyxl`, `fonttools`, `brotli`. Do not bundle proprietary fonts. Do not add a runtime dependency without a clear need.
