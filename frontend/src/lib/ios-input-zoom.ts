/**
 * Safari on iPhone and iPad zooms the page in when a text field under 16px
 * takes the focus, and leaves it zoomed after the field lets go. The map's
 * canvas takes every pinch for itself, so nothing on it can zoom the page back
 * out: the reader is left on a magnified corner of the map. Most of our fields
 * are 14px.
 *
 * `maximum-scale=1` stops that zoom. Since iOS 10 Safari ignores it for the
 * reader's own pinch, so it costs no one the zoom they ask for. Elsewhere it
 * would take pinch-zoom away, so it goes on Apple touch devices only.
 */

/** An iPhone or iPad, the latter also when it asks for the desktop site and
 *  calls itself a Mac. */
function isAppleTouch(): boolean {
	const ua = navigator.userAgent;
	return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

export function keepInputsFromZooming(): void {
	if (typeof document === 'undefined' || !isAppleTouch()) return;
	const meta = document.querySelector<HTMLMetaElement>('meta[name="viewport"]');
	if (!meta || /maximum-scale/.test(meta.content)) return;
	meta.content = `${meta.content}, maximum-scale=1`;
}
