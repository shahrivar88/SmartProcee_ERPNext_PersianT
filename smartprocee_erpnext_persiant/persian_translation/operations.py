"""Durable background work for the Translation Manager.

Every long Excel preview, Excel apply, snapshot preview and snapshot restore runs
here, never in the request. One record of type `Persian Translation Operation` per
run is the single source of truth for progress, so a closed browser tab changes
nothing and no HTTP request has to survive a long import.

Guarantees this module is responsible for:

* **One writer at a time.** An apply and a restore both take one database lease
  (`lock_key`, a unique column). The database, not a check-then-insert window, is
  what refuses a second writer, so two operations can never write the translation
  tables at the same time -- whatever file or snapshot they name.
* **A fenced lease.** A claim hands out a `lease_token`, and the worker checks it
  still owns that token before every batch. A worker that lost the operation stops
  writing instead of racing the worker that took over.
* **Stale recovery.** `heartbeat` is refreshed before every batch. A `Running`
  operation whose heartbeat is older than `STALE_SECONDS` belonged to a worker
  that died and may be resumed; a live worker can never be taken over. A `Queued`
  operation whose job never reached the queue is closed as failed before the next
  admission, so a dead job cannot hold the lease or block a restore forever.
* **A plan that cannot drift.** The ordered plan of an apply is stored, with the
  workbook hash it was built from, on the first pass and reused verbatim on a
  resume. `checkpoint` is a position in that one list, so a rebuilt plan can never
  shift the cursor and no row can be skipped or applied twice.
* **Bounded transactions.** Rows are applied in batches. One batch and its
  checkpoint are committed together, so the checkpoint can never claim more work
  than the database holds.
* **Per-row isolation.** Each row is applied inside its own savepoint, so one
  rejected or failing row cannot undo the healthy rows of the same batch.
* **Idempotency.** Writing the same value again is a no-op, so re-running a
  resumed batch or re-applying an already applied workbook cannot double-apply.
* **Honest counts.** `applied`, `unchanged`, `rejected` and `failed` are counted
  from what actually happened, never estimated.
* **Honest diagnostics.** The values a rejection reports are stored verbatim, so
  `before` is what Frappe would have received and `after` is what it would store.
  Every row that was not applied -- rejected or failed -- is kept in a compressed
  list, and that list is what the error workbook is built from, so a large import
  cannot silently lose rows from the file.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path

import frappe
from frappe.database import savepoint
from frappe.utils import cint, get_datetime, now, now_datetime

from smartprocee_erpnext_persiant.persian_translation import ownership, snapshots
from smartprocee_erpnext_persiant.persian_translation.doctype.persian_font_family.persian_font_family import (
	SKIP_RESTORE_POINT,
)
from smartprocee_erpnext_persiant.persian_translation.excel_io import (
	build_error_workbook,
	classify_import_rows,
	read_workbook,
)

OPERATION = "Persian Translation Operation"
IMPORT_PREVIEW = "import_preview"
IMPORT_APPLY = "import_apply"
SNAPSHOT_PREVIEW = "snapshot_preview"
SNAPSHOT_RESTORE = "snapshot_restore"
IMPORT_KINDS = (IMPORT_PREVIEW, IMPORT_APPLY)
# Kinds that only read and report. They never write a row and never take an undo point.
PREVIEW_KINDS = (IMPORT_PREVIEW, SNAPSHOT_PREVIEW)
SNAPSHOT_KINDS = (SNAPSHOT_PREVIEW, SNAPSHOT_RESTORE)
# Kinds that write translation state, so they need the lease and an undo point.
MUTATING_KINDS = (IMPORT_APPLY, SNAPSHOT_RESTORE)

QUEUE = "long"
JOB_TIMEOUT = 60 * 60
BATCH_SIZE = 50
# A worker refreshes `heartbeat` before every batch; an operation whose heartbeat
# is older than `STALE_SECONDS` belonged to a worker that died and may be resumed.
HEARTBEAT_SECONDS = 30
STALE_SECONDS = 300
# A `Queued` operation whose job is gone from the queue and that has sat untouched
# for this long was never picked up (a worker container was down, or the enqueue
# was lost). It may not hold the lease, or block the next operation, forever.
QUEUED_GRACE_SECONDS = 120
# The name of the one lease a mutating operation holds. Every mutating operation
# takes the same lease, because every one of them writes the same tables.
LEASE_KEY = "translations"
MAX_STORED_ERRORS = 2000
ACTIVE_STATUSES = ("Queued", "Running")
FINISHED_STATUSES = ("Completed", "Partial", "Failed", "Cancelled")

# Action types one operation may contain.
TRANSLATION_UPSERT = "translation_upsert"
TRANSLATION_DELETE = "translation_delete"
FONT_FAMILY_CREATE = "font_family_create"
FONT_FAMILY_DELETE = "font_family_delete"
FONT_ACTIVATE = "font_activate"
RTL_RESTORE = "rtl_restore"

# Outcomes of a single row.
APPLIED = "applied"
UNCHANGED = "unchanged"


def require_system_manager():
	from smartprocee_erpnext_persiant.persian_translation.service import require_system_manager as check

	check()


# --------------------------------------------------------------------------- #
# Starting an operation
# --------------------------------------------------------------------------- #


def start_import(file_url: str, preview: int = 0) -> dict:
	"""Queue a preview or an apply of an exported workbook. Returns immediately."""
	return _start(
		kind=IMPORT_PREVIEW if cint(preview) else IMPORT_APPLY,
		file_url=(file_url or "").strip(),
	)


def start_restore(snapshot: str, mode: str = "full", remove_fonts: int = 0, confirm: int = 0) -> dict:
	"""Queue a targeted restore of one snapshot. Requires explicit confirmation.

	The undo point is not taken here: reading the whole translation state into a
	snapshot is the same work a restore does, and it must not block the request.
	The worker takes it as its first step, before it writes anything.
	"""
	require_system_manager()
	if not cint(confirm):
		frappe.throw("برای بازگردانی، تأیید صریح لازم است.")
	return _start(
		kind=SNAPSHOT_RESTORE,
		snapshot=_require_snapshot(snapshot),
		detail={
			"mode": "values" if mode == "values" else "full",
			"remove_fonts": cint(remove_fonts),
		},
	)


def start_restore_preview(snapshot: str, mode: str = "full", remove_fonts: int = 0) -> dict:
	"""Queue a read-only preview of what a restore would change.

	The plan is built by the worker, not by the request: it reads every Persian
	translation row and every lock, which is the same work a restore would do, so
	it may not block an HTTP request.
	"""
	require_system_manager()
	return _start(
		kind=SNAPSHOT_PREVIEW,
		snapshot=_require_snapshot(snapshot),
		detail={
			"mode": "values" if mode == "values" else "full",
			"remove_fonts": cint(remove_fonts),
		},
	)


def _require_snapshot(snapshot: str) -> str:
	if not snapshot or not frappe.db.exists(snapshots.SNAPSHOT, snapshot):
		frappe.throw("نسخهٔ پشتیبان انتخاب‌شده پیدا نشد.")
	return snapshot


def _start(kind: str, file_url: str = "", snapshot: str = "", detail: dict | None = None) -> dict:
	"""Create the operation record, then queue it. Returns without waiting for a worker."""
	name = _create(kind, file_url=file_url, snapshot=snapshot, detail=detail)
	_enqueue(name)
	return summarize(name)


def _create(kind: str, file_url: str = "", snapshot: str = "", detail: dict | None = None) -> str:
	"""Create the record and take the writer lease. Never captures an undo point.

	The lease is a unique column, so the insert itself is the atomic admission:
	`_guard` only exists to explain the refusal in Persian before the database
	does. A second mutating operation cannot slip through between the check and
	the insert, because both would write the same `lock_key`.
	"""
	require_system_manager()
	recover_abandoned()
	_guard(kind, file_url)
	doc = frappe.new_doc(OPERATION)
	doc.kind = kind
	doc.status = "Queued"
	doc.file_url = file_url
	doc.file_name = _file_name(file_url) if file_url else ""
	doc.snapshot = snapshot or ""
	doc.lock_key = LEASE_KEY if kind in MUTATING_KINDS else None
	doc.detail = json.dumps(dict(detail or {}), ensure_ascii=False)
	try:
		doc.insert()
	except Exception as exc:  # noqa: BLE001 - re-raised unless it is the lease
		frappe.db.rollback()
		if not _is_duplicate(exc):
			raise
		frappe.throw(_busy_message(kind))
	frappe.db.commit()
	return doc.name


def _is_duplicate(exc: Exception) -> bool:
	"""True when the database refused the row because the lease was already held.

	Frappe reports a duplicate primary key as `DuplicateEntryError` and a violated
	unique index as `UniqueValidationError`; the two are checked by name and by
	message so neither has to be guessed.
	"""
	return isinstance(
		exc, (frappe.DuplicateEntryError, frappe.UniqueValidationError)
	) or "Duplicate entry" in str(exc)


def _busy_message(kind: str) -> str:
	if kind == SNAPSHOT_RESTORE:
		return "همین حالا یک بازگردانی در جریان است. تا پایان آن بازگردانی تازه‌ای شروع نمی‌شود."
	return "همین حالا یک عملیات در حال نوشتن است. تا پایان آن، اعمال تازه‌ای شروع نمی‌شود."


def _enqueue(name: str, attempt: int = 0) -> None:
	"""Queue the worker for this operation.

	The job id is derived from the operation, so the queued job can always be
	looked up again (`is_job_enqueued`), and a resume gets its own id instead of
	colliding with the stopped one. `enqueue_after_commit` makes the job visible
	only after the row that describes it is committed.

	A test never pushes a real job unless it asks to (`real_queue`): a live worker
	would run the job against the same site while the test still holds its
	transaction, which is a race that shows up as lock timeouts and stray
	"document not found" errors in the worker log rather than as a test failure.
	"""
	job_id = _job_id(name, attempt)
	frappe.db.set_value(OPERATION, name, "job_id", job_id, update_modified=False)
	if not _queue_enabled():
		return
	frappe.enqueue(
		"smartprocee_erpnext_persiant.persian_translation.operations.run_operation",
		operation=name,
		queue=QUEUE,
		timeout=JOB_TIMEOUT,
		enqueue_after_commit=True,
		job_id=job_id,
	)


def _job_id(name: str, attempt: int = 0) -> str:
	return f"ptm-operation-{name}-{attempt}"


def _queue_enabled() -> bool:
	"""Whether a real job may be pushed onto the shared queue right now.

	Outside a test run this is always yes. Inside one it is yes only when the test
	asked for the real queue, so the suite does not race its own worker
	containers on the site it is testing.
	"""
	if not getattr(frappe.flags, "in_test", False):
		return True
	return bool(getattr(frappe.flags, "ptm_real_queue", False))


def _guard(kind: str, file_url: str) -> None:
	"""Explain, in Persian, why this operation is refused before the database does.

	Advisory only: the unique `lock_key` of the operation row is what actually
	guarantees that only one mutating operation exists at a time. This function
	exists so the operator gets a readable reason instead of a duplicate-key error.
	"""
	active = frappe.get_all(
		OPERATION,
		filters={"status": ["in", list(ACTIVE_STATUSES)]},
		fields=["name", "kind", "file_url"],
		limit_page_length=0,
	)
	if kind in SNAPSHOT_KINDS:
		if kind == SNAPSHOT_RESTORE and active:
			frappe.throw(
				"تا زمانی که یک عملیات در صف یا در حال اجراست، بازگردانی شروع نمی‌شود: "
				+ "، ".join(row.name for row in active[:5])
			)
		return
	if not file_url:
		frappe.throw("فایل اکسل انتخاب نشده است.")
	busy = [row.name for row in active if row.file_url == file_url]
	if busy:
		frappe.throw(
			"برای همین فایل یک عملیات در صف یا در حال اجراست: " + "، ".join(busy[:5])
		)
	if kind in MUTATING_KINDS:
		# Two different workbooks both write the same Translation rows, so they may
		# not run together either.
		writing = [row.name for row in active if row.kind in MUTATING_KINDS]
		if writing:
			frappe.throw(
				"همین حالا یک عملیات در حال نوشتن روی ترجمه‌هاست. تا پایان آن، اعمال تازه‌ای شروع نمی‌شود: "
				+ "، ".join(writing[:5])
			)


def _file_checksum(path) -> str:
	"""The exact bytes of the workbook a plan was built from."""
	return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stored_checksum(doc) -> str:
	return str(_detail(doc.detail).get("plan_checksum") or "")


def _plan_checksum(kind: str, file_url: str) -> str:
	from smartprocee_erpnext_persiant.persian_translation.service import _file_from_url

	if kind not in IMPORT_KINDS or not file_url:
		return ""
	return _file_checksum(_file_from_url(file_url))


def _file_name(file_url: str) -> str:
	name = frappe.db.get_value("File", {"file_url": file_url}, "file_name")
	return name or file_url.rsplit("/", 1)[-1]


def _ensure_undo_point(doc) -> None:
	"""Take this operation's undo point, inside the worker, before its first write.

	Capture reads the whole translation state and every lock, so it belongs in the
	background job and not in the HTTP request that queued it. It runs after the
	worker owns the lease and before the first row is written, so nothing else can
	mutate the translation tables between the snapshot and the first write. A
	resume reuses the undo point the first pass took.
	"""
	if doc.kind not in MUTATING_KINDS:
		return
	detail = _detail(doc.detail)
	if detail.get("undo_snapshot"):
		return
	if doc.kind == SNAPSHOT_RESTORE:
		kind = snapshots.PRE_RESTORE
		label = f"وضعیت کنونی پیش از بازگردانی {doc.snapshot}"
		note = "برای برگرداندن نتیجهٔ بازگردانی. اگر بازگردانی اشتباه بود، همین نسخه را بازگردانید."
	else:
		kind = snapshots.PRE_APPLY
		label = f"وضعیت ترجمه‌ها پیش از اعمال {doc.file_name or doc.file_url}"
		note = "برای برگرداندن نتیجهٔ همین فایل اکسل."
	undo = snapshots.capture(kind, label, note=note)
	detail["undo_snapshot"] = undo["name"]
	doc.detail = json.dumps(detail, ensure_ascii=False)
	frappe.db.set_value(OPERATION, doc.name, "detail", doc.detail, update_modified=False)
	frappe.db.commit()


def pending_operations() -> list[dict]:
	"""The operations that are queued or running right now.

	The timestamps are returned as strings: this list travels inside the stored
	`detail` JSON of a preview, and a `datetime` there would not serialise.
	"""
	rows = frappe.get_all(
		OPERATION,
		filters={"status": ["in", list(ACTIVE_STATUSES)]},
		fields=["name", "kind", "status", "file_url", "snapshot", "processed", "planned", "started_at"],
		order_by="creation desc",
		limit_page_length=20,
	)
	return [
		{**row, "started_at": str(row.get("started_at") or "")}
		for row in rows
	]


# --------------------------------------------------------------------------- #
# Reading an operation
# --------------------------------------------------------------------------- #


def get_operation(name: str) -> dict:
	return summarize(name, with_detail=True)


def summarize(name: str, with_detail: bool = False) -> dict:
	doc = frappe.get_doc(OPERATION, name)
	_check_read(doc)
	detail = _detail(doc.detail)
	# The stored plan and the full error list can be megabytes; they never travel
	# to the browser. What the manager needs to know is that they exist and how
	# much is in them.
	full_errors = detail.pop("errors_full", None)
	plan_blob = detail.pop("plan_blob", None)
	payload = {
		"name": doc.name,
		"kind": doc.kind,
		"status": doc.status,
		"file_url": doc.file_url or "",
		"file_name": doc.file_name or "",
		"snapshot": doc.snapshot or "",
		"total_rows": cint(doc.total_rows),
		"planned": cint(doc.planned),
		"processed": cint(doc.processed),
		"checkpoint": cint(doc.checkpoint),
		"applied": cint(doc.applied),
		"unchanged": cint(doc.unchanged),
		"rejected": cint(doc.rejected),
		"failed": cint(doc.failed),
		"error_count": cint(doc.error_count),
		"resume_count": cint(doc.resume_count),
		"cancel_requested": bool(doc.cancel_requested),
		"started_at": str(doc.started_at or ""),
		"finished_at": str(doc.finished_at or ""),
		"summary": doc.summary or "",
		"detail": detail,
		"errors": [_error_payload(row) for row in doc.errors[:200]],
		"errors_truncated": cint(doc.error_count) > min(len(doc.errors), 200),
		"errors_full_count": len(_decode_blob(full_errors)) if full_errors else len(doc.errors),
		"plan_stored": bool(plan_blob),
		"stale": is_stale(doc),
	}
	if with_detail:
		payload["owner"] = doc.owner
		payload["job_id"] = doc.job_id or ""
		payload["lease_token"] = doc.lease_token or ""
	return payload


def _detail(raw) -> dict:
	if not raw:
		return {}
	try:
		parsed = json.loads(raw)
	except (TypeError, ValueError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _error_payload(row) -> dict:
	return {
		"excel_row": cint(row.excel_row),
		"sheet": row.sheet or "",
		"app": row.app or "",
		"code": row.code or "",
		"source_text": row.source_text or "",
		"translated_text": row.translated_text or "",
		"context": row.context or "",
		"identity": row.identity or "",
		"reason": row.reason or "",
		"action": row.action or "",
		"before": row.before or "",
		"after": row.after or "",
	}


def _check_read(doc) -> None:
	user = frappe.session.user
	if user in ("Administrator", doc.owner):
		return
	if "System Manager" in set(frappe.get_roles()):
		return
	frappe.throw("دسترسی به این عملیات مجاز نیست.", frappe.PermissionError)


def list_operations(limit: int = 20) -> list[dict]:
	require_system_manager()
	names = frappe.get_all(
		OPERATION,
		pluck="name",
		order_by="creation desc",
		limit_page_length=min(max(cint(limit) or 20, 1), 100),
	)
	return [summarize(name) for name in names]


def export_errors(name: str):
	"""Stream one workbook listing every row this operation did not apply.

	Built from the complete stored list, never from the capped child rows: a
	rejected or failed row may never be missing from this file.
	"""
	doc = frappe.get_doc(OPERATION, name)
	_check_read(doc)
	errors = _all_errors(doc)
	frappe.response["filename"] = f"persian-import-errors-{doc.name}.xlsx"
	frappe.response["filecontent"] = build_error_workbook(errors)
	frappe.response["type"] = "binary"
	frappe.response["display_content_as"] = "attachment"


def _all_errors(doc) -> list[dict]:
	detail = _detail(doc.detail)
	stored = detail.get("errors_full")
	if stored:
		return _decode_blob(stored)
	return [_error_payload(row) for row in doc.errors]


# --------------------------------------------------------------------------- #
# Cancel and resume
# --------------------------------------------------------------------------- #


def cancel_operation(name: str) -> dict:
	require_system_manager()
	doc = frappe.get_doc(OPERATION, name)
	if doc.status in FINISHED_STATUSES:
		return {"cancelled": False, "status": doc.status}
	frappe.db.set_value(OPERATION, name, "cancel_requested", 1, update_modified=False)
	frappe.db.commit()
	return {"cancelled": True, "status": doc.status}


def resume_operation(name: str) -> dict:
	"""Re-queue a stopped operation. It continues at the cursor after the last committed row.

	A `Running` operation is only taken over when its worker is provably gone: its
	heartbeat must be older than `STALE_SECONDS`. A live worker is never stolen
	from, and if it is somehow still alive it stops as soon as it notices that the
	lease token is no longer its own.
	"""
	require_system_manager()
	# Two resumes of the same row are serialised here: the second one reads the
	# `Queued` status the first one committed and is refused below.
	frappe.db.get_value(OPERATION, name, "name", for_update=True)
	doc = frappe.get_doc(OPERATION, name)
	if doc.status in ACTIVE_STATUSES and not is_abandoned(doc):
		frappe.throw("این عملیات هنوز تمام نشده و در صف یا در حال اجراست.")
	if doc.kind in SNAPSHOT_KINDS:
		_guard(doc.kind, "")
	elif doc.status not in ACTIVE_STATUSES and cint(doc.processed) >= cint(doc.planned):
		frappe.throw("این عملیات به آخرین ردیف رسیده است و ادامه‌دادن معنایی ندارد.")
	_assert_workbook_unchanged(doc)
	values = {
		"status": "Queued",
		"cancel_requested": 0,
		"resume_count": cint(doc.resume_count) + 1,
		"finished_at": None,
		"summary": "",
		"lease_token": "",
	}
	if doc.kind in MUTATING_KINDS:
		# `_finish` released the writer lease; a resumed writer must hold it again,
		# so the unique `lock_key` refuses it while any other writer is active.
		values["lock_key"] = LEASE_KEY
	try:
		frappe.db.set_value(OPERATION, name, values, update_modified=False)
	except Exception as exc:  # noqa: BLE001 - re-raised unless it is the lease
		frappe.db.rollback()
		if not _is_duplicate(exc):
			raise
		frappe.throw(_busy_message(doc.kind))
	frappe.db.commit()
	_enqueue(name, attempt=cint(doc.resume_count) + 1)
	return summarize(name)


def is_stale(doc) -> bool:
	"""True when a `Running` operation belongs to a worker that is no longer there.

	`Queued` is never stale: it has not been claimed yet, so nothing has died.
	"""
	if doc.status != "Running":
		return False
	stamp = doc.heartbeat or doc.started_at
	if not stamp:
		return True
	return (now_datetime() - get_datetime(stamp)).total_seconds() > STALE_SECONDS


def is_abandoned(doc) -> bool:
	"""True when no worker can still be running this operation.

	This is the wider question `_guard` and `resume` need: a `Running` row whose
	worker died (`is_stale`) and a `Queued` row whose job is no longer in the
	queue both hold the lease for nobody. Only the second case can be *proved*
	abandoned and not merely quiet, so a `Queued` row is checked against the queue
	itself, and a young one is never touched: the row is committed before the job
	is enqueued, so for a moment it is legitimately `Queued` without a job.
	"""
	if doc.status == "Running":
		return is_stale(doc)
	if doc.status != "Queued":
		return False
	if (now_datetime() - get_datetime(doc.modified or doc.creation)).total_seconds() <= QUEUED_GRACE_SECONDS:
		return False
	return not _job_still_known(doc.job_id)


def _job_still_known(job_id) -> bool:
	"""Whether the queue still has, or ever ran, this job.

	A job id the queue has never heard of is a job that was never enqueued: the
	worker container was down, or the enqueue was lost after the row was
	committed. When the queue cannot be reached at all the answer is `True`,
	because closing a live operation would be the worse mistake.
	"""
	job_id = str(job_id or "")
	if not job_id:
		return False
	try:
		from frappe.utils.background_jobs import get_job_status, is_job_enqueued

		return bool(is_job_enqueued(job_id)) or get_job_status(job_id) is not None
	except Exception:  # noqa: BLE001 - an unreachable queue must not close a live job
		return True


def recover_abandoned() -> list[str]:
	"""Close the operations no worker can still run, and release their lease.

	Run before every admission. A dead `Running` operation or a `Queued` one whose
	job never reached the queue holds `lock_key`, and a held lease would refuse
	the next apply or restore forever with a message about an operation that will
	never finish. Closing the row is what releases that lease.

	Safe to call at any time and for any number of times: a live worker's row has
	a fresh heartbeat or a young `Queued` status, so it is never touched, and an
	operation that was already closed is no longer active.
	"""
	recovered = []
	for name in frappe.get_all(
		OPERATION,
		filters={"status": ["in", list(ACTIVE_STATUSES)]},
		pluck="name",
		limit_page_length=0,
	):
		doc = frappe.get_doc(OPERATION, name)
		if not is_abandoned(doc):
			continue
		if doc.status == "Running":
			summary = "اجرای این عملیات نیمه‌کاره ماند. ردیف‌های اعمال‌شده دست‌نخورده‌اند؛ برای ادامه، عملیات را از سر بگیرید."
		else:
			summary = "این عملیات اجرا نشد. برای اجرا، آن را دوباره شروع کنید."
		_finish(doc, "Failed", summary)
		recovered.append(name)
	return recovered


def _still_owns(operation: str, token: str) -> bool:
	"""Whether this worker is still the one allowed to write.

	Read in a fresh transaction, because the row this worker holds in memory is
	exactly the row another worker may have changed after it went stale.
	"""
	frappe.db.commit()
	return frappe.db.get_value(OPERATION, operation, "lease_token") == token


def _assert_workbook_unchanged(doc) -> None:
	"""Refuse to continue a half-applied workbook that is not the same file any more.

	`processed` and `checkpoint` describe positions inside one specific file. If
	the workbook changed after the stop, those positions no longer mean the same
	rows, so continuing would silently skip or repeat work. Failing loudly is the
	only honest option.
	"""
	if doc.kind not in IMPORT_KINDS or not cint(doc.processed):
		return
	stored = _stored_checksum(doc)
	if not stored:
		return
	current = _plan_checksum(doc.kind, doc.file_url)
	if current != stored:
		frappe.throw(
			"فایل اکسل پس از توقف عملیات تغییر کرده است. برای جلوگیری از جاافتادن یا تکرار ردیف‌ها، "
			"این عملیات ادامه داده نمی‌شود؛ فایل اصلی را برگردانید یا یک عملیات تازه شروع کنید."
		)


# --------------------------------------------------------------------------- #
# The job
# --------------------------------------------------------------------------- #


def run_operation(operation: str) -> dict:
	"""Background entry point. Owns exactly one operation for its whole lifetime."""
	doc = frappe.get_doc(OPERATION, operation)
	if doc.status not in ACTIVE_STATUSES:
		return {"skipped": True, "status": doc.status}
	token = _claim(operation)
	if not token:
		return {"skipped": True, "reason": "another worker claimed it"}
	try:
		_become_owner(doc)
		_ensure_undo_point(doc)
		actions, summary = _build_plan(doc)
		_assert_workbook_unchanged(doc)
		_record_plan(doc, actions, summary)
		if doc.kind in PREVIEW_KINDS:
			_finish(doc, "Completed", summary.get("summary") or "")
			return summarize(operation)
		_execute(doc, actions, token)
	except Exception as exc:  # noqa: BLE001 - the operation record is the report
		frappe.db.rollback()
		frappe.log_error(title=f"Persian operation {operation} failed", message=frappe.get_traceback())
		_finish_failed(doc, exc)
		return {"failed": True, "error": str(exc)[:500]}
	return summarize(operation)


def _claim(operation: str) -> str | None:
	"""Take the operation for this worker. Returns the lease token, or None.

	`for_update` makes the claim atomic: only one worker can read a `Queued` row
	and commit it as `Running` with its own token before the other one looks. A row
	that is already `Running` belongs to another worker, or to one that died;
	neither case may be taken over here. Only an explicit resume re-queues a
	stopped operation, and it hands the next worker a fresh token.
	"""
	token = frappe.generate_hash(length=32)
	status = frappe.db.get_value(OPERATION, operation, "status", for_update=True)
	if status != "Queued":
		frappe.db.rollback()
		return None
	frappe.db.set_value(
		OPERATION,
		operation,
		{"status": "Running", "started_at": now(), "heartbeat": now(), "lease_token": token},
		update_modified=False,
	)
	frappe.db.commit()
	return token


def _become_owner(doc) -> None:
	"""A background job has no session, so the owner's own permissions are used."""
	owner = doc.owner
	if owner and owner not in ("Guest", ""):
		frappe.set_user(owner)
	if not doc.owner or doc.owner in ("Guest", ""):
		frappe.throw("این عملیات صاحب مشخصی ندارد و اجرا نمی‌شود.")
	if "System Manager" not in set(frappe.get_roles()):
		frappe.throw(f"کاربر «{doc.owner}» دیگر System Manager نیست و عملیات متوقف شد.")


