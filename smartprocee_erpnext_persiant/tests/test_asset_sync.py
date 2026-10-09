"""The one destructive thing this app does to the filesystem.

`sync_public_assets` replaces `<sites>/assets/smartprocee_erpnext_persiant` on
every migrate. These tests pin the boundary of that replacement:

* only this app's folder is ever replaced -- the sibling assets of every other
  app in the same directory are never touched;
* a symlink standing in the target's place is unlinked, never followed, so the
  directory it points at keeps its files;
* a missing source, a source outside this app, or a failed copy leaves the
  assets that are working right now exactly as they were;
* no site name and no bench path is hard-coded: the paths come from
  `frappe.get_site_path()` and `frappe.get_app_path()`.

Every test runs against a throwaway directory tree, so no real asset is at risk.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from smartprocee_erpnext_persiant import install

APP = install.APP_NAME
COPY = "css/app.css"


class AssetSyncCase(UnitTestCase):
	def setUp(self):
		super().setUp()
		self.tmp = Path(tempfile.mkdtemp(prefix="ptm-assets-"))
		self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

		self.bench = self.tmp / "frappe-bench"
		self.sites = self.bench / "sites"
		self.assets = self.sites / "assets"
		self.site = self.sites / "a_test_site"
		self.app_root = self.bench / "apps" / APP
		self.source = self.app_root / "public"
		self.assets.mkdir(parents=True)
		self.site.mkdir()
		(self.source / "css").mkdir(parents=True)
		(self.source / COPY).write_text("body {}", encoding="utf-8")
		self.target = self.assets / APP
		self.staging = self.assets / f".{APP}.staging"

		self.logged = []
		for patcher in (
			patch.object(frappe, "get_site_path", self._site_path),
			patch.object(frappe, "get_app_path", self._app_path),
			patch.object(frappe, "log_error", self._log_error),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def _site_path(self, *parts):
		return str(self.site.joinpath(*parts))

	def _app_path(self, app, *parts):
		return str(self.app_root.joinpath(*parts))

	def _log_error(self, **kwargs):
		self.logged.append(kwargs)

	def assert_refused(self):
		self.assertTrue(self.logged, "an unsafe sync must be reported, not silently skipped")


class TestAssetSyncBoundary(AssetSyncCase):
	def test_the_app_folder_becomes_a_real_copy_of_this_app(self):
		self.target.mkdir()
		(self.target / "stale.css").write_text("from an older release", encoding="utf-8")

		install.sync_public_assets()

		self.assertTrue((self.target / COPY).is_file())
		self.assertFalse(
			(self.target / "stale.css").exists(),
			"the folder is replaced, not merged, so a removed file cannot survive",
		)
		self.assertFalse(self.target.is_symlink())
		self.assertFalse(self.staging.exists())

	def test_the_assets_of_other_apps_are_never_touched(self):
		sibling = self.assets / "erpnext"
		sibling.mkdir()
		(sibling / "app.js").write_text("belongs to erpnext", encoding="utf-8")
		loose = self.assets / "assets.json"
		loose.write_text("{}", encoding="utf-8")

		install.sync_public_assets()

		self.assertEqual((sibling / "app.js").read_text(encoding="utf-8"), "belongs to erpnext")
		self.assertEqual(loose.read_text(encoding="utf-8"), "{}")

	def test_a_symlink_in_the_target_place_is_unlinked_never_followed(self):
		image_assets = self.tmp / "image-assets" / APP
		image_assets.mkdir(parents=True)
		(image_assets / "keep.css").write_text("baked into the image", encoding="utf-8")
		self.target.symlink_to(image_assets, target_is_directory=True)

		install.sync_public_assets()

		self.assertTrue(
			(image_assets / "keep.css").is_file(),
			"the directory the symlink pointed at must survive the replacement",
		)
		self.assertFalse(self.target.is_symlink())
		self.assertTrue((self.target / COPY).is_file())

	def test_a_staging_symlink_left_behind_is_replaced_not_followed(self):
		left_behind = self.tmp / "left-behind"
		left_behind.mkdir()
		(left_behind / "keep.css").write_text("still needed", encoding="utf-8")
		self.staging.symlink_to(left_behind, target_is_directory=True)

		install.sync_public_assets()

		self.assertTrue((left_behind / "keep.css").is_file())
		self.assertTrue((self.target / COPY).is_file())

	def test_a_missing_source_leaves_the_working_assets_in_place(self):
		self.target.mkdir()
		(self.target / "working.css").write_text("in use right now", encoding="utf-8")
		shutil.rmtree(self.source)

		install.sync_public_assets()

		self.assertEqual((self.target / "working.css").read_text(encoding="utf-8"), "in use right now")
		self.assert_refused()

	def test_a_source_outside_this_app_is_refused(self):
		self.target.mkdir()
		(self.target / "working.css").write_text("in use right now", encoding="utf-8")
		other_app_public = self.tmp / "other-app" / "public"
		other_app_public.mkdir(parents=True)
		(other_app_public / "other.css").write_text("not ours", encoding="utf-8")

		with patch.object(
			frappe, "get_app_path", lambda app, *parts: str(other_app_public) if parts else str(self.app_root)
		):
			install.sync_public_assets()

		self.assertEqual((self.target / "working.css").read_text(encoding="utf-8"), "in use right now")
		self.assert_refused()

	def test_a_site_without_an_assets_directory_is_left_alone(self):
		shutil.rmtree(self.assets)

		install.sync_public_assets()

		self.assertFalse(self.assets.exists(), "the sync must not create a directory tree of its own")
		self.assert_refused()

	def test_a_failed_copy_leaves_the_working_assets_in_place(self):
		self.target.mkdir()
		(self.target / "working.css").write_text("in use right now", encoding="utf-8")

		with patch.object(install.shutil, "copytree", side_effect=OSError("disk full")):
			with self.assertRaises(OSError):
				install.sync_public_assets()

		self.assertEqual((self.target / "working.css").read_text(encoding="utf-8"), "in use right now")
		self.assertFalse(self.staging.exists(), "a failed copy may not leave staging behind")


class TestAssetPathGuards(AssetSyncCase):
	def test_the_target_is_this_app_inside_the_resolved_assets_directory(self):
		self.assertEqual(install._asset_path(), self.target)
		self.assertEqual(install._asset_root(), self.assets.resolve())

	def test_the_target_follows_a_symlinked_assets_directory(self):
		shared = self.tmp / "shared-assets"
		shared.mkdir()
		shutil.rmtree(self.assets)
		self.assets.symlink_to(shared, target_is_directory=True)

		self.assertEqual(install._asset_path(), shared.resolve() / APP)
		install.sync_public_assets()
		self.assertTrue((shared / APP / COPY).is_file())
		self.assertTrue((shared / APP).is_dir())

	def test_no_path_is_hard_coded(self):
		source = Path(install.__file__).read_text(encoding="utf-8")
		for hard_coded in ("/home/frappe", "frappe-bench", "ptm_clean_test2", "SmartProcessERP"):
			self.assertNotIn(hard_coded, source)
