"""The contract every RTL adapter implements.

An adapter is *declarative data*, not behaviour. It states which app it targets,
which routes it may touch, which versions were actually checked, which DOM
signatures prove the target still looks the way the adapter was written for, and
which direction-sensitive regions must be handled explicitly.

Everything technical lives here, in version control. The database only stores the
decisions an administrator is allowed to make: switch the adapter on, accept a
version range that was not tested, and -- where ``supports_system_font`` says the
adapter can take it -- use the active Persian system font inside the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Where a direction-sensitive region sits inside the target app.
LTR_ISLAND = "LTR Island"
AUTO_DIRECTION = "Auto Direction"
EXCLUSION_MODES = (LTR_ISLAND, AUTO_DIRECTION)

# A standalone SPA renders its own document, so it needs a stylesheet link.
# A Desk-hosted target already receives Frappe's own RTL assets.
STANDALONE = "Standalone SPA"
DESK_HOSTED = "Desk hosted"


@dataclass(frozen=True)
class Exclusion:
	"""One region the adapter handles explicitly instead of mirroring blindly."""

	label: str
	selector: str
	mode: str = LTR_ISLAND
	review: str = ""

	def __post_init__(self):
		if not self.label or not self.selector:
			raise ValueError("an exclusion needs both a label and a selector")
		if self.mode not in EXCLUSION_MODES:
			raise ValueError(f"unknown exclusion mode: {self.mode}")


@dataclass(frozen=True)
class Adapter:
	"""Static, version-controlled description of one RTL compatibility adapter."""

	adapter_id: str
	title: str
	target_app: str
	entry_template: str
	hosting: str
	routes: tuple[str, ...]
	tested_versions: tuple[str, ...]
	compatible_min: str
	compatible_max: str
	stylesheet: str = ""
	script: str = ""
	visual_ready: bool = True
	entry_anchor: str = ""
	signature_physical: tuple[str, ...] = ()
	signature_logical: tuple[str, ...] = ()
	exclusions: tuple[Exclusion, ...] = field(default_factory=tuple)
	risk: str = "medium"
	notes: str = ""
	# Whether the app's typography was checked against the generated adapter font
	# stylesheet (see `system_font.css.render_adapter_css`).
	supports_system_font: bool = False

	def __post_init__(self):
		for name in ("adapter_id", "title", "target_app", "entry_template", "hosting"):
			if not getattr(self, name):
				raise ValueError(f"{self.adapter_id or 'adapter'}: {name} is required")
		if not self.routes:
			raise ValueError(f"{self.adapter_id}: at least one route pattern is required")
		if not self.tested_versions:
			raise ValueError(f"{self.adapter_id}: record at least one tested version")
		if self.hosting == STANDALONE and self.visual_ready and not self.stylesheet:
			raise ValueError(f"{self.adapter_id}: a visual standalone adapter needs a stylesheet")
		if self.hosting not in (STANDALONE, DESK_HOSTED):
			raise ValueError(f"{self.adapter_id}: unknown hosting {self.hosting!r}")
		if self.supports_system_font and self.hosting != STANDALONE:
			raise ValueError(f"{self.adapter_id}: only a standalone app needs the system font linked")
		if self.script and ("/" in self.script or "\\" in self.script or ".." in self.script):
			raise ValueError(f"{self.adapter_id}: script must be a file name, not a path")

	@property
	def asset_url(self) -> str:
		"""Bench-relative URL of the adapter stylesheet, or an empty string."""
		if not self.stylesheet:
			return ""
		return (
			"/assets/smartprocee_erpnext_persiant/css/rtl/"
			f"{self.target_app}/{self.stylesheet}"
		)

	@property
	def script_url(self) -> str:
		"""Bench-relative URL of the adapter script, or an empty string."""
		if not self.script:
			return ""
		return (
			"/assets/smartprocee_erpnext_persiant/js/rtl/"
			f"{self.target_app}/{self.script}"
		)