def _build_plan(doc) -> tuple[list[dict], dict]:
	if doc.kind in SNAPSHOT_KINDS:
		detail = _detail(doc.detail)
		if doc.kind == SNAPSHOT_RESTORE and detail.get("plan_blob"):
			# A rebuilt restore plan drops the rows the first pass already restored
			# and renumbers the rest, so the checkpoint -- a position in the first
			# plan -- would skip rows that were never written. Like an import, a
			# resumed restore continues in the plan its checkpoint was measured in.
			return _stored_plan(detail)
		actions, report = snapshots.build_plan(
			doc.snapshot,
			mode=detail.get("mode") or "full",
			remove_fonts=cint(detail.get("remove_fonts")),
		)
		_number(actions)
		report["summary"] = _restore_summary(report)
		if doc.kind == SNAPSHOT_PREVIEW:
			# A preview writes nothing: the plan is reported, not executed, so
			# `planned` stays zero and the whole report travels in `detail`.
			report["file_rows"] = len(actions)
			report["preview"] = _restore_preview_payload(actions, report)
			return [], report
		return actions, report
	return _import_plan(doc)


def _stored_plan(detail: dict) -> tuple[list[dict], dict]:
	blob = _decode_blob(detail["plan_blob"])
	summary = dict(blob.get("summary") or {})
	summary["errors"] = []
	return blob.get("actions") or [], summary


