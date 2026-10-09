"""Restore points: what they hold, what they refuse, and what a restore touches.

These tests drive real `Persian Snapshot` records, the real restore plan and the
real background operation against the real database.

What is proven here:

* the first-install baseline is immutable: it cannot be edited, unlocked or
  deleted, and it is never created a second time;
* a site that was already installed is never given a false historical baseline,
  and `adopted_state` can never overwrite an existing snapshot;
* a snapshot holds only app-owned Persian state, and only that state is restored:
  business documents and other languages are neither read nor written;
* `values` mode restores values without deleting rows created later, `full` mode
  also removes them;
* a restore is previewed first, and the preview is queued instead of run inside
  the HTTP request;
* a restore takes a reversible undo point before it starts, and requires both
  explicit confirmation and System Manager;
* pruning keeps the newest disposable snapshots and never touches an immutable
  one;
* the font part of a plan refuses a family whose files are gone or were shipped
  as app assets before 1.2;
* `full` removes a row only while it still holds the value this app last wrote;
* a snapshot a queued or running operation reads cannot be deleted or pruned,
  and a finished operation keeps working after its snapshot is gone;
* an uploaded font file lives while a face or a snapshot records it, and is
  removed after the commit that drops its last record.
"""

import time
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import cint

from smartprocee_erpnext_persiant.persian_translation import (
	operations,
	ownership,
	service,
	snapshots,
)
from smartprocee_erpnext_persiant.persian_translation.doctype.persian_font_family.persian_font_family import (
	SKIP_RESTORE_POINT,
)
from smartprocee_erpnext_persiant.persian_translation.system_font import storage as font_storage
from smartprocee_erpnext_persiant.persian_translation.tests.helpers import MARKER
from smartprocee_erpnext_persiant.persian_translation.tests.test_font_manager import CssConfigMixin

SNAPSHOT = snapshots.SNAPSHOT
FAMILY = snapshots.FAMILY
TRANSLATION = "Translation"

PERSIAN = "یک"
REPLACED = "دو"


