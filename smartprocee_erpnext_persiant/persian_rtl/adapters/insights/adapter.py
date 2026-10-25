"""RTL adapter for Frappe Insights (standalone SPA at ``/insights``).

Registered and diagnosed, but no visual layer yet. Phase 1 proves the mechanism
on CRM only; Insights is the first candidate afterwards. The entry template
(``insights/www/insights.html``, Insights 3.14.2) declares
``<html lang="en" class="h-full bg-gray-100">`` with no ``dir`` and no RTL
stylesheet, so it is LTR-only today -- but nothing is applied until its own
adapter CSS has been written and verified.
"""

from smartprocee_erpnext_persiant.persian_rtl.adapters.base import STANDALONE, Adapter

ADAPTER = Adapter(
	adapter_id="insights",
	title="Insights",
	target_app="insights",
	entry_template="insights/www/insights.html",
	entry_anchor="",
	hosting=STANDALONE,
	routes=("/insights/*", "/insights_v2/*"),
	tested_versions=("3.14.2", "3.15.1"),
	compatible_min="3.14.0",
	compatible_max="3.15.99",
	stylesheet="",
	visual_ready=False,
	exclusions=(),
	risk="high",
	notes=(
		"Identified and diagnosed only. Insights is a dashboard product: charts, "
		"pivot tables and data grids dominate the interface, so it needs its own "
		"direction-sensitive analysis before any mirroring is safe."
	),
)
