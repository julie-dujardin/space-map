/**
 * The browser's own zoom, kept off a full-screen view that takes every pinch.
 *
 * Every pinch on the map or a panorama is the view's, so a page zoomed in by
 * any other means cannot be pinched back out from it: the reader is left on a
 * magnified corner. A pinch that lands on a button or the sheet over the view
 * zooms the page, and on an iPhone or iPad so does the focus of any text field
 * under 16px, which most of ours are.
 *
 * While such a view is open the viewport tag forbids zooming, which also takes
 * a page already zoomed back to its own size. Chrome's "Force enable zoom"
 * still overrides it, for a reader who needs to. Safari ignores the tag for
 * the reader's pinch, so there the pinch itself is cancelled; only on a touch
 * screen, as a Mac's trackpad pinch never reaches the view and could always
 * zoom the page back out.
 */

const LOCKED = 'maximum-scale=1, user-scalable=no';

let locks = 0;
/** The tag as the page shipped it. */
let base: string | null = null;

const cancel = (e: Event): void => e.preventDefault();

function apply(): void {
	const meta = document.querySelector<HTMLMetaElement>('meta[name="viewport"]');
	if (meta) {
		base ??= meta.content;
		const content = locks > 0 ? `${base}, ${LOCKED}` : base;
		if (meta.content !== content) meta.content = content;
	}
	if (navigator.maxTouchPoints === 0) return;
	for (const type of ['gesturestart', 'gesturechange']) {
		if (locks > 0) document.addEventListener(type, cancel, { passive: false });
		else document.removeEventListener(type, cancel);
	}
}

/** Keep the page from zooming until the returned function is called. Locks
 *  count, so two views on one page hold it between them. */
export function lockPageZoom(): () => void {
	locks++;
	apply();
	let held = true;
	return () => {
		if (!held) return;
		held = false;
		locks--;
		apply();
	};
}