def _number(actions: list[dict]) -> list[dict]:
	"""Give a restore action its position in the plan, which is the resume cursor.

	An apply action already carries the workbook row it came from, and the plan is
	in workbook order, so the same cursor works there too.
	"""
	for position, action in enumerate(actions, start=1):
		if not cint(action.get("row_index")):
			action["row_index"] = position
	return actions


def _import_plan(doc) -> tuple[list[dict], dict]:
	from smartprocee_erpnext_persiant.persian_translation.identity import translation_identity
	from smartprocee_erpnext_persiant.persian_translation.service import _file_from_url, effective_translation

	path = _file_from_url(doc.file_url)
	checksum = _file_checksum(path)
	stored = _detail(doc.detail)
	if stored.get("plan_blob") and stored.get("plan_checksum") == checksum:
		# The first pass fixed the order of this workbook and stored it. Rebuilding
		# the plan now would read a translation table that pass has already partly
		# changed: the rows it wrote classify as `unchanged`, drop out of the list,
		# and the checkpoint -- still a position in the original list -- would then
		# point past rows that were never written. The stored plan is the only list
		# the checkpoint means anything in, so a resume continues in it verbatim.
		blob = _decode_blob(stored["plan_blob"])
		summary = dict(blob.get("summary") or {})
		summary["errors"] = []
		summary["plan_checksum"] = checksum
		return blob.get("actions") or [], summary
	file_rows = read_workbook(path)
	classified = classify_import_rows(file_rows, effective_translation, translation_identity)
	actions = [_upsert_action(row) for row in classified["actions"]] if doc.kind == IMPORT_APPLY else []
	summary = {
		"file_rows": classified["file_rows"],
		"unchanged": classified["unchanged"],
		"new": classified["new"],
		"changed": classified["changed"],
		"errors": classified["errors"],
		"plan_checksum": checksum,
		"summary": (
			f"{classified['file_rows']} ردیف خوانده شد؛ "
			f"{classified['new']} ترجمه تازه، {classified['changed']} تغییر، "
			f"{classified['unchanged']} بی‌تغییر، {len(classified['errors'])} رد‌شده."
		),
	}
	return actions, summary


