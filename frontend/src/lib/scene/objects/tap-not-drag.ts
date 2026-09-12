/**
 * Tap-vs-drag for the map's labels: a camera drag that happens to start on a
 * label must not read as a press on it.
 *
 * Measured from `pointerdown` to `click` rather than from `pointermove`, which
 * stops firing as soon as the pointer leaves an element this small.
 */

/** How far the pointer may travel and still count as a tap. */
const TAP_SLOP_PX = 3;

/**
 * Call `handler` when `el` is tapped, not when it is dragged. The click is
 * always stopped from reaching the canvas underneath, drag or not.
 */
export function onTapNotDrag(
	el: HTMLElement,
	handler: (event: MouseEvent) => void,
	slopPx = TAP_SLOP_PX
): void {
	let downX = 0;
	let downY = 0;
	el.addEventListener('pointerdown', (event) => {
		downX = event.clientX;
		downY = event.clientY;
	});
	el.addEventListener('click', (event) => {
		event.stopPropagation();
		const dx = event.clientX - downX;
		const dy = event.clientY - downY;
		if (dx * dx + dy * dy <= slopPx * slopPx) handler(event);
	});
}
