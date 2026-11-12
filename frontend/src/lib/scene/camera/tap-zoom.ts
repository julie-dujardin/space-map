/** Longest a finger may stay down and still tap, in ms. */
export const TAP_MAX_MS = 300;

/** Longest from one tap's lift to the next touch for the two to be a double
 *  tap, in ms. */
export const DOUBLE_TAP_GAP_MS = 300;

/** How far a finger may move, in CSS pixels, and still tap. */
export const TAP_SLOP = 10;

/** How far apart two taps may land, in CSS pixels, to be one double tap. */
const DOUBLE_TAP_SPREAD = 40;

export interface TouchSample {
	id: number;
	x: number;
	y: number;
	/** Event time, in ms. */
	t: number;
}

/** What a touch sequence asks of the camera. */
export type TapZoomAction =
	/** Zoom in at the point: the second tap of a double tap. */
	| { type: 'in'; x: number; y: number }
	/** Zoom out about the point between the fingers: a two-finger tap. */
	| { type: 'out'; x: number; y: number }
	/** The second tap of a double tap stayed down and moved: from here on the
	 *  finger zooms about where it came down. */
	| { type: 'drag-start'; x: number; y: number }
	/** The finger went down the screen by `down` pixels since the last step. */
	| { type: 'drag'; down: number }
	| { type: 'drag-end' };

interface Down {
	x: number;
	y: number;
	t: number;
	moved: boolean;
}

/**
 * Reads the taps a map app zooms on: a double tap zooms in where it lands, a
 * two-finger tap zooms out, and a double tap whose second touch stays down
 * and slides zooms with the finger, in as it goes down the screen. Touches
 * come in one at a time; each call returns what the camera should do, if
 * anything.
 */
export class TapZoomGesture {
	private readonly downs = new Map<number, Down>();
	/** Most fingers down at once since the gesture began. */
	private most = 0;
	private gestureStart = 0;
	/** A finger moved past the slop, or stayed down too long: no tap. */
	private spoilt = false;
	/** The last single tap, which a second one could make a double tap. */
	private lastTap: { x: number; y: number; t: number } | null = null;
	/** The finger of a double tap's second touch, while it is down. */
	private second: number | null = null;
	private dragging = false;
	private lastY = 0;
	/** The pointer whose lift the camera answered: not a tap on anything. */
	private claimed: number | null = null;
	/** Where the first finger of two to lift came down. */
	private firstLift: Down | null = null;

	/** Whether this pointer's touch belongs to a zoom, so its lift picks
	 *  nothing. Holds until the next touch. */
	claims(id: number): boolean {
		return this.claimed === id;
	}

	/** Whether this pointer is the second touch of a double tap, which the
	 *  orbit should leave alone. */
	holds(id: number): boolean {
		return this.second === id;
	}

	/** Forget every touch: zooming is off, or something else took the camera. */
	reset(): void {
		this.downs.clear();
		this.lastTap = null;
		this.second = null;
		this.dragging = false;
		this.claimed = null;
		this.firstLift = null;
	}

	down(s: TouchSample): TapZoomAction | null {
		let ended: TapZoomAction | null = null;
		if (this.downs.size === 0) {
			this.most = 0;
			this.spoilt = false;
			this.gestureStart = s.t;
			this.claimed = null;
			this.firstLift = null;
			const last = this.lastTap;
			this.lastTap = null;
			if (
				last &&
				s.t - last.t <= DOUBLE_TAP_GAP_MS &&
				Math.hypot(s.x - last.x, s.y - last.y) <= DOUBLE_TAP_SPREAD
			) {
				this.second = s.id;
				this.claimed = s.id;
			}
		} else if (this.second !== null) {
			// A second finger turns a double tap into a pinch.
			ended = this.endDrag();
			this.second = null;
		}
		this.downs.set(s.id, { x: s.x, y: s.y, t: s.t, moved: false });
		this.most = Math.max(this.most, this.downs.size);
		return ended;
	}

	move(s: TouchSample): TapZoomAction | null {
		const d = this.downs.get(s.id);
		if (!d) return null;
		if (!d.moved && Math.hypot(s.x - d.x, s.y - d.y) > TAP_SLOP) {
			d.moved = true;
			this.spoilt = true;
		}
		if (s.id !== this.second || !d.moved) return null;
		if (!this.dragging) {
			this.dragging = true;
			this.lastY = s.y;
			return { type: 'drag-start', x: d.x, y: d.y };
		}
		const down = s.y - this.lastY;
		this.lastY = s.y;
		return down === 0 ? null : { type: 'drag', down };
	}

	up(s: TouchSample): TapZoomAction | null {
		const d = this.downs.get(s.id);
		if (!d) return null;
		this.downs.delete(s.id);
		if (s.t - this.gestureStart > TAP_MAX_MS) this.spoilt = true;
		if (s.id === this.second) {
			this.second = null;
			if (this.dragging) return this.endDrag();
			if (!this.spoilt && this.most === 1) return { type: 'in', x: d.x, y: d.y };
			return null;
		}
		if (this.downs.size > 0) {
			this.firstLift ??= d;
			return null;
		}
		if (this.spoilt) return null;
		if (this.most === 1) {
			this.lastTap = { x: s.x, y: s.y, t: s.t };
			return null;
		}
		if (this.most === 2) return this.twoFingerTap(d);
		return null;
	}

	/** The touch was taken from the page: whatever it was doing ends. */
	cancel(id: number): TapZoomAction | null {
		if (!this.downs.delete(id)) return null;
		this.spoilt = true;
		this.lastTap = null;
		if (id !== this.second) return null;
		this.second = null;
		return this.endDrag();
	}

	/** Two fingers both lifted, the second now: the zoom goes about the point
	 *  between where they came down. */
	private twoFingerTap(last: Down): TapZoomAction {
		const first = this.firstLift ?? last;
		return { type: 'out', x: (first.x + last.x) / 2, y: (first.y + last.y) / 2 };
	}

	private endDrag(): TapZoomAction | null {
		if (!this.dragging) return null;
		this.dragging = false;
		return { type: 'drag-end' };
	}
}