def _upsert_action(row: dict) -> dict:
	"""Turn one classified workbook row into the action the engine executes.

	The importer describes *rows* (with the cell they came from); the engine
	executes *actions*. Keeping the sheet, the Excel row, the plan position and the
	identity on the action is what makes a runtime failure reportable and makes a
	resume continue at the right row: the plan is in workbook order, so its
	positions are monotonic and a cursor into it can never step over a pending row.
	"""
	return {
		"type": TRANSLATION_UPSERT,
		"source_text": row["source_text"],
		"context": row.get("context") or "",
		"value": row["translated_text"],
		"app": row.get("app") or "",
		"sheet": row.get("sheet") or "",
		"excel_row": cint(row.get("excel_row")),
		"row_index": cint(row.get("row_index")),
		"identity": row.get("identity") or "",
	}


def _restore_preview_payload(actions, report: dict) -> dict:
	"""What `snapshot_preview` reports: how much would change, and a sample of it."""
	sample = [action for action in actions if action["type"] in ("translation_upsert", "translation_delete")][:20]
	return {
		"planned_actions": len(actions),
		"pending_operations": pending_operations(),
		"sample": [
			{
				"type": action["type"],
				"source_text": action.get("source_text") or "",
				"context": action.get("context") or "",
				"value": action.get("value") or "",
			}
			for action in sample
		],
	}


