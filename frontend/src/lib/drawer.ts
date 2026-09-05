/**
 * Gap kept between a fully open mobile drawer and the top of the viewport.
 * Meets the collapsed search bar's top (pinned at top-4 = 16px), covering it
 * while leaving that same map sliver above. Shared so every drawer stops on
 * the same line.
 */
export const DRAWER_TOP_GAP_PX = 16;

/** The mobile sheet's top snap point for a given viewport height. Shared so
 *  the drawer's resize re-pin and the sheet's snap list can't disagree. */
export function topSnapPx(innerHeight: number): string {
	return `${Math.max(1, innerHeight - DRAWER_TOP_GAP_PX)}px`;
}

/** vaul's snap transition (its unexported TRANSITIONS.DURATION). */
const SNAP_TRANSITION_MS = 500;

export interface SheetCover {
	/** Whether the sheet is parked on its top snap. */
	setAtTop(atTop: boolean): void;
	onDrag(): void;
	onRelease(): void;
	dispose(): void;
}

/**
 * Whether a mobile sheet hides the map behind it: parked on its top snap,
 * nobody pulling it, slide finished. vaul moves `activeSnapPoint` at release,
 * half a second before the sheet arrives, and reports nothing while a pull is
 * under way — so the first pull uncovers at once, and a snap to the top covers
 * only once the slide is over.
 */
export function trackSheetCover(onChange: (covers: boolean) => void): SheetCover {
	let atTop = false;
	let dragging = false;
	let sliding = false;
	let reported = false;
	let timer: ReturnType<typeof setTimeout> | undefined;
	const report = () => {
		const covers = atTop && !dragging && !sliding;
		if (covers === reported) return;
		reported = covers;
		onChange(covers);
	};
	const slide = () => {
		clearTimeout(timer);
		sliding = true;
		report();
		timer = setTimeout(() => {
			sliding = false;
			report();
		}, SNAP_TRANSITION_MS);
	};
	return {
		setAtTop(v) {
			atTop = v;
			if (v) slide();
			else report();
		},
		onDrag() {
			if (dragging) return;
			dragging = true;
			clearTimeout(timer);
			report();
		},
		onRelease() {
			if (!dragging) return;
			dragging = false;
			slide();
		},
		dispose() {
			clearTimeout(timer);
			if (reported) onChange(false);
		}
	};
}
