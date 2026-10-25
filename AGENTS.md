# AGENTS.md — Persianizer engineering contract

This is the authoritative development policy for this repository.

It applies to Cursor, Claude Code, Codex, later AI agents and human contributors.

Read this file before you edit runtime code, hooks, DocTypes, locales, patches or release metadata.

Tool entry points must point here. Do not copy this contract into `CLAUDE.md` or `.cursor/rules/`.

Machine-wide skills (`smartprocess-erpnext`, official Frappe skills) add procedure. If they conflict with this file, keep the stricter safety rule until the owner resolves the conflict.

## 1. Identity

| Item | Value |
|---|---|
| Public repository | `SmartProcee_ERPNext_PersianT` |
| Public remote | the configured `origin` remote of this working tree |
| App install name | `smartprocee_erpnext_persiant` |
| Desk title | فارسی‌ساز |
| Latest published tag | `v1.2.2` |
| Working version | `1.2.2` in `__init__.py` |

Do not rename the install name, DocType identifiers or database columns.

Do not assume this module shares sites, ports or versions with Jalali, Logistics or another SmartProcess app.

Do not use a stale copy of this repository.

Protect uncommitted work. Do not reset or overwrite another agent's changes.

Do not write machine paths, personal usernames, email addresses, internal IP addresses, server hostnames, container names, site names, or port numbers into this repository.

### Environments for this module

Use only owner-approved existing benches and sites. Do not create a site, container, volume or port.

| Role | Rule |
|---|---|
| Operational / production-like site | Treat as production. Do not test, migrate, uninstall or write here unless the owner asked for that site by name |
| Disposable test site | Run automated, destructive and experimental work here |
| Clean install site | Use when a test needs a database with no historical Persianizer index |

The machine-wide `smartprocess-erpnext` skill may name the owner's local sites. Those names stay out of this repository.

Shared Docker volumes do not make an operational site safe for tests. Logical isolation is a process rule, not a hardware guarantee.

## 2. Instruction layers

| Layer | Role |
|---|---|
| `AGENTS.md` | Shared contract |
| `CLAUDE.md` | Claude Code entry point only |
| `.cursor/rules/persianizer-engineering.mdc` | Cursor pointer and short hard limits |
| `docs/FRAPPE_COMPATIBILITY.md` | Version matrix and version-sensitive APIs |
| `docs/ARCHITECTURE.md` | Runtime map. Must not contradict this file |
| `docs/DEVELOPER.md` | Handoff map. Must not copy this contract |
| `docs/TESTING.md` | How to run suites |
| `docs/ADMINISTRATION.md` | Site operations |
| `docs/USER_GUIDE.fa.md` | Persian end-user steps |
| `smartprocess-erpnext` skill | Reuse order, container routing, Persian reports |
| Official Frappe skills | Framework mechanics |

Do not add a project Skill that only restates this file.

## 3. Priority

1. Data integrity and recoverability
2. Correct accounting and stock behavior
3. Security and permissions
4. Standard Frappe/ERPNext compatibility
5. Upgradeability and maintainability
6. Performance
7. Minimal complexity

Never trade a higher priority for speed.

## 4. Compatibility

Lesson from v1.2.0: a query on `Workspace.app` failed with `Unknown column 'app' in 'SELECT'`. That was an application schema assumption, not a missing Persianizer migration.

Rules:

1. Do not assume a standard DocType field exists because one development database has it.
2. Check standard schemas and APIs against each supported Frappe version.
3. Do not add artificial columns to core tables to hide a compatibility bug.
4. Do not treat every `Unknown column` error as a migrate problem.
5. Prefer documented Frappe APIs.
6. Where supported versions differ, keep the compatibility branch narrow.
7. Fail safely when a version or feature is unsupported.
8. Do not swallow a failure that leaves a core workflow incomplete.
9. Do not claim compatibility with an untested release.
10. Do not rewrite working code only because a newer API exists.

Declared range: Frappe `>=16.0.0,<17.0.0` and ERPNext `>=16.0.0,<17.0.0`.

Record tested versions, incompatibilities and version-sensitive calls in `docs/FRAPPE_COMPATIBILITY.md`.

## 5. Architecture

- Stay self-contained. Do not edit Frappe, ERPNext, CRM, Insights, Raven or another app.
- No undocumented monkey patches. No global prototype changes. No unnecessary DocType class overrides.
- Prefer hooks, app DocTypes, Gettext, safe Property Setter use and the existing `after_request` RTL path.
- No Windows or Ubuntu path hardcoding. No site-name hardcoding in app code.
- Do not store required runtime state only inside a disposable container.
- Preserve standard permissions.
- Keep install, migrate, upgrade and uninstall safe and repeatable.
- Use versioned patches for schema or managed-data changes.

Before an architectural change, name the affected contracts: DocType schema, API, jobs, data ownership, integrations, Excel format, configuration, restore/rollback, install/uninstall.