def _record_plan(doc, actions, summary: dict) -> None:
	errors = summary.get("errors") or []
	doc.reload()
	first_run = not cint(doc.processed)
	doc.status = "Running"
	doc.total_rows = cint(summary.get("file_rows") or len(actions))
	if first_run:
		# Only the first pass writes the plan, the rejection list and the total.
		# A resume keeps the rows already recorded, including the runtime failures
		# and the plan the checkpoint was measured in; `_execute` then sets the
		# exact total from the actions that are still outstanding.
		doc.planned = max(cint(doc.planned), cint(doc.processed) + len(actions))
		doc.rejected = len(errors)
		doc.error_count = len(errors)
		doc.set("errors", [])
		for error in errors[:MAX_STORED_ERRORS]:
			doc.append("errors", _stored_error(error))
	doc.unchanged = cint(summary.get("unchanged"))
	payload = {
		**_detail(doc.detail),
		"report": _report_payload(summary),
		"errors_truncated": len(errors) > MAX_STORED_ERRORS,
	}
	if summary.get("plan_checksum"):
		payload["plan_checksum"] = summary["plan_checksum"]
	if summary.get("preview"):
		payload["preview"] = summary["preview"]
	if first_run:
		if doc.kind in MUTATING_KINDS:
			payload["plan_blob"] = _encode_blob(
				{
					"actions": actions,
					"summary": {key: value for key, value in summary.items() if key != "errors"},
				}
			)
		_append_errors(payload, [_stored_error(error) for error in errors])
	doc.detail = json.dumps(payload, ensure_ascii=False)
	_save(doc)
	frappe.db.commit()


