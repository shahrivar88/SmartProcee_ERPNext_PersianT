"""Release gate for the public fa.csv.

Run before every release. No site is needed:

	env/bin/python -m smartprocee_erpnext_persiant.persian_translation.release_check

or with a site: bench --site <site> execute
smartprocee_erpnext_persiant.persian_translation.release_check.run

Fails when a row's owner is not proven to be Frappe or ERPNext, when a
(source, context) identity repeats, or when the CSV cannot be parsed.
Translation format problems are reported as warnings.
"""

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from smartprocee_erpnext_persiant.persian_translation.catalogue import (
	catalogue_key,
	catalogue_records,
	unescape_newlines,
)
from smartprocee_erpnext_persiant.persian_translation.provenance import CATALOGUE_OWNERS, OwnershipIndex
from smartprocee_erpnext_persiant.persian_translation.validate import translation_error

CATALOGUE = Path(__file__).resolve().parent.parent / "translations" / "fa.csv"


@dataclass
class Finding:
	line: int
	source: str
	problem: str


@dataclass
class Audit:
	rows: int
	failures: list[Finding]
	warnings: list[Finding]


def audit_catalogue(path: Path = CATALOGUE, index: OwnershipIndex | None = None) -> Audit:
	index = index or OwnershipIndex.for_catalogue_owners()
	failures, warnings, seen = [], [], {}
	rows = 0
	try:
		for line, row in catalogue_records(path):
			rows += 1
			source, context = catalogue_key(row)
			failures.extend(_identity_findings(line, source, context, seen, index))
			problem = translation_error(source, unescape_newlines(row[1]), context)
			if problem:
				warnings.append(Finding(line, source, problem))
	except (csv.Error, UnicodeDecodeError) as exc:
		failures.append(Finding(0, "", f"CSV parse error: {exc}"))
	return Audit(rows, failures, warnings)


def main() -> int:
	audit = audit_catalogue()
	print(f"fa.csv rows: {audit.rows}; allowed owners: {', '.join(CATALOGUE_OWNERS)}")
	_print("WARNING", audit.warnings)
	_print("FAIL", audit.failures)
	if audit.failures:
		print(f"RELEASE BLOCKED: {len(audit.failures)} row(s) failed.")
		return 1
	print("RELEASE CHECK PASSED")
	return 0


def run():
	if main():
		raise SystemExit(1)


def _identity_findings(line, source, context, seen, index):
	key = (source, context)
	if key in seen:
		yield Finding(line, source, f"duplicate of line {seen[key]}")
	else:
		seen[key] = line
	if not index.owner_of(source, context):
		yield Finding(line, source, "source owner is not proven to be " + " or ".join(CATALOGUE_OWNERS))


def _print(label, findings):
	for finding in findings:
		preview = finding.source.replace("\n", "\\n")[:80]
		print(f"{label} line {finding.line}: {finding.problem} | {preview}")


if __name__ == "__main__":
	sys.exit(main())
