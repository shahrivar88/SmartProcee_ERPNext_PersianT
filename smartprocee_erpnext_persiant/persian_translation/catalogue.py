import csv
import os
from datetime import datetime
from pathlib import Path


def unescape_newlines(value: str) -> str:
	return (value or "").replace("\\n", "\n")


def read_catalogue(path: Path) -> list[list[str]]:
	return [row for _line, row in catalogue_records(path)]


def catalogue_records(path: Path):
	"""Yield (first line number, padded row) for every non-blank CSV record."""
	with path.open(encoding="utf-8", newline="") as handle:
		reader = csv.reader(handle)
		line = 1
		for raw in reader:
			if raw and any((cell or "").strip() for cell in raw):
				padded = list(raw[:3])
				while len(padded) < 3:
					padded.append("")
				yield line, padded
			line = reader.line_num + 1


def catalogue_key(row: list[str]) -> tuple[str, str]:
	context = row[2] if len(row) > 2 else ""
	return unescape_newlines(row[0]), unescape_newlines(context)


def catalogue_map(rows: list[list[str]]) -> dict[tuple[str, str], str]:
	mapped = {}
	for row in rows:
		mapped[catalogue_key(row)] = unescape_newlines(row[1])
	return mapped


def detect_newline(path: Path) -> str:
	sample = path.read_bytes()[:4096]
	if b"\r\n" in sample:
		return "\r\n"
	return "\n"


def merge_overrides(rows: list[list[str]], overrides: dict[tuple[str, str], str]) -> tuple[list[list[str]], dict]:
	"""Update matching catalogue rows and append new ones. Never drops a row."""
	index = {}
	for position, row in enumerate(rows):
		index.setdefault(catalogue_key(row), []).append(position)

	updated = 0
	appended = 0
	unchanged = 0
	merged = [row[:] for row in rows]
	for key, translated in overrides.items():
		source, context = key
		if not translated:
			continue
		positions = index.get(key)
		if positions:
			changed_here = False
			for position in positions:
				current = unescape_newlines(merged[position][1])
				if current == translated:
					continue
				merged[position][1] = translated
				changed_here = True
			if changed_here:
				updated += 1
			else:
				unchanged += 1
			continue
		merged.append([source, translated, context])
		index[key] = [len(merged) - 1]
		appended += 1
	return merged, {"updated": updated, "appended": appended, "unchanged": unchanged}


def write_catalogue_atomic(path: Path, rows: list[list[str]]) -> Path:
	"""Write a validated temporary CSV, back up the original, then replace it."""
	path = Path(path)
	original = path.read_bytes()
	newline = detect_newline(path)
	stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
	temp = path.with_name(f".fa.csv.tmp-{stamp}")
	backup = path.with_name(f"fa.csv.bak-{stamp}")
	expected = len(rows)
	try:
		with temp.open("w", encoding="utf-8", newline="") as handle:
			writer = csv.writer(handle, lineterminator=newline)
			writer.writerows(rows)
		reread = read_catalogue(temp)
		if len(reread) != expected:
			raise RuntimeError(f"Rewritten catalogue has {len(reread)} rows, expected {expected}.")
		if catalogue_map(reread) != catalogue_map(rows):
			raise RuntimeError("Rewritten catalogue did not round-trip.")
		backup.write_bytes(original)
		os.replace(temp, path)
		if not path.exists() or path.stat().st_size == 0:
			path.write_bytes(original)
			raise RuntimeError("Refusing to leave an empty catalogue.")
	except Exception:
		if temp.exists():
			temp.unlink()
		if path.exists() and path.read_bytes() != original:
			path.write_bytes(original)
		raise
	return backup