def _stored_error(error: dict) -> dict:
	"""One row of the error workbook, exactly as it will be exported."""
	return {
		"excel_row": cint(error.get("excel_row")),
		"sheet": error.get("sheet") or "",
		"app": error.get("app") or "",
		"code": error.get("code") or "",
		"source_text": error.get("source_text") or "",
		"translated_text": error.get("translated_text") or "",
		"context": error.get("context") or "",
		"identity": error.get("identity") or "",
		"reason": error.get("reason") or error.get("message") or "",
		"action": error.get("action") or "",
		"before": error.get("before") or "",
		"after": error.get("after") or "",
	}


def _append_errors(payload: dict, rows: list[dict]) -> None:
	"""Keep every row that was not applied, beyond the capped child table.

	`doc.errors` is a readable sample; this is the record. The error workbook is
	built from it, so a limit on how much is shown can never drop rows from the
	file the operator has to work through.
	"""
	if not rows:
		return
	stored = _decode_blob(payload["errors_full"]) if payload.get("errors_full") else []
	stored.extend(rows)
	payload["errors_full"] = _encode_blob(stored)


def _encode_blob(value) -> str:
	raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
	return base64.b64encode(zlib.compress(raw, 6)).decode("ascii")


def _decode_blob(blob: str):
	return json.loads(zlib.decompress(base64.b64decode(blob)).decode("utf-8"))


