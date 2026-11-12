import { MathUtils } from 'three';

/** How far a finger goes, in CSS pixels, before a two-finger gesture is read
 *  as a tilt or as the map's own pinch and pan. */
export const TWO_FINGER_SLOP = 10;

/** How far one finger goes, while the other has not moved at all, before the
 *  gesture is read without it: a pinch or twist about a finger held still. */
const TWO_FINGER_ALONE = 3 * TWO_FINGER_SLOP;

/** Steepest the line between the fingers may stand for a tilt: side by side,
 *  as a hand lies on a phone held upright. */
const TILT_MAX_SPREAD_SLOPE = Math.tan(MathUtils.degToRad(40));

/** How far a finger may stray sideways for each pixel it goes up or down, and
 *  still be tilting. */
const TILT_MAX_SIDEWAYS = 0.5;

/** The lesser finger's travel against the greater's for the two to move
 *  together: one finger held while the other sweeps is a pinch or a twist. */
const TILT_MIN_TOGETHER = 0.3;

/** Twist, in radians, before the heading starts to follow it, so a pinch does
 *  not turn the map by the wobble in it. */
export const TWIST_ENGAGE = MathUtils.degToRad(12);

export type TwoFingerMode = 'undecided' | 'tilt' | 'map';

export interface Point {
	x: number;
	y: number;
}

export interface TwoFingerStep {
	mode: TwoFingerMode;
	/** With `tilt`: how far the fingers went down since the last step, in pixels. */
	down: number;
	/** With `map`: how far the fingers turned clockwise on screen since the last
	 *  step, in radians, once the twist is past {@link TWIST_ENGAGE}. */
	twist: number;
}

/**
 * Reads a two-finger gesture the way a map app does: both fingers sliding up
 * or down side by side tilt the view, anything else pinches and pans, and a
 * twist past a few degrees turns it. The reading holds for the rest of the
 * gesture, so a tilt does not slide into a pan as the fingers drift.
 */
export class TwoFingerGesture {
	private mode: TwoFingerMode = 'map';
	private readonly a0 = { x: 0, y: 0 };
	private readonly b0 = { x: 0, y: 0 };
	private lastMidY = 0;
	private lastAngle = 0;
	private twisted = 0;
	private twisting = false;

	/** A second finger came down. Without `canTilt` the gesture is the map's
	 *  from the start, with nothing held back. */
	begin(a: Point, b: Point, canTilt: boolean): void {
		this.mode = canTilt ? 'undecided' : 'map';
		this.a0.x = a.x;
		this.a0.y = a.y;
		this.b0.x = b.x;
		this.b0.y = b.y;
		this.lastMidY = (a.y + b.y) / 2;
		this.lastAngle = Math.atan2(b.y - a.y, b.x - a.x);
		this.twisted = 0;
		this.twisting = false;
	}

	/** The fingers stand at `a` and `b`, in the order `begin` had them. */
	move(a: Point, b: Point): TwoFingerStep {
		const angle = Math.atan2(b.y - a.y, b.x - a.x);
		const turn = MathUtils.euclideanModulo(angle - this.lastAngle + Math.PI, 2 * Math.PI) - Math.PI;
		this.lastAngle = angle;
		const midY = (a.y + b.y) / 2;
		let down = midY - this.lastMidY;
		this.lastMidY = midY;
		this.twisted += turn;
		if (this.mode === 'undecided') {
			this.mode = this.decide(a, b);
			// From where the fingers came down, as the pinch and pan catch up.
			if (this.mode === 'tilt') down = midY - (this.a0.y + this.b0.y) / 2;
		}
		switch (this.mode) {
			case 'undecided':
				return { mode: 'undecided', down: 0, twist: 0 };
			case 'tilt':
				return { mode: 'tilt', down, twist: 0 };
			case 'map': {
				// From where the twist engaged on: the view does not jump by the
				// threshold.
				const engaged = this.twisting;
				this.twisting ||= Math.abs(this.twisted) > TWIST_ENGAGE;
				return { mode: 'map', down: 0, twist: engaged ? turn : 0 };
			}
		}
	}

	private decide(a: Point, b: Point): TwoFingerMode {
		const ax = a.x - this.a0.x;
		const ay = a.y - this.a0.y;
		const bx = b.x - this.b0.x;
		const by = b.y - this.b0.y;
		const aTravel = Math.hypot(ax, ay);
		const bTravel = Math.hypot(bx, by);
		const travel = Math.max(aTravel, bTravel);
		// The fingers report one at a time: until both have, the one that has
		// looks like it moves alone.
		const bothMoved = aTravel > 0 && bTravel > 0;
		if (travel < (bothMoved ? TWO_FINGER_SLOP : TWO_FINGER_ALONE)) return 'undecided';
		const sideBySide =
			Math.abs(this.b0.y - this.a0.y) <= Math.abs(this.b0.x - this.a0.x) * TILT_MAX_SPREAD_SLOPE;
		const vertical =
			Math.abs(ax) <= Math.abs(ay) * TILT_MAX_SIDEWAYS &&
			Math.abs(bx) <= Math.abs(by) * TILT_MAX_SIDEWAYS;
		const together =
			Math.sign(ay) === Math.sign(by) &&
			Math.min(aTravel, bTravel) >= Math.max(aTravel, bTravel) * TILT_MIN_TOGETHER;
		return sideBySide && vertical && together ? 'tilt' : 'map';
	}
}
