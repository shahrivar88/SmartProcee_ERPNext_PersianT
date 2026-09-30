"""Source ownership of catalogue rows.

The public fa.csv may only carry rows whose source text is owned by an app in
CATALOGUE_OWNERS. Ownership is proven from the owner's own package only:
its upstream POT, its quoted source literals, then its upstream PO files.
Site data and other installed apps are never evidence.
"""

import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path

CATALOGUE_OWNERS = ("frappe", "erpnext")
SOURCE_SUFFIXES = {".py", ".js", ".ts", ".vue", ".json", ".html", ".csv"}
SKIPPED_DIRS = {"node_modules", "dist", "__pycache__", ".git", "locale", "translations"}
LITERAL_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`')


@dataclass(frozen=True)
class Evidence:
	owner: str
	kind: str
	path: str


class OwnershipIndex:
	"""Answers which catalogue owner, if any, ships a (source, context) identity."""

	_shared = None

	def __init__(self, roots: dict[str, Path]):
		self.roots = roots
		self._cache = {}

	@classmethod
	def for_catalogue_owners(cls) -> "OwnershipIndex":
		if cls._shared is None:
			cls._shared = cls(owner_roots())
		return cls._shared

	def owner_of(self, source: str, context: str = "") -> Evidence | None:
		context = context or ""
		return (
			self._from_messages("pot", source, context)
			or self._from_literals(source, context)
			or self._from_messages("po", source, context)
		)

	def _from_messages(self, kind, source, context):
		for owner, entries in self._load(kind).items():
			found = entries.get((source, context or None))
			if found is None and not context:
				found = entries.get((source, ANY_CONTEXT))
			if found is not None:
				return Evidence(owner, kind, found)
		return None

	def _from_literals(self, source, context):
		for owner, literals in self._load("source").items():
			paths = literals.get(source)
			if paths and context:
				paths = paths & literals.get(context, set())
			if paths:
				return Evidence(owner, "source", sorted(paths)[0])
		return None

	def _load(self, kind):
		if kind not in self._cache:
			reader = {"pot": _read_pot, "po": _read_po_files, "source": _read_literals}[kind]
			self._cache[kind] = {owner: reader(root) for owner, root in self.roots.items()}
		return self._cache[kind]


ANY_CONTEXT = "\x00any"


def owner_roots() -> dict[str, Path]:
	roots = {}
	for owner in CATALOGUE_OWNERS:
		spec = importlib.util.find_spec(owner)
		if spec and spec.origin:
			roots[owner] = Path(spec.origin).parent
	return roots


def _read_pot(root: Path) -> dict:
	path = root / "locale" / "main.pot"
	return _read_messages(path, root.parent) if path.exists() else {}


def _read_po_files(root: Path) -> dict:
	entries = {}
	for path in sorted((root / "locale").glob("*.po")):
		for key, found in _read_messages(path, root.parent).items():
			entries.setdefault(key, found)
	return entries


def _read_messages(path: Path, app_root: Path) -> dict:
	"""Map active (msgid, msgctxt) pairs of a PO/POT file to their source references."""
	entries = {}
	label = str(path.relative_to(app_root))
	refs, context, msgid, field = [], None, None, None
	with path.open(encoding="utf-8") as handle:
		for line in handle:
			line = line.strip()
			if not line:
				refs, context, msgid, field = [], None, None, None
			elif line.startswith("#:"):
				refs.extend(line[2:].split())
			elif line.startswith("msgctxt "):
				context, field = _po_string(line[8:]), "msgctxt"
			elif line.startswith("msgid "):
				msgid, field = _po_string(line[6:]), "msgid"
			elif line.startswith('"') and field == "msgid":
				msgid += _po_string(line)
			elif line.startswith('"') and field == "msgctxt":
				context += _po_string(line)
			elif line.startswith(("msgid_plural", "msgstr")) and field:
				if msgid:
					found = f"{label} ({' '.join(refs[:2])})"
					entries.setdefault((msgid, context or None), found)
					entries.setdefault((msgid, ANY_CONTEXT), found)
				field = None
	return entries


def _read_literals(root: Path) -> dict[str, set[str]]:
	"""Map every quoted string literal in the owner's source files to its paths."""
	literals = {}
	app_root = root.parent
	for path in root.rglob("*"):
		if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
			continue
		if SKIPPED_DIRS & set(path.relative_to(root).parts):
			continue
		try:
			text = path.read_text(encoding="utf-8")
		except (OSError, UnicodeDecodeError):
			continue
		relative = str(path.relative_to(app_root))
		for match in LITERAL_RE.finditer(text):
			value = _decode_literal(match.group(0))
			if value:
				literals.setdefault(value, set()).add(relative)
	return literals


def _po_string(token: str) -> str:
	token = token.strip()
	if len(token) < 2 or token[0] != '"' or token[-1] != '"':
		return ""
	try:
		return json.loads(token)
	except ValueError:
		return token[1:-1]


def _decode_literal(token: str) -> str:
	if token.startswith('"'):
		try:
			return json.loads(token)
		except ValueError:
			pass
	inner = token[1:-1]
	return (
		inner.replace("\\'", "'").replace('\\"', '"').replace("\\`", "`").replace("\\n", "\n").replace("\\\\", "\\")
	)