A breaking change needs explicit owner approval.

## 6. Data protection

Data integrity comes before convenience.

Before a write, state: who is authorized, which DocTypes and fields, the transaction, failure/rollback, retry and idempotency, concurrent writers, and impact on existing business data.

- Do not delete or rewrite business data as part of a test.
- Do not use `ignore_permissions` unless the owner has reviewed a documented security boundary. Default is never.
- Do not change core tables to satisfy a custom query.
- Do not overwrite an existing Property Setter or user customization without an ownership or conflict policy.
- Treat ledgers, inventory, serials and payments as sensitive. This app must not post them.
- Preserve existing records in migrations unless an approved migration says otherwise.
- Display-only features must leave stored values, reports and APIs unchanged.

This app may write only its own DocTypes, Persian `Translation` rows it is allowed to own, font files it created, and RTL settings it owns.

## 7. Security — release blockers

Review relevant changes for: authentication, roles and trust boundaries, CSRF and HTTP methods, SQL injection, XSS and DOM injection, HTML/Jinja escaping, upload validation, path traversal, arbitrary file writes, SSRF, unsafe deserialization, secrets, sensitive logs, job ownership, races, replay, concurrent writers, retry safety, unsafe migrate or uninstall.

Write APIs must enforce HTTP method, login, System Manager and document permissions on the server. Hiding a control in the UI is not authorization.

Do not store credentials or private customer data in Git.

A confirmed Critical or High security or data-integrity issue blocks release.

## 8. Tests

Unit tests are required and not enough.

A successful `install-app` is not proof that the app works. After install, run the primary feature: a real text scan.

Required evidence, on a disposable site, when the change can affect that path:

- Fresh install on a database without this app's historical test data
- Upgrade from the last published version
- Repeated migrate
- Real Frappe database integration
- Browser check of native Persian UI before any scan
- English session isolation
- Role and permission boundaries
- Background jobs and queues
- Restart persistence, and Docker recreation persistence when the change depends on site or container config
- Uninstall safety for the changed surface
- Recovery after an interrupted operation
- No change to unrelated business data

Do not run `checks.run` or destructive suites on production.

Never claim PASS for a simulated browser or production test.

Use: Verified, Simulated, Not tested.

## 9. Production

Never migrate production as a side effect of development.

Before any production migrate: identify the site, record app versions, inspect pending patches for every installed app, assess impact, take and verify a full backup, document rollback limits, get explicit authorization, run the supported command, then verify the app and business data with non-destructive smoke tests.

Do not add a site, server, container or port when an approved test environment already exists.

The owner's operational site is production-like. Shared Docker volumes do not make it a test site.

## 10. UI and Persian

- Use standard Frappe UI. No generic DOM text replacement.
- Ship this app's own Persian labels in Gettext `locale/fa.po` and compile MO on install and migrate. Do not put those labels in public `fa.csv`.
- English sessions stay English.
- Keep RTL fixes narrow. Preserve LTR.
- Do not rename stored business values only to translate their display.
- Do not invent fake progress percentages.
- Ordinary users must not see internal technical traces.

## 11. Dependencies and license

Runtime Python: `openpyxl`, `fonttools`, `brotli`. License: `GPL-3.0-or-later`.

Do not bundle proprietary fonts. User-uploaded fonts stay in site files, not in git.

Do not add a runtime dependency without a clear need.

## 12. Code quality

Keep changes small, readable, testable and upgrade-safe.

Fix the root cause. Do not refactor unrelated code. Do not add a framework for one edge case.

Do not rework CRM RTL resize, Excel progress copy, Account Category Property Setter safety, Call Logs translation, schema-aware scan, or snapshot/ownership guards without a proven regression.

## 13. Release

Follow Semantic Versioning. For 1.x, keep backward compatibility with the last published tag wherever practical. Document any data migration. Do not silently break installed sites.

A release needs: verified version, relevant regression tests, security review, migration review, CHANGELOG, README, intended Git changes, and an appropriate tag.

Do not commit, tag, push or deploy only because tests are green. Those steps need an explicit owner request.

## 14. Reports

Every substantial report must state: PHASE name and number, STEP X/Y, duration, scope, actual changes, tests run, tests not run, remaining risks, Git status, release readiness.

Defect format: Severity, Root cause, Evidence, Impact, File/function, Corrective action, Required regression test.

Do not inflate severity.

## 15. Communication and method

Reply to Amir in Persian. Keep identifiers in their original form.

`Inspect → Plan → Smallest Safe Implementation → Test → User verification`

For HIGH-RISK work stop after the plan unless implementation is already authorized.

## 16. Stop conditions

STOP and ask before you delete or rewrite business data, drop or rename populated fields, alter ledgers, run a destructive migrate, uninstall an app that holds business records, reset a site, edit Core, or write an operational site.

State the risk and the safer alternative first.
