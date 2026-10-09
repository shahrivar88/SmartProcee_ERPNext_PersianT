"""Font Manager: validation, limits, permissions, activation, revert and cleanup."""

import io
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.config import clear_site_config_cache
from frappe.installer import update_site_config
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant.persian_translation import snapshots
from smartprocee_erpnext_persiant.persian_translation.doctype.persian_font_family.persian_font_family import (
	SKIP_RESTORE_POINT,
)
from smartprocee_erpnext_persiant.persian_translation.system_font import css as font_css
from smartprocee_erpnext_persiant.persian_translation.system_font import storage
from smartprocee_erpnext_persiant.persian_translation.system_font.inspect import (
	FontRejected,
	detect_format,
	inspect_font_bytes,
)
from smartprocee_erpnext_persiant.persian_translation.system_font.service import (
	MAX_BYTES,
	MAX_FILES,
	activate_family,
	delete_family,
	list_font_families,
	refresh_active_css,
	reset_font,
	save_face_mapping,
	upload_font_family,
)
from smartprocee_erpnext_persiant.persian_translation.tests.helpers import (
	SAMPLE_FAMILY,
	make_font,
	rule_selectors,
	sample_faces,
)

FAMILY = "Persian Font Family"
TESTER = "ptm-font-tester@example.com"
ACTIVE_CSS_PATH = "public", "files", storage.ACTIVE_CSS
ADAPTER_CSS_PATH = "public", "files", storage.ADAPTER_CSS


class _FakeUpload:
	def __init__(self, filename, data):
		self.filename = filename
		self.stream = io.BytesIO(data)


class _FakeRequest:
	def __init__(self, uploads):
		self._uploads = uploads

	@property
	def files(self):
		return self

	def getlist(self, _key):
		return self._uploads


def _fake_request(uploads):
	return _FakeRequest(uploads)


def _refresh_conf():
	clear_site_config_cache()
	frappe.local.conf = frappe.get_site_config()


def _upload_sample(testcase) -> dict:
	"""Upload a generated font as a new family and remove its file after the test."""
	frappe.local.request = _fake_request([_FakeUpload("Sample-Regular.woff2", make_font())])
	try:
		review = upload_font_family()
	finally:
		del frappe.local.request
	path = Path(frappe.get_site_path("public", review["faces"][0]["file_url"].lstrip("/")))
	testcase.addCleanup(lambda: path.exists() and path.unlink())
	testcase.addCleanup(_drop_family, review["name"])
	return review


def _drop_family(name: str) -> None:
	if not frappe.db.exists(FAMILY, name):
		return
	frappe.db.set_value(FAMILY, name, "is_active", 0)
	frappe.delete_doc(FAMILY, name, force=1, flags={SKIP_RESTORE_POINT: True})


def _sample_name(testcase) -> str:
	return _upload_sample(testcase)["name"]


class CssConfigMixin:
	"""Snapshot and restore `app_include_css`, which lives in site_config.json."""

	def snapshot_css_config(self):
		self._before_css = list(frappe.conf.get("app_include_css") or [])
		self.addCleanup(self.restore_css_config)

	def restore_css_config(self):
		had_marker = any(storage.MARKER in str(item) for item in getattr(self, "_before_css", []))
		if not had_marker:
			for parts in (ACTIVE_CSS_PATH, ADAPTER_CSS_PATH):
				active_css = Path(frappe.get_site_path(*parts))
				if active_css.exists():
					active_css.unlink()
		update_site_config("app_include_css", getattr(self, "_before_css", []))
		frappe.local._persian_adapter_font_url = None
		_refresh_conf()


