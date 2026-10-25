"""The contract between the Persianizer screens and the server.

`BROWSER_ENDPOINTS` lists every server method each screen calls and the HTTP verb
it uses. The first test reads the shipped client code, so a renamed endpoint or a
new call fails here instead of in the browser. The rest prove that every listed
method passes Frappe's API gate for a System Manager only, and that the screens
cannot call the server from another Desk route.
"""

import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import frappe
from frappe.handler import is_valid_http_method
from frappe.tests import IntegrationTestCase

from smartprocee_erpnext_persiant import hooks

APP = "smartprocee_erpnext_persiant"
MANAGER = f"{APP}.persian_translation.page.persian_translation_manager.persian_translation_manager"
FONT = f"{APP}.persian_translation.system_font.service"
RTL = f"{APP}.persian_rtl.diagnostics"
TESTER = "ptm.endpoint.tester@example.com"

MANAGER_JS = "persian_translation/page/persian_translation_manager/persian_translation_manager.js"
FONT_JS = "persian_translation/page/persian_system_font_manager/persian_system_font_manager.js"
RTL_JS = "persian_rtl/doctype/persian_rtl_settings/persian_rtl_settings.js"

# `frappe.call` posts unless told otherwise; downloads open a plain GET URL.
BROWSER_ENDPOINTS = {
	MANAGER_JS: {
		f"{MANAGER}.get_rows": "POST",
		f"{MANAGER}.save_column_widths": "POST",
		f"{MANAGER}.save_translations": "POST",
		f"{MANAGER}.start_scan": "POST",
		f"{MANAGER}.scan_status": "POST",
		f"{MANAGER}.start_export": "POST",
		f"{MANAGER}.download_export": "GET",
		f"{MANAGER}.preview_import": "POST",
		f"{MANAGER}.apply_import": "POST",
		f"{MANAGER}.operation_status": "POST",
		f"{MANAGER}.operation_list": "POST",
		f"{MANAGER}.operation_cancel": "POST",
		f"{MANAGER}.operation_resume": "POST",
		f"{MANAGER}.operation_errors": "GET",
		f"{MANAGER}.snapshot_list": "POST",
		f"{MANAGER}.snapshot_capture": "POST",
		f"{MANAGER}.snapshot_preview": "POST",
		f"{MANAGER}.snapshot_restore": "POST",
		f"{MANAGER}.publish_catalogue": "POST",
	},
	FONT_JS: {
		f"{FONT}.list_font_families": "POST",
		f"{FONT}.upload_font_family": "POST",
		f"{FONT}.save_face_mapping": "POST",
		f"{FONT}.activate_family": "POST",
		f"{FONT}.reset_font": "POST",
		f"{FONT}.delete_family": "POST",
	},
	RTL_JS: {
		f"{RTL}.compat_report": "GET",
		f"{RTL}.report": "POST",
	},
}

# Arguments that reach each endpoint's permission check. None of them names a
# real record, so a missing check would surface as a different error.
DUMMY_ARGS = {
	"save_column_widths": {"column_widths": "{}"},
	"save_translations": {"rows": "[]"},
	"preview_import": {"file_url": "/private/files/ptm-missing.xlsx"},
	"apply_import": {"file_url": "/private/files/ptm-missing.xlsx"},
	"operation_status": {"name": "PTOP-missing"},
	"operation_cancel": {"name": "PTOP-missing"},
	"operation_resume": {"name": "PTOP-missing"},
	"operation_errors": {"name": "PTOP-missing"},
	"download_export": {"name": "PTOP-missing"},
	"snapshot_preview": {"name": "PSNAP-missing"},
	"snapshot_restore": {"name": "PSNAP-missing", "confirm": 1},
	"save_face_mapping": {"name": "missing", "mapping": "[]"},
	"activate_family": {"name": "missing"},
	"delete_family": {"name": "missing"},
}

# Every endpoint that writes: a record, a queued job, a file or a user setting.
# A GET is never checked for CSRF, so these must refuse it.
MUTATIONS = (
	f"{MANAGER}.save_translations",
	f"{MANAGER}.start_scan",
	f"{MANAGER}.start_export",
	f"{MANAGER}.preview_import",
	f"{MANAGER}.apply_import",
	f"{MANAGER}.operation_cancel",
	f"{MANAGER}.operation_resume",
	f"{MANAGER}.snapshot_capture",
	f"{MANAGER}.snapshot_preview",
	f"{MANAGER}.snapshot_restore",
	f"{MANAGER}.publish_catalogue",
	f"{MANAGER}.save_column_widths",
	f"{FONT}.upload_font_family",
	f"{FONT}.save_face_mapping",
	f"{FONT}.activate_family",
	f"{FONT}.reset_font",
	f"{FONT}.delete_family",
)

