"""RTL adapter for Raven (standalone SPA at ``/raven``).

Registered and diagnosed, but no visual layer yet. ``raven/raven/www/raven.html``
in Raven 3.0.0 declares ``<html lang="en">`` with no ``dir`` and references no
RTL stylesheet, so the SPA itself is LTR-only. Raven's ``app_include_css`` and
``app_include_js`` apply to the Desk, not to this page.

Raven is the strongest candidate for a fully supported adapter: it is a Vue app
built on frappe-ui, which uses design tokens rather than hard-coded physical
utility classes. It is scheduled after CRM.
"""

from smartprocee_erpnext_persiant.persian_rtl.adapters.base import STANDALONE, Adapter

ADAPTER = Adapter(
	adapter_id="raven",
	title="Raven",
	target_app="raven",
	entry_template="raven/www/raven.html",
	entry_anchor="",
	hosting=STANDALONE,
	routes=("/raven/*",),
	tested_versions=("3.0.0",),
	compatible_min="3.0.0",
	compatible_max="3.0.99",
	stylesheet="",
	visual_ready=False,
	exclusions=(),
	risk="medium",
	notes=(
		"Identified and diagnosed only. Chat is the primary surface, so message "
		"bubbles and the composer need explicit handling before the shell is "
		"mirrored."
	),
)
