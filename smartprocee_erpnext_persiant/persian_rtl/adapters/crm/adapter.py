"""RTL adapter for Frappe CRM (standalone SPA served at ``/crm``).

Why CRM needs an adapter layer
------------------------------
CRM 1.85 renders its own document (``crm/www/crm.html``) and therefore never
receives Frappe's ``head.html``, ``app_include_css`` or ``web_include_css``. Its
front end is Tailwind CSS 4 with *physical* directional utilities only -- 87
distinct classes across ``ml-*``, ``mr-*``, ``pl-*``, ``pr-*``, ``left-*``,
``right-*``, ``border-l*``, ``border-r*``, ``rounded-l*``, ``rounded-r*``,
``float-*`` and ``text-*`` -- and no ``rtl:`` variants and no logical
``*-inline-*`` properties anywhere in the built stylesheets.

Consequence: setting ``dir="rtl"`` alone gives Persian text the right direction
while every spacing, offset and edge of the interface stays physically anchored
to the left. ``adapter.css`` cancels each physical declaration and re-states it
on the mirrored logical side.

Known limitation, stated on purpose
-----------------------------------
The mirror is a *cancelling* override layer. It cannot rewrite CRM's stylesheet,
so when one element carries two non-zero utilities of the same family (for
example ``ml-2`` together with ``mr-3``) only the later rule in ``adapter.css``
survives for the shared axis. CRM uses no ``space-x-*`` or ``divide-x-*`` and its
symmetric ``inset-x-*`` utilities are left alone, so the exposed surface is
small -- but it is real, and it is why the risk is recorded as high and the
adapter is expected to be verified visually before release.
"""

from smartprocee_erpnext_persiant.persian_rtl.adapters.base import STANDALONE, Adapter, Exclusion

ADAPTER = Adapter(
	adapter_id="crm",
	title="CRM",
	target_app="crm",
	entry_template="crm/www/crm.html",
	entry_anchor='id="app"',
	hosting=STANDALONE,
	# `/crm-form/*` is the public web form entry point and shares the same bundle.
	routes=("/crm/*", "/crm-form/*"),
	tested_versions=("1.85.1",),
	compatible_min="1.85.0",
	compatible_max="1.89.99",
	stylesheet="adapter.css",
	# ListHeaderItem resizes with a physical clientX delta; this script inverts
	# that delta only while the mirrored list-column handle is dragged.
	script="list-resize.js",
	# Physical utilities that prove the front end still needs mirroring.
	signature_physical=(
		"ml-2",
		"mr-2",
		"pl-3",
		"pr-3",
		"left-0",
		"right-0",
		"text-left",
		"text-right",
		"border-l",
		"border-r",
		"rounded-l",
		"rounded-r",
		"float-left",
	),
	# If these ever appear, CRM has adopted logical properties and this adapter
	# should be retired rather than kept in front of it.
	signature_logical=(
		"ms-2",
		"me-2",
		"ps-3",
		"pe-3",
		"start-0",
		"end-0",
		"text-start",
		"text-end",
		"border-s",
		"border-e",
	),
	exclusions=(
		Exclusion(
			label="Charts and dashboard canvas",
			selector=".echart-container, .chart-container, .frappe-chart, svg.chart",
			mode="LTR Island",
			review="Charts are plotted from left to right; mirroring the axes would "
			"misrepresent the data. Verify each chart type visually.",
		),
		Exclusion(
			label="Kanban board",
			selector=".kanban, .kanban-column, [data-kanban]",
			mode="LTR Island",
			review="Column order and drag/drop coordinates are pointer based.",
		),
		Exclusion(
			label="Rich text editor",
			selector=".ql-editor, .tiptap, [contenteditable='true']",
			mode="Auto Direction",
			review="Editor content can be Persian, English or mixed, so the browser "
			"should decide per paragraph instead of a forced direction.",
		),
		Exclusion(
			label="Phone numbers",
			selector="a[href^='tel:'], .phone-number, [data-phone]",
			mode="LTR Island",
			review="A phone number is read left to right.",
		),
		Exclusion(
			label="Email addresses",
			selector="a[href^='mailto:'], code, pre, kbd, samp",
			mode="LTR Island",
			review="Technical tokens keep their writing direction.",
		),
		Exclusion(
			label="Graph and workflow editors",
			selector=".workflow-builder, .graph-editor, .vue-flow",
			mode="LTR Island",
			review="Node coordinates are absolute and must not be mirrored.",
		),
	),
	risk="high",
	# CRM sets its font only on `html`, `.font-sans` and the toast container;
	# code, `.font-mono` and the editor's `pre` set their own monospace stack, and
	# its icons are inline SVG, so the adapter font rules leave all of them alone.
	supports_system_font=True,
	notes=(
		"Visually verified against CRM 1.85.1. CRM 1.89.1 still serves /crm as a "
		"standalone SPA (crm/www/crm.py, no crm.html) and still uses physical "
		"Tailwind utilities plus ListHeaderItem clientX resize. The adapter range "
		"includes 1.89.x so a matching site is not skipped as a version mismatch. "
		"Live browser proof on 1.89.1 is recorded separately. When the physical "
		"utilities disappear this adapter can be retired."
	),
)
