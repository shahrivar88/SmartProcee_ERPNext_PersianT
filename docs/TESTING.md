# Testing

Rules and required evidence live in [AGENTS.md](../AGENTS.md) section 8. This file shows how to run the suites.

Use a disposable test site. Do not run `checks.run` or destructive suites on an operational site.

Replace `<site-name>` with the owner-approved disposable site. Do not commit that name.

## Unit and integration tests

From the bench:

```bash
bench --site <site-name> run-tests --app smartprocee_erpnext_persiant
```

Focused navigation tests:

```bash
bench --site <site-name> run-tests --module smartprocee_erpnext_persiant.persian_translation.tests.test_navigation
```

Tests inherit `frappe.tests.IntegrationTestCase`. They run in a transaction that rolls back.

## Catalogue release gate

No site is required:

```bash
env/bin/python -m smartprocee_erpnext_persiant.persian_translation.release_check
```

Or:

```bash
bench --site <site-name> execute smartprocee_erpnext_persiant.persian_translation.release_check.run
```

The gate fails when `fa.csv` has a row whose owner is not Frappe or ERPNext, when a key repeats, or when the CSV cannot be parsed.

## Destructive harness

`checks.run` creates and removes data. It refuses to run unless the site config has both `allow_tests` and `persianizer_allow_destructive_checks`.

Do not enable those flags on an operational site.

## Browser checks

Use a real browser. A screenshot is not enough.

For a navigation change, confirm all of these:

1. The home icon `فارسی‌ساز` is visible and opens Translation Manager.
2. The Apps switcher does not list this app.
3. The contextual Sidebar shows Translation Manager, Font Manager and RTL Settings.
4. Other apps and user sidebar customizations stay visible.
5. An English session stays English.

Mark each check Verified, Simulated or Not tested. Never claim PASS for a simulated browser.

## Upgrade and uninstall

When the change can affect those paths, also verify on a disposable site:

- Fresh install with no historical Persianizer index
- Upgrade from the last published tag
- Repeated `bench --site <site-name> migrate`
- Uninstall leaves Frappe and other-app icons and navbar items in place

## Synthetic data

Tests and examples must use synthetic strings and the test marker helpers in this app. Do not copy customer translations, live snapshots or operational workbooks into tests.