# Read-only endpoints a System Manager can call with no arguments.
READS = (
	f"{MANAGER}.get_rows",
	f"{MANAGER}.scan_status",
	f"{MANAGER}.operation_list",
	f"{MANAGER}.snapshot_list",
	f"{FONT}.list_font_families",
	f"{RTL}.compat_report",
	f"{RTL}.report",
)


def all_endpoints() -> dict[str, str]:
	return {path: verb for calls in BROWSER_ENDPOINTS.values() for path, verb in calls.items()}


def read_client(relative: str) -> str:
	return (Path(frappe.get_app_path(APP)) / relative).read_text(encoding="utf-8")


def client_calls(relative: str) -> set[str]:
	"""Every server method the file names, in the forms this app's client code uses."""
	source = read_client(relative)
	if relative == MANAGER_JS:
		names = set(re.findall(r'method \+ "\.(\w+)[?"]', source))
		names |= set(re.findall(r'\.queue\(\s*"(\w+)"', source))
		names |= set(re.findall(r'open_download\([^,]+, "(\w+)"', source))
		return {f"{MANAGER}.{name}" for name in names}
	if relative == FONT_JS:
		names = set(re.findall(r'this\.call\("(\w+)"', source))
		names |= set(re.findall(r"\$\{PSF_METHOD\}\.(\w+)", source))
		return {f"{FONT}.{name}" for name in names}
	return set(re.findall(r'"(smartprocee_erpnext_persiant\.[\w.]+)"', source))


def call_through_api_gate(path: str, **kwargs):
	"""What `/api/method/<path>` does after routing: the whitelist gate, then the call."""
	method = frappe.get_attr(path)
	frappe.is_whitelisted(method)
	return frappe.call(method, **kwargs)


class TestEndpointMap(IntegrationTestCase):
	def test_the_map_matches_the_client_code(self):
		for relative, calls in BROWSER_ENDPOINTS.items():
			with self.subTest(client=relative):
				self.assertEqual(client_calls(relative), set(calls))

	def test_every_endpoint_exists_and_is_whitelisted_for_its_verb(self):
		for path, verb in all_endpoints().items():
			with self.subTest(endpoint=path):
				method = frappe.get_attr(path)
				self.assertIn(method, frappe.whitelisted)
				self.assertNotIn(method, frappe.guest_methods)
				self.assertIn(verb, frappe.allowed_http_methods_for_whitelisted_func[method])


@contextmanager
def http_verb(verb: str):
	"""The request method `frappe.handler.is_valid_http_method` reads."""
	previous = getattr(frappe.local, "request", None)
	frappe.local.request = SimpleNamespace(method=verb)
	try:
		yield
	finally:
		frappe.local.request = previous


class TestMutationVerbs(IntegrationTestCase):
	def test_every_state_changing_endpoint_refuses_get(self):
		for path in MUTATIONS:
			method = frappe.get_attr(path)
			with self.subTest(endpoint=path):
				self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[method], ["POST"])
				with http_verb("GET"), self.assertRaises(frappe.PermissionError):
					is_valid_http_method(method)
				with http_verb("POST"):
					is_valid_http_method(method)

	def test_every_endpoint_the_screens_use_is_either_a_mutation_or_read_only(self):
		writes = set(MUTATIONS)
		for path, verb in all_endpoints().items():
			with self.subTest(endpoint=path):
				if path in writes:
					self.assertEqual(verb, "POST")
				else:
					self.assertIn("GET", frappe.allowed_http_methods_for_whitelisted_func[frappe.get_attr(path)])

	def test_a_system_manager_may_post_a_mutation(self):
		with http_verb("POST"):
			is_valid_http_method(frappe.get_attr(f"{MANAGER}.save_translations"))
			result = call_through_api_gate(f"{MANAGER}.save_translations", rows="[]")
		self.assertEqual(result.get("saved"), 0)


