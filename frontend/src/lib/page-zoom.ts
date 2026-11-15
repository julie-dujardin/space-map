/**
 * The browser's own zoom, kept off the map.
 *
 * Every pinch on the map's canvas is the camera's, so a page zoomed in by any
 * other means cannot be pinched back out from the map: the reader is left on a
 * magnified corner of it. On Android a pinch that lands on the buttons, the
 * sheet or the menu over the map zooms the page; on an iPhone or iPad, so does
 * the focus of any text field under 16px, which most of ours are.
 *
 * Two settings on the viewport tag, then:
 * - While a page holding the map is open, the page does not zoom at all.
 *   Chrome's "Force enable zoom" still overrides it, for a reader who needs to.
 *   Setting it also takes a page already zoomed back to its own size.
 * - On Apple touch devices, `maximum-scale=1` everywhere. Safari reads it only
 *   to stop the zoom on a field's focus: since iOS 10 the reader's own pinch
 *   ignores it, so it costs no one anything.
 */

const LOCKED = 'maximum-scale=1, user-scalable=no';
const APPLE = 'maximum-scale=1';

let locks = 0;
/** The tag as the page shipped it, read once. */
let base: string | null = null;

/** An iPhone or iPad, the latter also when it asks for the desktop site and
 *  calls itself a Mac. */
function isAppleTouch(): boolean {
	const ua = navigator.userAgent;
	return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

function apply(): void {
	const meta = document.querySelector<HTMLMetaElement>('meta[name="viewport"]');
	if (!meta) return;
	base ??= meta.content;
	const extra = locks > 0 ? LOCKED : isAppleTouch() ? APPLE : '';
	const content = extra ? `${base}, ${extra}` : base;
	if (meta.content !== content) meta.content = content;
}

/** Set the viewport tag for the page as it is; call once at start. */
export function initPageZoom(): void {
	if (typeof document !== 'undefined') apply();
}

/** Keep the page from zooming until the returned function is called. Locks
 *  count, so two maps on one page hold it between them. */
export function lockPageZoom(): () => void {
	if (typeof document === 'undefined') return () => {};
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