class TestFontInspection(IntegrationTestCase):
	def test_only_web_fonts_are_accepted(self):
		font = inspect_font_bytes("Sample-Thin.woff2", make_font(weight=100))
		self.assertEqual(font["font_format"], "WOFF2")
		self.assertEqual(font["family_name"], SAMPLE_FAMILY)
		self.assertEqual(font["css_weight"], 100)
		self.assertEqual(inspect_font_bytes("Sample.woff", make_font(flavor="woff"))["font_format"], "WOFF")

	def test_ttf_and_otf_are_rejected(self):
		for name, head in (("font.ttf", b"\x00\x01\x00\x00"), ("font.otf", b"OTTO")):
			with self.assertRaises(FontRejected, msg=name):
				detect_format(name, head + b"\x00" * 64)

	def test_archives_and_garbage_are_rejected(self):
		with self.assertRaises(FontRejected):
			detect_format("font.zip", b"PK\x03\x04" + b"\x00" * 64)
		with self.assertRaises(FontRejected):
			detect_format("font.woff2", b"nope")
		with self.assertRaises(FontRejected):
			detect_format("font.bin", b"\x00" * 64)

	def test_weights_are_read_from_font_metadata(self):
		weights = [100, 300, 400, 600, 700, 800, 900]
		found = [inspect_font_bytes("Sample.woff2", make_font(weight=weight))["css_weight"] for weight in weights]
		self.assertEqual(found, weights)

	def test_css_helpers_reject_unsafe_values(self):
		self.assertEqual(font_css.sanitize_css_family("  Bad;Family{}  "), "BadFamily")
		with self.assertRaises(ValueError):
			font_css.sanitize_css_family("   ")
		for url in (
			"https://evil.example/f.woff2",
			"/files/../secret.woff2",
			"/assets/other/f.woff2",
			"/assets/smartprocee_erpnext_persiant/fonts/f.woff2",
		):
			with self.assertRaises(ValueError, msg=url):
				font_css._safe_url(url)

	def test_generated_css_is_language_scoped(self):
		css = font_css.render_family_css("Demo", sample_faces())
		self.assertIn('html[lang="fa"] {', css)
		for selector in rule_selectors(css):
			self.assertTrue(selector.startswith('html[lang="fa"]'), selector)


