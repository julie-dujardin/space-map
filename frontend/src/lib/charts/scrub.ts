/** px a touch must travel before it reads as a scrub rather than a tap. */
export const DRAG_SLOP = 8;

interface ScrubOptions {
	/** Hit-test the pointer position and show its preview. */
	onScrub: (clientX: number, clientY: number) => void;
	/** Drop the preview. Only called if a scrub actually started. */
	onEnd: () => void;
}

export interface ScrubHandlers {
	onpointerdown: (e: PointerEvent) => void;
	onpointermove: (e: PointerEvent) => void;
	onpointerup: () => void;
	onpointercancel: () => void;
	onpointerleave: () => void;
}

/**
 * Touch drag-to-scrub for a chart: dragging previews whatever is under the
 * finger, while a tap keeps its native action (click → navigate or focus).
 * Mouse hover stays on the per-element handlers, so the returned handlers
 * ignore mouse pointers.
 */
export function createScrub({ onScrub, onEnd }: ScrubOptions): ScrubHandlers {
	let downX: number | null = null;
	let downY = 0;
	let scrubbing = false;

	function end() {
		if (scrubbing) onEnd();
		downX = null;
		scrubbing = false;
	}

	return {
		onpointerdown(e) {
			if (e.pointerType === 'mouse') return;
			downX = e.clientX;
			downY = e.clientY;
			scrubbing = false;
		},
		onpointermove(e) {
			if (e.pointerType === 'mouse' || downX === null) return;
			if (!scrubbing && Math.hypot(e.clientX - downX, e.clientY - downY) < DRAG_SLOP) return;
			scrubbing = true;
			onScrub(e.clientX, e.clientY);
		},
		onpointerup: end,
		onpointercancel: end,
		onpointerleave: end
	};
}