def _report_payload(summary: dict) -> dict:
	report = {}
	for key, value in summary.items():
		if key == "errors":
			continue
		if isinstance(value, list):
			report[key] = value[:50]
		elif isinstance(value, dict):
			continue
		else:
			report[key] = value
	return report


def _restore_summary(report: dict) -> str:
	text = (
		f"بازگردانی {report['snapshot']} ({report['mode']}): "
		f"{report['translations_restored']} ترجمه بازنویسی، {report['translations_removed']} ترجمه حذف، "
		f"{report['fonts_restored']} خانواده فونت."
	)
	if report.get("preserved_unowned"):
		text += (
			f" {report['preserved_unowned']} ترجمه که این برنامه ننوشته بود دست‌نخورده ماند"
			" (حذف نشد)."
		)
	if report.get("overwritten"):
		text += (
			f" {report['overwritten']} ترجمه پس از آخرین نوشتن این برنامه تغییر کرده بود و"
			" بازنویسی شد."
		)
	return text


# --------------------------------------------------------------------------- #
# Executing the plan, in bounded batches
# --------------------------------------------------------------------------- #


def _execute(doc, actions, token: str) -> None:
	"""Apply the rows that are still outstanding, batch by batch.

	`checkpoint` is a position in the stored plan and the plan is in workbook
	order, so "still outstanding" is exactly "position greater than the last
	committed one". A rebuilt plan cannot shift the cursor, because on a resume
	there is no rebuilt plan: the one the checkpoint was measured in is reused.

	The worker checks that it still owns the lease before every batch. That is what
	makes stale recovery safe: an operation that was taken over after its worker
	went quiet is dropped by that worker the moment it wakes up, instead of racing
	the worker that now owns it.
	"""
	batch_size = max(cint(BATCH_SIZE), 1)
	checkpoint = cint(doc.checkpoint)
	remaining = [action for action in actions if cint(action.get("row_index")) > checkpoint] if checkpoint else list(actions)
	# The total this operation will ever write, counted from the rows that are
	# really still outstanding rather than from a list a resume may have rebuilt.
	doc.planned = cint(doc.processed) + len(remaining)
	done = 0
	total = len(remaining)
	while done < total:
		if not _still_owns(doc.name, token):
			return
		_touch(doc)
		if _cancel_requested(doc.name):
			_finish(doc, "Cancelled", "عملیات به درخواست کاربر متوقف شد.")
			return
		batch = remaining[done : done + batch_size]
		counts = {APPLIED: 0, UNCHANGED: 0}
		failures = []
		for action in batch:
			outcome, failure = _apply_row(doc, action)
			if failure is not None:
				failures.append((action, failure))
			else:
				counts[outcome] = counts.get(outcome, 0) + 1
		_commit_batch(
			doc,
			len(batch),
			counts,
			failures,
			cint(batch[-1].get("row_index")),
		)
		done += len(batch)
	_finish(doc, _outcome_status(doc), _done_summary(doc))


def _touch(doc) -> None:
	"""Publish this worker's heartbeat before it starts a batch.

	Committed on its own, before the first row of the batch, so the timestamp is
	visible to a `resume` while a slow batch is still running and no row of that
	batch is committed early with it.
	"""
	doc.heartbeat = now()
	frappe.db.set_value(OPERATION, doc.name, "heartbeat", doc.heartbeat, update_modified=False)
	frappe.db.commit()


def _apply_row(doc, action) -> tuple[str | None, Exception | None]:
	"""Apply one row inside its own savepoint.

	`frappe.database.savepoint(catch=...)` rolls the row back *and swallows* the
	exception, so the failure is caught here and handed back instead: one bad row
	must never take the healthy rows of its batch with it, and it must never be
	counted as applied either.
	"""
	outcome = None
	failure = None
	with savepoint(catch=Exception):
		try:
			outcome = _apply_action(doc, action)
		except Exception as exc:  # noqa: BLE001 - reported as a failed row
			failure = exc
			raise
	if failure is None and outcome is None:
		failure = frappe.ValidationError("نوشتن این ردیف در پایگاه داده انجام نشد.")
	return outcome, failure