class TestFontUploadLimits(CssConfigMixin, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self._original_request = getattr(frappe.local, "request", None)
		self.addCleanup(self._restore_request)

	def _restore_request(self):
		if self._original_request is None:
			if hasattr(frappe.local, "request"):
				del frappe.local.request
		else:
			frappe.local.request = self._original_request

	def test_too_many_files_are_rejected(self):
		uploads = [_FakeUpload(f"f{index}.woff2", b"wOF2") for index in range(MAX_FILES + 1)]
		frappe.local.request = _fake_request(uploads)
		with self.assertRaises(frappe.ValidationError):
			upload_font_family()

	def test_oversized_file_is_rejected(self):
		uploads = [_FakeUpload("big.woff2", b"wOF2" + b"\x00" * MAX_BYTES)]
		frappe.local.request = _fake_request(uploads)
		with self.assertRaises(frappe.ValidationError):
			upload_font_family()

	def test_missing_file_is_rejected(self):
		frappe.local.request = _fake_request([])
		with self.assertRaises(frappe.ValidationError):
			upload_font_family()

	def test_invalid_font_is_rejected_with_a_validation_error(self):
		uploads = [_FakeUpload("font.ttf", b"\x00\x01\x00\x00" + b"\x00" * 64)]
		frappe.local.request = _fake_request(uploads)
		with self.assertRaises(frappe.ValidationError):
			upload_font_family()


class TestFontPermissions(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", TESTER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": TESTER,
					"first_name": "PTM Font Tester",
					"send_welcome_email": 0,
					"user_type": "System User",
				}
			).insert()
		cls.addClassCleanup(cls._drop_tester)

	@classmethod
	def _drop_tester(cls):
		frappe.set_user("Administrator")
		if frappe.db.exists("User", TESTER):
			frappe.delete_doc("User", TESTER, force=1)

	def test_doctype_grants_full_access_to_system_manager_only(self):
		perms = frappe.get_all(
			"DocPerm",
			filters={"parent": FAMILY},
			fields=["role", "read", "write", "create", "delete"],
		)
		self.assertEqual([row.role for row in perms], ["System Manager"])
		self.assertTrue(all(row.read and row.write and row.create and row.delete for row in perms))

	def test_non_system_manager_cannot_touch_font_configuration(self):
		name = _sample_name(self)
		frappe.set_user(TESTER)
		try:
			self.assertEqual(frappe.get_roles(), ["All", "Guest"])
			for call in (
				list_font_families,
				lambda: activate_family(name),
				lambda: save_face_mapping(name, "[]"),
				lambda: delete_family(name),
				lambda: frappe.delete_doc(FAMILY, name),
				reset_font,
			):
				with self.assertRaises(frappe.PermissionError):
					call()
		finally:
			frappe.set_user("Administrator")

	def test_guest_cannot_list_font_families(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				list_font_families()
		finally:
			frappe.set_user("Administrator")


class TestFontActivation(CssConfigMixin, IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.snapshot_css_config()

	def test_activate_then_revert(self):
		name = _sample_name(self)
		result = activate_family(name, confirm_warnings=1)
		self.assertEqual(result["activated"], name)
		_refresh_conf()

		self.assertTrue(list_font_families()["custom_active"])
		self.assertEqual(frappe.db.get_value(FAMILY, name, "is_active"), 1)

		active_css = Path(frappe.get_site_path(*ACTIVE_CSS_PATH))
		self.assertTrue(active_css.exists())
		self.assertIn('html[lang="fa"]', active_css.read_text(encoding="utf-8"))

		reset_font()
		_refresh_conf()
		self.assertFalse(list_font_families()["custom_active"])
		self.assertFalse(active_css.exists())
		self.assertFalse(frappe.db.get_value(FAMILY, name, "is_active"))

	def test_revert_leaves_a_list_in_site_config(self):
		"""A sentinel string here would break `www/desk.py` (list + str)."""
		activate_family(_sample_name(self), confirm_warnings=1)
		reset_font()
		_refresh_conf()
		value = frappe.conf.get("app_include_css")
		self.assertIsInstance(value, list)
		self.assertEqual([item for item in value if storage.MARKER in str(item)], [])

	def test_activation_writes_a_standalone_app_stylesheet_too(self):
		"""A standalone SPA never receives `app_include_css`, so it needs its own file.

		That file hangs off `html[dir="rtl"]`, because the SPA keeps its own
		`<html lang="en">` and only the RTL adapter sets the direction.
		"""
		activate_family(_sample_name(self), confirm_warnings=1)
		frappe.local._persian_adapter_font_url = None
		adapter_css = Path(frappe.get_site_path(*ADAPTER_CSS_PATH))
		self.assertTrue(adapter_css.exists())
		text = adapter_css.read_text(encoding="utf-8")
		self.assertIn('html[dir="rtl"] {', text)
		self.assertNotIn('html[lang="fa"]', text)
		self.assertNotIn("!important", text)
		url = storage.adapter_font_url()
		self.assertTrue(url.startswith(f"/files/{storage.ADAPTER_CSS}?v="))

		reset_font()
		frappe.local._persian_adapter_font_url = None
		self.assertFalse(adapter_css.exists())
		self.assertEqual(storage.adapter_font_url(), "", "with no custom family the app keeps its own font")

	def test_migrate_rebuilds_a_stale_stylesheet_and_leaves_a_current_one_alone(self):
		"""A font activated under older rules must pick up the new ones on migrate."""
		activate_family(_sample_name(self), confirm_warnings=1)
		adapter_css = Path(frappe.get_site_path(*ADAPTER_CSS_PATH))
		current = adapter_css.read_text(encoding="utf-8")
		adapter_css.write_text("html[dir=\"rtl\"] body { font-family: x !important; }", encoding="utf-8")

		refresh_active_css()
		self.assertEqual(adapter_css.read_text(encoding="utf-8"), current)

		_refresh_conf()
		before = list(frappe.conf.get("app_include_css") or [])
		refresh_active_css()
		_refresh_conf()
		self.assertEqual(list(frappe.conf.get("app_include_css") or []), before)

	def test_remove_managed_files_cleans_uploads(self):
		# Uninstall removes every upload, so it runs against a scratch site folder:
		# on the real one it would also delete files other tests and families own.
		root = Path(tempfile.mkdtemp())
		self.addCleanup(shutil.rmtree, root, True)
		folder = root / "public" / "files"
		folder.mkdir(parents=True)
		fake = folder / f"{storage.UPLOAD_PREFIX}ptm-test.woff2"
		fake.write_bytes(b"wOF2")
		other = folder / "keep-me.woff2"
		other.write_bytes(b"wOF2")
		with (
			patch.object(storage.frappe, "get_site_path", lambda *parts: str(root.joinpath(*parts))),
			patch.object(storage, "update_site_config"),
		):
			storage.remove_managed_files()
		self.assertFalse(fake.exists())
		self.assertTrue(other.exists())


class TestFontFamilyLifecycle(CssConfigMixin, IntegrationTestCase):
	def _uploaded_family(self):
		frappe.local.request = _fake_request([_FakeUpload("Sample-Regular.woff2", make_font())])
		try:
			return upload_font_family()
		finally:
			del frappe.local.request

	def test_upload_creates_an_inactive_family_with_a_stored_file(self):
		review = self._uploaded_family()
		self.assertEqual(review["source"], "Uploaded")
		self.assertEqual(review["is_active"], 0)
		self.assertEqual(review["errors"], [])
		url = review["faces"][0]["file_url"]
		self.assertTrue(url.startswith(f"/files/{storage.UPLOAD_PREFIX}"))
		path = Path(frappe.get_site_path("public", url.lstrip("/")))
		self.assertTrue(path.exists())
		self.addCleanup(lambda: path.exists() and path.unlink())

		delete_family(review["name"])
		self.assertFalse(frappe.db.exists(FAMILY, review["name"]))
		# The delete records a restore point that points at this file, so the
		# file must survive: restoring the deleted family has to find its font.
		self.assertIn(url, snapshots.fonts_referenced_by_snapshots())
		self.assertTrue(path.exists(), "a file a restore point still records must survive the delete")

	def test_an_upload_that_is_rolled_back_leaves_no_file(self):
		review = self._uploaded_family()
		path = Path(frappe.get_site_path("public", review["faces"][0]["file_url"].lstrip("/")))
		self.addCleanup(lambda: path.exists() and path.unlink())
		self.assertTrue(path.exists())

		frappe.db.rollback()

		self.assertFalse(frappe.db.exists(FAMILY, review["name"]))
		self.assertFalse(path.exists(), "a family that was never committed keeps no file")

	def test_generated_css_has_one_block_per_weight(self):
		review = self._uploaded_family()
		try:
			css = font_css.render_family_css(review["family_name"], review["faces"])
			self.assertEqual(css.count("@font-face"), 1)
			self.assertIn("font-weight: 400;", css)
		finally:
			delete_family(review["name"])

	def test_an_active_family_refuses_a_direct_delete(self):
		review = self._uploaded_family()
		path = Path(frappe.get_site_path("public", review["faces"][0]["file_url"].lstrip("/")))
		self.addCleanup(lambda: path.exists() and path.unlink())
		frappe.db.set_value(FAMILY, review["name"], "is_active", 1)

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(FAMILY, review["name"])

		self.assertTrue(frappe.db.exists(FAMILY, review["name"]))
		self.assertTrue(path.exists())
		frappe.db.set_value(FAMILY, review["name"], "is_active", 0)
		delete_family(review["name"])

	def test_a_direct_delete_records_a_restore_point_and_releases_files_safely(self):
		review = self._uploaded_family()
		url = review["faces"][0]["file_url"]
		path = Path(frappe.get_site_path("public", url.lstrip("/")))
		self.addCleanup(lambda: path.exists() and path.unlink())
		before = set(frappe.get_all(snapshots.SNAPSHOT, {"kind": snapshots.PRE_FONT}, pluck="name"))

		frappe.delete_doc(FAMILY, review["name"])

		after = set(frappe.get_all(snapshots.SNAPSHOT, {"kind": snapshots.PRE_FONT}, pluck="name"))
		self.assertEqual(len(after - before), 1, "a Desk delete records the same restore point")
		self.assertIn(url, snapshots.fonts_referenced_by_snapshots())
		# The file goes to the after-commit release, which keeps anything still recorded.
		self.assertIn(url, frappe.local._persian_released_fonts)
		self.assertTrue(path.exists(), "nothing is removed before the commit")


class TestBundledFamilyRemoval(CssConfigMixin, IntegrationTestCase):
	"""Releases before 1.2 registered a family from font files shipped with the app."""

	def setUp(self):
		super().setUp()
		self.snapshot_css_config()

	def _legacy_family(self) -> str:
		family = frappe.new_doc(FAMILY)
		family.family_name = "PTM Legacy Bundled"
		family.css_family = "Persianizer PTM Legacy Bundled"
		family.source = "Uploaded"
		family.append(
			"faces",
			{
				"original_filename": "Legacy-Regular.woff2",
				"file_url": "/assets/smartprocee_erpnext_persiant/fonts/Legacy-Regular.woff2",
				"font_format": "WOFF2",
				"css_weight": "400",
				"font_style": "normal",
				"font_stretch": "normal",
				"enabled": 1,
			},
		)
		family.insert(ignore_permissions=True)
		self.addCleanup(_drop_family, family.name)
		# "Bundled" is no longer a valid option, so an old row can only be simulated in the database.
		frappe.db.set_value(FAMILY, family.name, {"source": "Bundled", "is_active": 1})
		return family.name

	def test_the_patch_removes_the_family_and_falls_back_to_the_default_font(self):
		from smartprocee_erpnext_persiant.patches.v1_2 import remove_bundled_font_family

		uploaded = _sample_name(self)
		legacy = self._legacy_family()
		storage.write_active_css("/* legacy font */")
		_refresh_conf()

		remove_bundled_font_family.execute()
		_refresh_conf()

		self.assertFalse(frappe.db.exists(FAMILY, legacy))
		self.assertTrue(frappe.db.exists(FAMILY, uploaded), "an uploaded family is left alone")
		self.assertFalse(Path(frappe.get_site_path(*ACTIVE_CSS_PATH)).exists())
		self.assertFalse(list_font_families()["custom_active"])
		self.assertEqual(storage.adapter_font_url(), "")

		remove_bundled_font_family.execute()
		self.assertTrue(frappe.db.exists(FAMILY, uploaded), "the patch can run again safely")
