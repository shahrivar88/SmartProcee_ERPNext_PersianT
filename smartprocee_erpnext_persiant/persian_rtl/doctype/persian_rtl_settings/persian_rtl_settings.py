"""Persian RTL Settings.

A Single that stores the decisions an administrator may make, plus optional
extra exclusions. Every technical fact about an adapter -- target app, routes,
tested versions, DOM signatures, exclusions -- lives in code under
``persian_rtl/adapters``. This controller only refreshes the read-only mirror
columns so they never disagree with the shipped build.
"""

from __future__ import annotations

from frappe.model.document import Document

from smartprocee_erpnext_persiant.persian_rtl import registry

# The switches a restore point has to remember. Read-only mirror columns and
# detected versions are derived, so a change in them is not a real change.
DECIDED_FIELDS = ("enabled", "diagnostic_mode")
ADAPTER_DECIDED_FIELDS = ("enabled", "override_version_check", "use_system_font")


class PersianRTLSettings(Document):
	def validate(self):
		if self.enabled is None:
			self.enabled = 0
		previous = self.get_doc_before_save()
		for row in self.adapters:
			adapter = registry.adapter_for(row.adapter_id)
			if adapter is None:
				continue
			row.detected_version = registry.installed_version(adapter.target_app)
			row.supports_system_font = int(adapter.supports_system_font)
			if not adapter.supports_system_font:
				row.use_system_font = 0
			row.state = registry.quick_state(adapter, bool(row.enabled))
		if previous and _decisions_changed(previous, self):
			_capture_restore_point()


def _decisions_changed(previous, current) -> bool:
	for field in DECIDED_FIELDS:
		if int(previous.get(field) or 0) != int(current.get(field) or 0):
			return True
	before = {row.adapter_id: _adapter_decisions(row) for row in previous.adapters}
	after = {row.adapter_id: _adapter_decisions(row) for row in current.adapters}
	# Only adapters that already existed are compared: a migrate that ships a new
	# adapter is a code change, not an administrator decision.
	shared = set(before) & set(after)
	return any(before[key] != after[key] for key in shared)


def _adapter_decisions(row) -> tuple[int, ...]:
	return tuple(int(row.get(field) or 0) for field in ADAPTER_DECIDED_FIELDS)


def _capture_restore_point():
	"""Snapshot before the switch flips, so an unwanted RTL change is revertible.

	Runs on the real change only: re-saving the form without touching a switch
	does not create a restore point.
	"""
	from smartprocee_erpnext_persiant.persian_translation import snapshots

	snapshots.capture(
		snapshots.PRE_RTL,
		"وضعیت پیش از تغییر تنظیمات راست‌به‌چپ",
		note="برای برگرداندن تصمیم‌های RTL به حالت پیش از این تغییر.",
	)