class SnapshotCase(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		# Everything this test creates is removed in `cleanup`, whether it was made
		# through the service or through the engine. The comparison is by name, so
		# nothing that existed before the test can be touched.
		self.existing_snapshots = self._names(SNAPSHOT)
		self.existing_operations = self._names(operations.OPERATION)
		self.uploaded_files = []

	def _names(self, doctype, filters=None):
		return set(frappe.get_all(doctype, filters=filters or {}, pluck="name", limit_page_length=0))

	def cleanup(self):
		"""Remove exactly what this test created, and nothing else.

		An immutable snapshot refuses a normal delete by design, so teardown uses
		`ignore_on_trash` for the records this test made and never for a record
		that was already on the site. The immutability itself is asserted inside
		the tests, through the normal API.
		"""
		frappe.db.rollback()
		for name in self._names(operations.OPERATION) - self.existing_operations:
			frappe.delete_doc(operations.OPERATION, name, force=1, ignore_permissions=True)
		for name in self._names(SNAPSHOT) - self.existing_snapshots:
			frappe.delete_doc(SNAPSHOT, name, force=1, ignore_on_trash=True, ignore_permissions=True)
		for name in frappe.get_all(
			TRANSLATION,
			filters={"source_text": ["like", f"{MARKER}%"]},
			pluck="name",
			limit_page_length=0,
		):
			frappe.delete_doc(TRANSLATION, name, force=1, ignore_permissions=True)
		for name in self._names(FAMILY, {"family_name": ["like", f"{MARKER}%"]}):
			# An active family refuses a delete, exactly as it does for a person.
			frappe.db.set_value(FAMILY, name, "is_active", 0, update_modified=False)
			frappe.delete_doc(
				FAMILY, name, force=1, ignore_permissions=True, flags={SKIP_RESTORE_POINT: True}
			)
		# The ownership registry outlives the translation it describes, so a
		# leftover row would make the next test see a key this app "wrote".
		for name in self._names(ownership.DOCTYPE, {"source_text": ["like", f"{MARKER}%"]}):
			frappe.delete_doc(ownership.DOCTYPE, name, force=1, ignore_permissions=True)
		for path in [Path(frappe.get_site_path("public", "files", name)) for name in self.uploaded_files]:
			if path.exists():
				path.unlink()
		service.clear_translation_caches()
		frappe.db.commit()

	def capture(self, kind=snapshots.MANUAL, label="", immutable=False):
		return snapshots.capture(kind, label or f"{MARKER} {kind}", immutable=immutable)["name"]

	def translate(self, source, value, context="", language="fa"):
		"""Write one Persian value the way the manager does, so validation still runs."""
		if language == "fa":
			service.save_translations(
				[{"source_text": source, "context": context, "translated_text": value}]
			)
		else:
			frappe.get_doc(
				{
					"doctype": TRANSLATION,
					"language": language,
					"source_text": source,
					"context": context,
					"translated_text": value,
				}
			).insert()
		frappe.db.commit()

	def stored(self, source, context=""):
		return frappe.db.get_value(
			TRANSLATION, {"language": "fa", "source_text": source, "context": context}, "translated_text"
		)

	def restore_via_worker(self, snapshot, mode="values", remove_fonts=0):
		name = operations._create(
			operations.SNAPSHOT_RESTORE,
			snapshot=snapshot,
			detail={"mode": mode, "remove_fonts": cint(remove_fonts)},
		)
		operations.run_operation(name)
		return operations.get_operation(name)

	def tearDown(self):
		self.cleanup()
		super().tearDown()


class TestBaselineImmutability(SnapshotCase):
	def test_an_immutable_snapshot_cannot_be_edited_unlocked_or_deleted(self):
		name = self.capture(snapshots.ADOPTED_STATE, immutable=True)
		doc = frappe.get_doc(SNAPSHOT, name)
		self.assertTrue(cint(doc.immutable))

		doc.note = "تغییر غیرمجاز"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

		doc = frappe.get_doc(SNAPSHOT, name)
		doc.immutable = 0
		with self.assertRaises(frappe.ValidationError):
			doc.save()

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(SNAPSHOT, name)

		self.assertTrue(frappe.db.exists(SNAPSHOT, name), "an immutable snapshot must survive a refusal")

	def test_a_baseline_is_only_possible_on_a_site_with_no_snapshot_at_all(self):
		"""A later install must not label a used site as a pristine one."""
		if snapshots.has_any():
			before = frappe.db.count(SNAPSHOT)
			self.assertIsNone(
				snapshots.capture_install_baseline(),
				"a site that already carries a snapshot may not gain a pre-install baseline",
			)
			self.assertEqual(frappe.db.count(SNAPSHOT), before)
			return

		created = snapshots.capture_install_baseline()
		self.assertTrue(created)
		second = snapshots.capture_install_baseline()
		self.assertIsNone(second, "the baseline may only be created once")
		self.assertTrue(cint(frappe.db.get_value(SNAPSHOT, created["name"], "immutable")))

	def test_adopted_state_never_overwrites_an_existing_snapshot(self):
		before = frappe.db.count(SNAPSHOT)
		self.assertIsNone(snapshots.ensure_adopted_state())
		self.assertEqual(frappe.db.count(SNAPSHOT), before)

	def test_adopted_state_is_labelled_as_adopted_and_not_as_a_baseline(self):
		"""On a site that already had snapshots, the honest label is what remains."""
		name = frappe.db.get_value(SNAPSHOT, {"kind": snapshots.ADOPTED_STATE}, "name")
		if not name:
			self.skipTest("this site has no adopted_state snapshot")
		doc = frappe.get_doc(SNAPSHOT, name)
		self.assertEqual(doc.label, snapshots.ADOPTED_LABEL)
		self.assertNotEqual(doc.label, snapshots.BASELINE_LABEL)
		self.assertEqual(doc.note, snapshots.ADOPTED_NOTE)
		self.assertTrue(cint(doc.immutable))

	def test_adopted_state_is_not_created_during_an_install(self):
		previous = getattr(frappe.flags, "in_install", None)
		frappe.flags.in_install = True
		try:
			self.assertIsNone(snapshots.ensure_adopted_state())
		finally:
			frappe.flags.in_install = previous


class TestSnapshotScope(SnapshotCase):
	def test_a_snapshot_holds_only_persian_owned_state(self):
		persian = f"{MARKER} SCOPE"
		self.translate(persian, PERSIAN)
		arabic = f"{MARKER} ARABIC"
		self.translate(arabic, "نص عربي", language="ar")
		name = self.capture()

		payload = snapshots.load_payload(name)
		self.assertEqual(set(payload), {"schema", "translations", "fonts", "rtl"})
		self.assertEqual(payload["schema"], snapshots.SCHEMA)

		rows = {(row[0], row[1]): row[2] for row in payload["translations"]}
		self.assertEqual(rows.get((persian, "")), PERSIAN)
		self.assertNotIn((arabic, ""), rows, "another language is not this app's state")

	def test_a_snapshot_records_the_rtl_state(self):
		source = f"{MARKER} LOCKED"
		self.translate(source, PERSIAN)
		name = self.capture()

		payload = snapshots.load_payload(name)
		self.assertIn("available", payload["rtl"])


class TestTargetedRecovery(SnapshotCase):
	def test_a_values_restore_rewrites_changed_rows_and_keeps_later_ones(self):
		source = f"{MARKER} VALUES"
		later = f"{MARKER} LATER"
		self.translate(source, PERSIAN)
		name = self.capture()

		self.translate(source, REPLACED)
		self.translate(later, "بعدی")
		self.assertEqual(self.stored(source), REPLACED)

		actions, report = snapshots.build_plan(name, "values")
		upserts = {a["source_text"]: a["value"] for a in actions if a["type"] == "translation_upsert"}
		self.assertEqual(upserts.get(source), PERSIAN)
		self.assertEqual(report["translations_removed"], 0)
		self.assertFalse([a for a in actions if a["type"] == "translation_delete"])

		result = self.restore_via_worker(name, mode="values")
		self.assertEqual(result["status"], "Completed")
		self.assertEqual(self.stored(source), PERSIAN)
		self.assertEqual(self.stored(later), "بعدی", "values mode must not delete a later row")

	def test_a_full_restore_removes_rows_created_after_the_snapshot(self):
		source = f"{MARKER} FULL"
		later = f"{MARKER} FULL LATER"
		arabic = f"{MARKER} FULL ARABIC"
		self.translate(source, PERSIAN)
		self.translate(arabic, "نص عربي", language="ar")
		name = self.capture()
		self.translate(later, "بعدی")

		actions, report = snapshots.build_plan(name, "full")
		deletes = [a for a in actions if a["type"] == "translation_delete"]
		self.assertEqual([a["source_text"] for a in deletes], [later])
		self.assertEqual(report["translations_removed"], 1)
		for action in deletes:
			self.assertTrue(
				action["source_text"].startswith(MARKER),
				"a full restore may only remove rows this test created",
			)

		result = self.restore_via_worker(name, mode="full")
		self.assertEqual(result["status"], "Completed")
		self.assertIsNone(self.stored(later))
		self.assertEqual(self.stored(source), PERSIAN)
		self.assertEqual(
			frappe.db.get_value(
				TRANSLATION, {"language": "ar", "source_text": arabic}, "translated_text"
			),
			"نص عربي",
			"another language is never touched by a restore",
		)

	def test_a_restore_takes_a_reversible_undo_point_before_it_starts(self):
		source = f"{MARKER} UNDO"
		self.translate(source, PERSIAN)
		name = self.capture()

		queued = service.restore_snapshot(name, mode="values", confirm=1)
		# Queueing must not read the whole translation state into a snapshot.
		self.assertIsNone(operations.get_operation(queued["name"])["detail"].get("undo_snapshot"))

		operations.run_operation(queued["name"])
		undo = operations.get_operation(queued["name"])["detail"]["undo_snapshot"]
		self.assertTrue(frappe.db.exists(SNAPSHOT, undo))
		self.assertEqual(frappe.db.get_value(SNAPSHOT, undo, "kind"), snapshots.PRE_RESTORE)
		self.assertEqual(cint(frappe.db.get_value(SNAPSHOT, undo, "immutable")), 0)


class TestRestoreResume(SnapshotCase):
	def test_a_resumed_restore_writes_every_row_of_its_first_plan_exactly_once(self):
		"""A rebuilt plan drops the rows already restored and renumbers the rest,
		so the checkpoint of the first pass would skip rows that were never written."""
		sources = [f"{MARKER} RESUME {index}" for index in range(4)]
		for index, source in enumerate(sources):
			self.translate(source, f"اصل {index}")
		snapshot = self.capture()
		for index, source in enumerate(sources):
			self.translate(source, f"تغییر {index}")

		name = operations._create(
			operations.SNAPSHOT_RESTORE, snapshot=snapshot, detail={"mode": "values", "remove_fonts": 0}
		)
		real_commit = operations._commit_batch
		batches = {"count": 0}

		def dying(doc, size, counts, failures, checkpoint):
			batches["count"] += 1
			if batches["count"] > 1:
				raise RuntimeError("worker stopped")
			return real_commit(doc, size, counts, failures, checkpoint)

		with patch.object(operations, "BATCH_SIZE", 1), patch.object(operations, "_commit_batch", dying):
			operations.run_operation(name)

		stopped = operations.get_operation(name)
		self.assertEqual(stopped["status"], "Failed")
		self.assertEqual(stopped["checkpoint"], 1)
		self.assertTrue(stopped["plan_stored"], "the first pass must store its restore plan")
		plan = operations._decode_blob(operations._detail(frappe.get_doc(operations.OPERATION, name).detail)["plan_blob"])[
			"actions"
		]
		upserts = [action["source_text"] for action in plan if action["type"] == operations.TRANSLATION_UPSERT]
		self.assertEqual(sorted(upserts), sources)
		self.assertEqual(
			sum(self.stored(source) == f"اصل {index}" for index, source in enumerate(sources)),
			1,
			"exactly the first committed row is restored before the stop",
		)

		with patch.object(operations, "_enqueue"):
			operations.resume_operation(name)
		real_apply = operations._apply_action
		executed = []

		def counting(doc, action):
			executed.append(action["row_index"])
			return real_apply(doc, action)

		with patch.object(operations, "_apply_action", counting):
			operations.run_operation(name)

		result = operations.get_operation(name)
		self.assertEqual(result["status"], "Completed")
		# The resume runs every row after the checkpoint once, and none before it.
		self.assertEqual(executed, [action["row_index"] for action in plan if action["row_index"] > 1])
		self.assertEqual(result["planned"], len(plan))
		self.assertEqual(result["processed"], len(plan))
		self.assertEqual(result["checkpoint"], len(plan))
		self.assertEqual(result["applied"], len(plan))
		self.assertEqual(result["failed"], 0)
		for index, source in enumerate(sources):
			self.assertEqual(self.stored(source), f"اصل {index}")


class TestScopedRestore(SnapshotCase):
	def test_a_full_restore_preserves_a_persian_row_this_app_never_wrote(self):
		"""`full` may only remove rows this app is recorded as having written."""
		source = f"{MARKER} SCOPED OWNED"
		foreign = f"{MARKER} SCOPED FOREIGN"
		self.translate(source, PERSIAN)
		name = self.capture()

		# Written by somebody else: no ownership record, so this app may not
		# delete it. This is the case a blanket "delete everything not in the
		# snapshot" would silently destroy.
		frappe.get_doc(
			{
				"doctype": TRANSLATION,
				"language": "fa",
				"source_text": foreign,
				"context": "",
				"translated_text": "دست‌نویس",
			}
		).insert()
		service.clear_translation_caches()
		frappe.db.commit()

		actions, report = snapshots.build_plan(name, "full")
		self.assertFalse(
			[action for action in actions if action.get("source_text") == foreign],
			"a row this app never wrote is not part of the plan",
		)
		self.assertEqual(report["preserved_unowned"], 1)
		self.assertEqual(report["preserved_unowned_sample"][0]["source_text"], foreign)

		result = self.restore_via_worker(name, mode="full")
		self.assertEqual(result["status"], "Completed")
		self.assertEqual(
			self.stored(foreign), "دست‌نویس", "a row this app never wrote must survive a full restore"
		)
		self.assertIn("دست‌نخورده", result["detail"]["report"]["summary"])

	def test_a_full_restore_still_removes_a_row_this_app_wrote(self):
		"""The scope must not make `full` a no-op for the rows it owns."""
		source = f"{MARKER} SCOPED KEPT"
		later = f"{MARKER} SCOPED LATER"
		self.translate(source, PERSIAN)
		name = self.capture()
		self.translate(later, "بعدی")

		_actions, report = snapshots.build_plan(name, "full")
		self.assertEqual(report["translations_removed"], 1)
		self.assertEqual(report["preserved_unowned"], 0)

		result = self.restore_via_worker(name, mode="full")
		self.assertEqual(result["status"], "Completed")
		self.assertIsNone(self.stored(later))
		self.assertEqual(self.stored(source), PERSIAN)

	def test_a_restore_reports_a_value_changed_after_this_app_wrote_it(self):
		source = f"{MARKER} SCOPED DRIFT"
		self.translate(source, PERSIAN)
		name = self.capture()
		self.translate(source, REPLACED)
		# Changed behind the app's back, so its own record is out of date.
		frappe.db.set_value(
			TRANSLATION,
			{"language": "fa", "source_text": source},
			"translated_text",
			"دست‌کاری",
			update_modified=False,
		)
		service.clear_translation_caches()
		frappe.db.commit()

		actions, report = snapshots.build_plan(name, "values")
		self.assertEqual(report["overwritten"], 1)
		sample = report["overwritten_sample"][0]
		self.assertEqual(sample["source_text"], source)
		self.assertEqual(sample["current_value"], "دست‌کاری")
		self.assertEqual(sample["last_written_value"], REPLACED)
		self.assertEqual(sample["snapshot_value"], PERSIAN)
		self.assertTrue([action for action in actions if action.get("source_text") == source])

		result = self.restore_via_worker(name, mode="values")
		self.assertEqual(result["status"], "Completed")
		self.assertEqual(self.stored(source), PERSIAN)
		self.assertIn("تغییر کرده بود", result["detail"]["report"]["summary"])

	def test_an_ownership_record_survives_the_delete_of_its_translation(self):
		"""A string stays this app's even while it currently has no value."""
		source = f"{MARKER} SCOPED DELETE"
		self.translate(source, PERSIAN)
		self.assertTrue(ownership.owns(source, ""))
		frappe.delete_doc(
			TRANSLATION,
			frappe.db.get_value(TRANSLATION, {"language": "fa", "source_text": source}),
			force=1,
			ignore_permissions=True,
		)
		self.translate(source, REPLACED)
		self.assertTrue(ownership.owns(source, ""))

	def test_a_full_restore_keeps_a_row_typed_in_again_after_this_apps_row_was_deleted(self):
		"""The claim outlives the row, so it must not make a hand-made row this app's."""
		source = f"{MARKER} SCOPED RETYPED"
		name = self.capture()
		self.translate(source, PERSIAN)
		frappe.delete_doc(
			TRANSLATION,
			frappe.db.get_value(TRANSLATION, {"language": "fa", "source_text": source}),
			force=1,
			ignore_permissions=True,
		)
		frappe.get_doc(
			{
				"doctype": TRANSLATION,
				"language": "fa",
				"source_text": source,
				"context": "",
				"translated_text": "دست‌نویس",
			}
		).insert()
		service.clear_translation_caches()
		frappe.db.commit()
		self.assertTrue(ownership.owns(source, ""), "the stale claim is still there")

		actions, report = snapshots.build_plan(name, "full")
		self.assertFalse([action for action in actions if action.get("source_text") == source])
		self.assertEqual(report["preserved_unowned"], 1)

		result = self.restore_via_worker(name, mode="full")
		self.assertEqual(result["status"], "Completed")
		self.assertEqual(self.stored(source), "دست‌نویس")

	def test_a_full_restore_keeps_an_owned_row_whose_value_was_changed_by_hand(self):
		source = f"{MARKER} SCOPED EDITED"
		name = self.capture()
		self.translate(source, PERSIAN)
		frappe.db.set_value(
			TRANSLATION, {"language": "fa", "source_text": source}, "translated_text", "دست‌کاری"
		)
		service.clear_translation_caches()
		frappe.db.commit()

		_actions, report = snapshots.build_plan(name, "full")
		self.assertEqual(report["translations_removed"], 0)
		self.assertEqual(report["preserved_unowned"], 1)

		self.restore_via_worker(name, mode="full")
		self.assertEqual(self.stored(source), "دست‌کاری")


class TestSnapshotLifecycle(SnapshotCase):
	"""A snapshot can go away; an operation that already ran must not notice."""

	def _operation(self, snapshot, status):
		doc = frappe.new_doc(operations.OPERATION)
		doc.kind = operations.SNAPSHOT_PREVIEW
		doc.status = status
		doc.snapshot = snapshot
		doc.insert()
		return doc.name

	def test_a_snapshot_an_active_operation_reads_cannot_be_deleted(self):
		"""Also with `force`, which skips the link check and is what pruning uses."""
		name = self.capture()
		operation = self._operation(name, "Queued")
		for force in (0, 1):
			with self.assertRaises(frappe.ValidationError):
				frappe.delete_doc(SNAPSHOT, name, force=force)
		self.assertTrue(frappe.db.exists(SNAPSHOT, name))

		frappe.db.set_value(operations.OPERATION, operation, "status", "Completed")
		frappe.delete_doc(SNAPSHOT, name, force=1)
		self.assertFalse(frappe.db.exists(SNAPSHOT, name))

	def test_pruning_skips_a_snapshot_an_active_operation_reads(self):
		first = self.capture(snapshots.PRE_APPLY)
		self.capture(snapshots.PRE_APPLY)
		self._operation(first, "Running")

		snapshots.prune(snapshots.PRE_APPLY, keep=1)
		self.assertTrue(frappe.db.exists(SNAPSHOT, first))

	def test_a_finished_operation_outlives_its_snapshot(self):
		name = self.capture()
		with patch.object(operations, "_enqueue"):
			queued = operations.start_restore_preview(name)
		operations.run_operation(queued["name"])
		frappe.delete_doc(SNAPSHOT, name, force=1)
		frappe.db.commit()

		result = operations.get_operation(queued["name"])
		self.assertEqual(result["status"], "Completed")
		self.assertEqual(result["snapshot"], name, "the name stays as history")
		self.assertIn(queued["name"], [row["name"] for row in operations.list_operations(limit=50)])
		# Saving the record again, as a status change does, must not need the snapshot.
		operations._finish(frappe.get_doc(operations.OPERATION, queued["name"]), "Completed", "بازبینی")

	def test_a_queued_restore_whose_snapshot_vanished_fails_and_frees_the_lease(self):
		name = self.capture()
		operation = operations._create(
			operations.SNAPSHOT_RESTORE, snapshot=name, detail={"mode": "values", "remove_fonts": 0}
		)
		# Only a raw delete can do this now; the document delete refuses it.
		frappe.db.delete(SNAPSHOT, {"name": name})
		frappe.db.commit()

		operations.run_operation(operation)
		result = operations.get_operation(operation)
		self.assertEqual(result["status"], "Failed")
		self.assertFalse(frappe.db.get_value(operations.OPERATION, operation, "lock_key"))


class TestFontRestore(CssConfigMixin, SnapshotCase):
	def setUp(self):
		super().setUp()
		self.snapshot_css_config()

	def _face(self, url: str, filename: str = "recorded.woff2") -> list:
		return [filename, url, "", "WOFF2", "400", "normal", "normal", 1]

	def test_restoring_an_older_font_renders_it_instead_of_keeping_the_current_file(self):
		"""The active stylesheet lives at one fixed path, so it is never copied back."""
		recorded = "/files/persian-font-recorded-snapshot.woff2"
		payload = {
			"fonts": {
				"active_css": "/files/persian-font-active.css?v=old",
				"families": [
					{
						"key": "recorded-font",
						"family_name": "Recorded Font",
						"css_family": "Persianizer Recorded Font",
						"source": "Uploaded",
						"is_active": 1,
						"faces": [self._face(recorded)],
					}
				],
			}
		}
		# A newer font is the one on disk right now.
		font_storage.write_active_css("/* the current font */")

		snapshots.apply_font_activate("/files/persian-font-active.css?v=old", payload)

		text = (Path(frappe.get_site_path("public", "files")) / font_storage.ACTIVE_CSS).read_text(
			encoding="utf-8"
		)
		self.assertIn("Persianizer Recorded Font", text)
		self.assertIn(recorded, text)
		self.assertNotIn("the current font", text)

	def test_restoring_a_font_shipped_before_1_2_falls_back_to_the_default_font(self):
		"""Its files are no longer shipped, so the stylesheet is cleared instead of pointing at them."""
		payload = {
			"fonts": {
				"active_css": "/files/persian-font-active.css?v=old",
				"families": [
					{
						"key": "legacy-font",
						"family_name": "Legacy Font",
						"css_family": "Persianizer Legacy Font",
						"source": "Bundled",
						"is_active": 1,
						"faces": [self._face("/assets/smartprocee_erpnext_persiant/fonts/Legacy-Regular.woff2")],
					}
				],
			}
		}
		font_storage.write_active_css("/* the current font */")

		snapshots.apply_font_activate("/files/persian-font-active.css?v=old", payload)

		self.assertFalse((Path(frappe.get_site_path("public", "files")) / font_storage.ACTIVE_CSS).exists())

	def test_deactivating_a_font_clears_the_stylesheet(self):
		font_storage.write_active_css("/* a font */")
		snapshots.apply_font_activate(None, {"fonts": {"active_css": None, "families": []}})
		path = Path(frappe.get_site_path("public", "files")) / font_storage.ACTIVE_CSS
		self.assertFalse(path.exists())

	def test_a_plan_never_removes_an_active_family(self):
		"""`_active_family_names` reads plucked names, which are plain strings."""
		family = frappe.new_doc(FAMILY)
		family.family_name = f"{MARKER} Active Font"
		family.css_family = "Persianizer Active Font"
		family.source = "Uploaded"
		family.is_active = 1
		family.append("faces", {"original_filename": "active.woff2", "file_url": "/files/persian-font-active-test.woff2", "font_format": "WOFF2", "css_weight": "400", "font_style": "normal", "font_stretch": "normal", "enabled": 1})
		family.insert(ignore_permissions=True)
		frappe.db.commit()
		self.assertIn(family.name, snapshots._active_family_names())

		payload = {"fonts": {"active_css": None, "families": []}}
		actions, _report = snapshots._font_plan(payload, full=True, remove_fonts=True)
		self.assertNotIn(family.name, [action.get("name") for action in actions])

	def test_deleting_a_family_keeps_a_file_a_stored_snapshot_still_records(self):
		url = font_storage.write_upload("WOFF2", b"\x00" * 32)
		self.uploaded_files.append(url.rsplit("/", 1)[-1])
		path = Path(frappe.get_site_path("public", "files")) / url.rsplit("/", 1)[-1]
		self.assertTrue(path.exists())

		family = frappe.new_doc(FAMILY)
		family.family_name = f"{MARKER} Kept Font"
		family.css_family = "Persianizer Kept Font"
		family.source = "Uploaded"
		family.is_active = 0
		family.append("faces", {"original_filename": "kept.woff2", "file_url": url, "font_format": "WOFF2", "css_weight": "400", "font_style": "normal", "font_stretch": "normal", "enabled": 1})
		family.insert(ignore_permissions=True)
		frappe.db.commit()

		self.capture()  # records this family and its file
		self.assertIn(url, snapshots.fonts_referenced_by_snapshots())

		operations._delete_font_family(family.name)

		self.assertFalse(frappe.db.exists(FAMILY, family.name))
		self.assertTrue(
			path.exists(), "a file a stored snapshot still records must survive the delete"
		)

	def test_deleting_a_family_removes_a_file_no_snapshot_needs(self):
		url = font_storage.write_upload("WOFF2", b"\x00" * 32)
		filename = url.rsplit("/", 1)[-1]
		path = Path(frappe.get_site_path("public", "files")) / filename

		family = frappe.new_doc(FAMILY)
		family.family_name = f"{MARKER} Orphan Font"
		family.css_family = "Persianizer Orphan Font"
		family.source = "Uploaded"
		family.is_active = 0
		family.append("faces", {"original_filename": "orphan.woff2", "file_url": url, "font_format": "WOFF2", "css_weight": "400", "font_style": "normal", "font_stretch": "normal", "enabled": 1})
		family.insert(ignore_permissions=True)
		frappe.db.commit()

		# No snapshot records this file, so nothing keeps it alive.
		with patch.object(snapshots, "load_payload", return_value={"fonts": {"families": []}}):
			operations._delete_font_family(family.name)

		self.assertFalse(frappe.db.exists(FAMILY, family.name))
		self.assertFalse(path.exists(), "a file nothing needs any more is removed")

	def _recorded_upload(self, label):
		"""An uploaded file that only snapshots record: its family is already gone."""
		url = font_storage.write_upload("WOFF2", b"\x00" * 32)
		self.uploaded_files.append(url.rsplit("/", 1)[-1])
		family = frappe.new_doc(FAMILY)
		family.family_name = f"{MARKER} {label}"
		family.css_family = f"Persianizer {label}"
		family.source = "Uploaded"
		family.is_active = 0
		family.append("faces", {"original_filename": "released.woff2", "file_url": url, "font_format": "WOFF2", "css_weight": "400", "font_style": "normal", "font_stretch": "normal", "enabled": 1})
		family.insert(ignore_permissions=True)
		return url, family.name

	def test_deleting_the_last_snapshot_that_records_a_file_removes_it(self):
		url, family = self._recorded_upload("Released Font")
		path = Path(frappe.get_site_path("public", "files")) / url.rsplit("/", 1)[-1]
		first = self.capture()
		second = self.capture()
		frappe.delete_doc(FAMILY, family, force=1, flags={SKIP_RESTORE_POINT: True})
		frappe.db.commit()

		frappe.delete_doc(SNAPSHOT, first)
		frappe.db.commit()
		self.assertTrue(path.exists(), "another snapshot still records the file")

		frappe.delete_doc(SNAPSHOT, second)
		self.assertTrue(path.exists(), "nothing is deleted before the commit")
		frappe.db.commit()
		self.assertFalse(path.exists(), "the last record of the file is gone")

	def test_a_file_a_live_face_uses_survives_the_delete_of_its_snapshot(self):
		url, _family = self._recorded_upload("Live Font")
		path = Path(frappe.get_site_path("public", "files")) / url.rsplit("/", 1)[-1]
		name = self.capture()
		frappe.db.commit()

		frappe.delete_doc(SNAPSHOT, name)
		frappe.db.commit()
		self.assertTrue(path.exists())

	def test_a_rolled_back_snapshot_delete_keeps_the_file(self):
		url, family = self._recorded_upload("Rolled Back Font")
		path = Path(frappe.get_site_path("public", "files")) / url.rsplit("/", 1)[-1]
		name = self.capture()
		frappe.delete_doc(FAMILY, family, force=1, flags={SKIP_RESTORE_POINT: True})
		frappe.db.commit()

		frappe.delete_doc(SNAPSHOT, name)
		frappe.db.rollback()
		self.assertTrue(frappe.db.exists(SNAPSHOT, name))
		self.assertTrue(path.exists())


class TestRestoreGuards(SnapshotCase):
	def test_a_restore_requires_explicit_confirmation(self):
		name = self.capture()
		with self.assertRaises(frappe.ValidationError):
			service.restore_snapshot(name, mode="values")

	def test_a_restore_is_refused_while_another_operation_is_active(self):
		name = self.capture()
		blocker = frappe.new_doc(operations.OPERATION)
		blocker.kind = operations.IMPORT_PREVIEW
		blocker.status = "Queued"
		blocker.insert()

		with self.assertRaises(frappe.ValidationError):
			service.restore_snapshot(name, mode="values", confirm=1)

	def test_a_restore_of_an_unknown_snapshot_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			service.restore_snapshot(f"{MARKER}-missing", mode="values", confirm=1)
		with self.assertRaises(frappe.ValidationError):
			service.preview_restore(f"{MARKER}-missing")

	def test_starting_a_restore_needs_system_manager(self):
		name = self.capture()
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				service.restore_snapshot(name, mode="values", confirm=1)
			with self.assertRaises(frappe.PermissionError):
				service.preview_restore(name)
		finally:
			frappe.set_user("Administrator")

	def test_a_restore_preview_refuses_a_snapshot_that_does_not_exist(self):
		with self.assertRaises(frappe.ValidationError):
			operations.start_restore_preview(f"{MARKER}-missing")


class TestRestorePreview(SnapshotCase):
	def test_the_preview_is_queued_instead_of_running_inside_the_request(self):
		source = f"{MARKER} PREVIEW"
		self.translate(source, PERSIAN)
		name = self.capture()
		self.translate(source, REPLACED)

		before = frappe.db.count(SNAPSHOT)
		started = time.time()
		with patch.object(operations, "_enqueue") as queued:
			result = service.preview_restore(name)
		elapsed = time.time() - started

		self.assertEqual(queued.call_count, 1)
		self.assertEqual(queued.call_args.args[0], result["name"])
		self.assertEqual(result["status"], "Queued")
		self.assertEqual(result["applied"], 0)
		self.assertLess(elapsed, 5, "queueing a preview must not wait for the plan")
		self.assertEqual(frappe.db.count(SNAPSHOT), before, "a preview may not write a snapshot")

	def test_the_preview_reports_what_a_restore_would_change_and_writes_nothing(self):
		source = f"{MARKER} PREVIEW REPORT"
		self.translate(source, PERSIAN)
		name = self.capture()
		self.translate(source, REPLACED)

		queued = service.preview_restore(name)
		operations.run_operation(queued["name"])
		result = operations.get_operation(queued["name"])

		self.assertEqual(result["status"], "Completed")
		self.assertEqual(result["applied"], 0)
		self.assertEqual(result["checkpoint"], 0)
		preview = result["detail"]["preview"]
		self.assertGreaterEqual(preview["planned_actions"], 1)
		sample = {(row["source_text"], row["context"]): row["value"] for row in preview["sample"]}
		self.assertEqual(sample.get((source, "")), PERSIAN)
		self.assertEqual(self.stored(source), REPLACED, "a preview must not change a value")
		self.assertFalse(
			frappe.db.exists(SNAPSHOT, {"kind": snapshots.PRE_RESTORE, "label": ["like", f"%{name}%"]}),
			"a preview may not take an undo point",
		)

	def test_the_preview_honours_values_mode(self):
		later = f"{MARKER} PREVIEW LATER"
		name = self.capture()
		self.translate(later, "بعدی")

		queued = service.preview_restore(name, mode="values")
		operations.run_operation(queued["name"])
		result = operations.get_operation(queued["name"])

		self.assertEqual(result["detail"]["report"]["translations_removed"], 0)
		self.assertEqual(self.stored(later), "بعدی")


class TestPruning(SnapshotCase):
	def test_pruning_keeps_the_newest_disposable_snapshots_and_all_immutable_ones(self):
		immutable = self.capture(snapshots.ADOPTED_STATE, immutable=True)
		first = self.capture(snapshots.PRE_APPLY)
		second = self.capture(snapshots.PRE_APPLY)

		removed = snapshots.prune(snapshots.PRE_APPLY, keep=1)
		self.assertGreaterEqual(removed, 1)
		self.assertFalse(frappe.db.exists(SNAPSHOT, first))
		self.assertTrue(frappe.db.exists(SNAPSHOT, second))
		self.assertTrue(frappe.db.exists(SNAPSHOT, immutable), "an immutable snapshot is never pruned")
		self.assertEqual(
			frappe.db.count(SNAPSHOT, {"kind": snapshots.PRE_APPLY, "immutable": 0}),
			1,
			"pruning keeps exactly the requested number of disposable snapshots",
		)

	def test_pruning_never_touches_an_immutable_kind(self):
		before = frappe.db.count(SNAPSHOT, {"kind": snapshots.INSTALL_BASELINE})
		self.assertEqual(snapshots.prune(snapshots.INSTALL_BASELINE, keep=0), 0)
		self.assertEqual(frappe.db.count(SNAPSHOT, {"kind": snapshots.INSTALL_BASELINE}), before)


class TestFontPlan(SnapshotCase):
	def test_a_family_whose_files_are_missing_is_not_restored(self):
		payload = {
			"fonts": {
				"active_css": None,
				"families": [
					{
						"key": f"{MARKER}-missing-font",
						"family_name": f"{MARKER} Missing Font",
						"css_family": "",
						"source": "Uploaded",
						"is_active": 0,
						"faces": [
							[
								"missing.woff2",
								"/files/persian-font-missing.woff2",
								"",
								"WOFF2",
								"400",
								"normal",
								"normal",
								1,
							]
						],
					}
				],
			}
		}
		actions, report = snapshots._font_plan(payload, full=False, remove_fonts=False)
		self.assertEqual(report["fonts_restored"], 0)
		self.assertEqual(report["fonts_missing_files"], ["/files/persian-font-missing.woff2"])
		self.assertFalse([a for a in actions if a["type"] == "font_family_create"])

	def test_a_family_shipped_as_app_assets_is_not_restored(self):
		payload = {
			"fonts": {
				"active_css": None,
				"families": [
					{
						"key": f"{MARKER}-legacy-font",
						"family_name": f"{MARKER} Legacy Font",
						"css_family": "",
						"source": "Bundled",
						"is_active": 0,
						"faces": [
							[
								"Legacy-Regular.woff2",
								"/assets/smartprocee_erpnext_persiant/fonts/Legacy-Regular.woff2",
								"",
								"WOFF2",
								"400",
								"normal",
								"normal",
								1,
							]
						],
					}
				],
			}
		}
		actions, report = snapshots._font_plan(payload, full=False, remove_fonts=False)
		self.assertEqual(report["fonts_restored"], 0)
		self.assertFalse([a for a in actions if a["type"] == "font_family_create"])

	def test_a_restore_never_removes_fonts_unless_it_is_asked_to(self):
		# The active stylesheet is recorded as it is, so the plan has nothing to
		# re-activate: this test is about removal, not about activation.
		payload = {"fonts": {"active_css": snapshots._active_css(), "families": []}}
		actions, _report = snapshots._font_plan(payload, full=True, remove_fonts=False)
		self.assertFalse([a for a in actions if a["type"] == "font_family_delete"])
		self.assertFalse([a for a in actions if a["type"] == "font_activate"])