def _commit_batch(doc, size: int, counts: dict, failures: list, checkpoint: int) -> None:
	"""Write the batch's counters and its checkpoint in the same transaction as its rows.

	`processed` counts the actions this operation has committed overall, so it
	stays honest across a resume; `checkpoint` is the plan position the last
	committed write belongs to, which is both readable and the resume cursor.

	The document is deliberately *not* reloaded: this worker is the only writer
	while it holds the lease, and reloading would throw away the plan, the stored
	error list and the counters that are newer than the row it would read back.
	"""
	doc.status = "Running"
	doc.applied = cint(doc.applied) + counts[APPLIED]
	doc.unchanged = cint(doc.unchanged) + counts[UNCHANGED]
	doc.failed = cint(doc.failed) + len(failures)
	doc.processed = cint(doc.processed) + size
	doc.checkpoint = max(cint(doc.checkpoint), checkpoint)
	doc.heartbeat = now()
	payload = _detail(doc.detail)
	failure_rows = [_failure_row(action, exc) for action, exc in failures]
	_append_errors(payload, failure_rows)
	doc.detail = json.dumps(payload, ensure_ascii=False)
	for row in failure_rows:
		doc.error_count = cint(doc.error_count) + 1
		if len(doc.errors) < MAX_STORED_ERRORS:
			doc.append("errors", row)
	_save(doc)
	frappe.db.commit()
	_after_commit()


def _failure_row(action, exc) -> dict:
	return {
		"app": action.get("app") or "",
		"excel_row": cint(action.get("excel_row")),
		"sheet": action.get("sheet") or "",
		"code": "row_failed",
		"source_text": action.get("source_text") or "",
		"translated_text": action.get("value") or "",
		"context": action.get("context") or "",
		"identity": action.get("identity") or "",
		"reason": f"نوشتن این ردیف ناموفق بود: {exc}",
		"action": "ردیف را در فایل اصلاح کنید و پس از رفع علت، عملیات را ادامه دهید.",
		"before": action.get("value") or "",
		"after": "",
	}


def _after_commit() -> None:
	from smartprocee_erpnext_persiant.persian_translation.service import clear_translation_caches

	clear_translation_caches()


def _cancel_requested(operation: str) -> bool:
	return bool(cint(frappe.db.get_value(OPERATION, operation, "cancel_requested")))


def _apply_action(doc, action) -> str:
	kind = action.get("type")
	if kind == TRANSLATION_UPSERT:
		source = action["source_text"]
		context = action.get("context") or ""
		_upsert_translation(source, context, action["value"], action.get("app") or "")
		return APPLIED
	if kind == TRANSLATION_DELETE:
		return APPLIED if _delete_translation(action["source_text"], action.get("context") or "") else UNCHANGED
	if kind == FONT_FAMILY_CREATE:
		snapshots.apply_font_family_create(action["family"])
		return APPLIED
	if kind == FONT_FAMILY_DELETE:
		_delete_font_family(action["name"])
		return APPLIED
	if kind == FONT_ACTIVATE:
		snapshots.apply_font_activate(action["url"], action["snapshot"])
		return APPLIED
	if kind == RTL_RESTORE:
		snapshots.apply_rtl_restore(action["state"])
		return APPLIED
	frappe.throw(f"نوع عمل ناشناخته: {kind}")


def _upsert_translation(source: str, context: str, value: str, app: str = "") -> None:
	from smartprocee_erpnext_persiant.persian_translation.service import _upsert_translation as upsert

	upsert(source, context, value, app=app)


def _delete_translation(source: str, context: str) -> int:
	"""Delete exactly the rows that hold this source and context, never a similar one."""
	rows = frappe.get_all(
		"Translation",
		filters={"language": "fa", "source_text": source},
		fields=["name", "context", "source_text"],
		limit_page_length=0,
	)
	exact = [row.name for row in rows if (row.context or "") == (context or "") and row.source_text == source]
	for name in exact:
		frappe.delete_doc("Translation", name)
	return len(exact)


def _delete_font_family(name: str) -> None:
	"""Remove one font family, and only the files nothing else needs any more.

	The row is deleted before the files. If the delete is refused, nothing on disk
	has been touched, which is the only order that cannot leave a row pointing at
	missing files. Files a stored snapshot still records are kept: deleting them
	would break a restore the operator can still run.
	"""
	doc = frappe.get_doc(snapshots.FAMILY, name)
	if doc.is_active:
		frappe.throw("خانوادهٔ فونت فعال حذف نمی‌شود.")
	uploads = [face.file_url for face in doc.faces]
	frappe.delete_doc(snapshots.FAMILY, name, flags={SKIP_RESTORE_POINT: True})
	snapshots.delete_font_uploads(uploads)


# --------------------------------------------------------------------------- #
# Finishing
# --------------------------------------------------------------------------- #


def _outcome_status(doc) -> str:
	if cint(doc.failed) and cint(doc.applied):
		return "Partial"
	if cint(doc.failed):
		return "Failed"
	return "Completed"


def _done_summary(doc) -> str:
	return (
		f"{cint(doc.applied)} اعمال شد، {cint(doc.unchanged)} بی‌تغییر، "
		f"{cint(doc.rejected)} رد‌شده، {cint(doc.failed)} ناموفق."
	)


def _finish(doc, status: str, summary: str) -> None:
	"""Close the operation and release the writer lease.

	Releasing the lease is what lets the next operation start, so it happens in the
	very same transaction as the closing status: an operation can never be finished
	and still hold the lease.
	"""
	doc.status = status
	doc.summary = summary
	doc.finished_at = now()
	doc.heartbeat = now()
	doc.lock_key = None
	doc.lease_token = ""
	_save(doc)
	frappe.db.commit()
	_after_commit()


def _save(doc) -> None:
	# `snapshot` is history once the operation has run: a snapshot pruned or
	# deleted meanwhile must not stop progress, failure or completion being saved.
	doc.flags.ignore_links = True
	doc.save()


def _finish_failed(doc, exc) -> None:
	doc.reload()
	_finish(doc, "Failed", f"عملیات با خطا متوقف شد: {str(exc)[:400]}")
