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
# These rows were owned by Frappe/ERPNext on 16.35 and left the 16.53 source
# tree (dock copy, invitation mail, editor chrome). The catalogue keeps them
# so existing Persian sites do not lose labels. Do not add new third-party
# sources here.
FRAPPE_1653_SOURCE_DRIFT = frozenset(
	{
		"Audits",
		"Google Calender",
		"Health Report",
		"Navigation Buttons",
		"Notification Message",
		"Notification Title",
		" You are impersonating as another user.",
		"A new account has been created for you at {0}.",
		"Add CSS",
		"Add to Desktop",
		"Cannot find a default warehouse for item {0}. Please select one in the Update Items dialog, or set a default in the Item Master or in Stock Settings.",
		"Click below to accept your invitation and get started.",
		"Click the button below to complete your registration and set a new password.",
		"Click the button below to sign in to your account. This link will expire in {0} minutes.",
		"Complete your registration",
		"Getting Started",
		"Great!",
		"Heading 1",
		"Heading 2",
		"Heading 3",
		"Heading 4",
		"Heading 5",
		"Heading 6",
		"Headline of the in-app notification. Falls back to Subject if left blank. Supports Jinja.",
		"If you did not request a password reset, please ignore this email. Your password will remain unchanged.",
		"If you did not request this code, you can safely ignore this email.",
		"If you didn't request this link, you can ignore this email. Someone may have entered your email address by mistake.",
		"Invalid line reference format: '{0}'. Must start with letter and contain only letters, numbers, underscores, and hyphens",
		"Invitation cancelled",
		"Invitation expired",
		"Line references undefined in {0}: {1}",
		"Log in to {0}",
		"Log In to {0}",
		"More Options",
		"Optional body of the in-app notification. Supports Jinja.",
		"Or copy and paste this link:",
		"Poor!",
		"Reset All",
		"Row #{0}: % of FG Cost needs a BOM secondary item. Choose Valuation Rate or Manual for {1}.",
		"Skip All",
		"steps completed",
		"Use minimum of 8 characters(case sensitive) with at least one number or special character.",
		"Use the code below to complete your sign-in.",
		"Valuation Rate and Manual value this item on its own and deduct that cost from the raw material cost, like the pre-v16 scrap items. % of FG Cost allocates a percentage of the remaining raw material cost.",
		"Verification code",
		"We received a request to reset the password for your account. Click the button below to set a new password.",
		"Welcome to Frappe!",
		"Workspace added to desktop",
		"You've been invited",
	}
)


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
			for finding in _identity_findings(line, source, context, seen, index):
				if finding.problem.startswith("kept after Frappe 16.53"):
					warnings.append(finding)
				else:
					failures.append(finding)
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
		if source in FRAPPE_1653_SOURCE_DRIFT:
			yield Finding(line, source, "kept after Frappe 16.53 source drift")
		else:
			yield Finding(line, source, "source owner is not proven to be " + " or ".join(CATALOGUE_OWNERS))


def _print(label, findings):
	for finding in findings:
		preview = finding.source.replace("\n", "\\n")[:80]
		print(f"{label} line {finding.line}: {finding.problem} | {preview}")


if __name__ == "__main__":
	sys.exit(main())
