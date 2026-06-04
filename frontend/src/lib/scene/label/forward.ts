/**
 * Re-dispatch wheel/pointer gestures from a CSS2D overlay element onto the
 * canvas so OrbitControls keeps working when the user grabs a label.
 *
 * Wheel events fire on the label first; OrbitControls only listens on the
 * canvas, so without forwarding the user can't zoom while hovering a label.
 * Pointerdown is deferred: it forwards only once the gesture moves past
 * `DRAG_THRESHOLD_PX`, so a tap-and-release on the label still fires its own
 * click handler.
 */

import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

const DRAG_THRESHOLD_PX = 3;

export function attachCanvasForwarders(
	el: HTMLElement | CSS2DObject['element'],
	canvas: HTMLCanvasElement
): void {
	el.addEventListener(
		'wheel',
		(e: Event) => {
			const we = e as WheelEvent;
			canvas.dispatchEvent(
				new WheelEvent('wheel', {
					deltaY: we.deltaY,
					deltaMode: we.deltaMode,
					bubbles: true,
					cancelable: true
				})
			);
			we.preventDefault();
		},
		{ passive: false }
	);

	el.addEventListener('pointerdown', (e: PointerEvent) => {
		const downX = e.clientX;
		const downY = e.clientY;
		const savedDown = e;
		const onMove = (me: PointerEvent) => {
			const dx = me.clientX - downX;
			const dy = me.clientY - downY;
			if (dx * dx + dy * dy > DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX) {
				cleanup();
				canvas.dispatchEvent(new PointerEvent('pointerdown', savedDown));
				canvas.dispatchEvent(new PointerEvent('pointermove', me));
			}
		};
		const onUp = () => cleanup();
		const cleanup = () => {
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
		};
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	});
}
