"""RTL compatibility adapters for standalone single-page apps.

Frappe ships RTL support for the Desk and the Website (``is_rtl``, ``dir`` on
``<html>``, ``rtl_*`` bundles). Bundled SPAs such as CRM, Insights and Raven
render their own document and bypass every one of those channels, so this
package adds a *supported* layer next to them instead of editing them.

Nothing here writes to another application. An adapter only declares what the
runtime is allowed to add to a response: one stylesheet link and a ``dir``
attribute on the document root.
"""
