/* Invert CRM list-column resize deltas under RTL.
 *
 * frappe-ui ListHeaderItem does `width + (clientX - startX)` and parks the
 * handle on `-right-2`. adapter.css mirrors that handle to inline-end (left in
 * RTL), so a physical +delta shrinks the column. This file rewrites clientX on
 * mousemove only while that handle is being dragged. The sidebar Resizer
 * (`w-1` / `left-0` / `right-0`) is left alone. LTR is a no-op.
 */
(function () {
	let originX = null;

	function isRtl() {
		return document.documentElement.getAttribute("dir") === "rtl";
	}

	function isListColumnHandle(target) {
		if (!target || !target.closest) {
			return false;
		}
		const handle = target.closest(".cursor-col-resize");
		if (!handle) {
			return false;
		}
		const tokens = " " + (handle.className || "") + " ";
		return tokens.indexOf(" -right-2 ") !== -1 || tokens.indexOf(" -left-2 ") !== -1;
	}

	function invertClientX(event) {
		if (originX == null) {
			return;
		}
		Object.defineProperty(event, "clientX", {
			configurable: true,
			value: originX - (event.clientX - originX),
		});
	}

	document.addEventListener(
		"mousedown",
		function (event) {
			if (!isRtl() || event.button || !isListColumnHandle(event.target)) {
				return;
			}
			originX = event.clientX;
		},
		true
	);
	document.addEventListener(
		"mousemove",
		function (event) {
			if (originX == null || !isRtl()) {
				return;
			}
			invertClientX(event);
		},
		true
	);
	document.addEventListener(
		"mouseup",
		function () {
			originX = null;
		},
		true
	);
})();