class TestEndpointAccess(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", TESTER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": TESTER,
					"first_name": "PTM Endpoint Tester",
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

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_guest_is_refused_at_the_api_gate(self):
		frappe.set_user("Guest")
		for path in all_endpoints():
			with self.subTest(endpoint=path), self.assertRaises(frappe.PermissionError):
				frappe.is_whitelisted(frappe.get_attr(path))

	def test_a_user_without_system_manager_is_refused_by_every_endpoint(self):
		frappe.set_user(TESTER)
		self.assertNotIn("System Manager", frappe.get_roles())
		for path in all_endpoints():
			args = DUMMY_ARGS.get(path.rsplit(".", 1)[1], {})
			with self.subTest(endpoint=path), self.assertRaises(frappe.PermissionError):
				call_through_api_gate(path, **args)

	def test_a_system_manager_reads_every_screen_through_the_api_gate(self):
		self.assertIn("System Manager", frappe.get_roles())
		for path in READS:
			with self.subTest(endpoint=path):
				self.assertIsNotNone(call_through_api_gate(path))
		page = call_through_api_gate(f"{MANAGER}.get_rows", start=0, page_length=5)
		self.assertLessEqual(len(page["rows"]), 5)
		self.assertIn("total", page)


class TestRouteIsolation(IntegrationTestCase):
	"""Persianizer client code runs only on its own pages."""

	def test_the_app_ships_no_desk_wide_script(self):
		self.assertFalse(getattr(hooks, "app_include_js", None))
		self.assertFalse(getattr(hooks, "page_js", None))
		self.assertFalse(getattr(hooks, "web_include_js", None))
		account_only = {"Account": "public/js/account_display.js"}
		self.assertEqual(getattr(hooks, "doctype_js", None), account_only)
		self.assertEqual(getattr(hooks, "doctype_list_js", None), account_only)
		self.assertEqual(getattr(hooks, "doctype_tree_js", None), account_only)

	def test_every_deferred_manager_call_checks_the_active_route(self):
		"""A poll or late callback must not call the server from another route.

		Frappe keeps a visited page alive, so each entry point that a timer or a
		callback can reach starts with the route check.
		"""
		source = read_client(MANAGER_JS)
		self.assertIn('frappe.pages[PAGE_NAME].on_page_show', source)
		self.assertIn("return frappe.get_route()[0] === PAGE_NAME;", source)
		entry_points = [
			r"\n\tload\(\) \{\n(.*?)\n\t\}\n",
			r"\n\tpoll_scan\(\) \{\n(.*?)\n\t\}\n",
			r"const tick = \(\) => \{\n(.*?)\n\t\};\n",
		]
		bodies = [body for pattern in entry_points for body in re.findall(pattern, source, re.S)]
		# Three `load()` methods (rows, operation queue, snapshots), the scan poll
		# and the operation watcher.
		self.assertEqual(len(bodies), 5)
		for body in bodies:
			with self.subTest(body=body.strip()[:60]):
				self.assertIn("on_manager_page()", body.split("frappe.call", 1)[0])

	def test_the_first_visit_asks_for_rows_once(self):
		"""Building the filter controls must not start extra `get_rows` calls."""
		source = read_client(MANAGER_JS)
		constructor = re.search(r"\n\tconstructor\(page\) \{\n(.*?)\n\t\}\n", source, re.S).group(1)
		self.assertIn("this.ready = false;", constructor)
		self.assertNotIn("this.load()", constructor)
		self.assertEqual(source.count("this.ready = true;"), 1)
		initial = re.search(r"\n\tinitial_load\(\) \{\n(.*?)\n\t\}\n", source, re.S).group(1)
		self.assertEqual([line.strip() for line in initial.splitlines()], ["this.ready = true;", "this.load();"])
		for field in ("page_length_field", "status_field", "app_field", "kind_field", "search_field"):
			with self.subTest(field=field):
				self.assertNotIn(f"this.{field}.set_value(", source)

	def test_a_change_that_keeps_the_filters_does_not_reload(self):
		source = read_client(MANAGER_JS)
		on_change = re.search(r"\n\ton_filter_change\(\) \{\n(.*?)\n\t\}\n", source, re.S).group(1)
		self.assertLess(on_change.index("=== this._requested"), on_change.index("this.load()"))
		load = re.search(r"\n\tload\(\) \{\n(.*?)\n\t\}\n", source, re.S).group(1)
		self.assertIn("this._requested = JSON.stringify(args);", load)

	def test_import_progress_explains_the_wait(self):
		source = read_client(MANAGER_JS)
		self.assertIn("در حال پردازش فایل؛ لطفاً منتظر بمانید و این پنجره را نبندید.", source)
		self.assertIn("is_running(operation.status)", source)

	def test_no_manager_class_defines_a_method_twice(self):
		"""A JS class keeps the last definition, so a reused name silently replaces the first."""
		source = read_client(MANAGER_JS)
		for chunk in re.split(r"\nclass ", source)[1:]:
			name = chunk.split(" ", 1)[0]
			body = chunk.split("\n}\n", 1)[0]
			methods = re.findall(r"\n\t(\w+)\([^)]*\) \{\n", body)
			with self.subTest(cls=name):
				self.assertEqual(sorted(methods), sorted(set(methods)))
