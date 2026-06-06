import { dateToJD } from '$lib/format/date';

const MS_PER_DAY = 86_400_000;

/**
 * Optional boundary stops consulted only inside `tick()`. Forward stop fires
 * when `tick` would advance `jd` past `forwardJd` while `timeScale > 0`;
 * backward symmetric. `setJD` deliberately bypasses these — slider scrubs
 * cross freely.
 */
interface BoundaryStops {
	forwardJd: number | null;
	backwardJd: number | null;
	onHit: (jd: number) => void;
}

/**
 * Simulation clock. Advances Julian Date by real elapsed time × timeScale;
 * timeScale === 0 means paused. `play()` re-resumes the previous non-zero scale.
 */
export class SimClock {
	jd = $state(0);
	timeScale = $state(1);
	direction = $state<1 | -1>(1);
	private lastRealMs = 0;
	private prevScale = 1;
	private stops: BoundaryStops | null = null;

	constructor(initialJd: number) {
		this.jd = initialJd;
		this.lastRealMs = performance.now();
	}

	/** Advance jd based on real elapsed time since last tick. When boundary
	 *  stops are armed, clamp the new jd to the nearest stop in the time-step
	 *  direction and pause. */
	tick(nowMs: number): void {
		const dt = nowMs - this.lastRealMs;
		this.lastRealMs = nowMs;
		if (this.timeScale === 0) return;
		const proposed = this.jd + (dt / MS_PER_DAY) * this.timeScale;
		const stops = this.stops;
		if (stops !== null) {
			if (
				this.timeScale > 0 &&
				stops.forwardJd !== null &&
				proposed >= stops.forwardJd &&
				this.jd < stops.forwardJd
			) {
				this.jd = stops.forwardJd;
				this.pause();
				stops.onHit(stops.forwardJd);
				return;
			}
			if (
				this.timeScale < 0 &&
				stops.backwardJd !== null &&
				proposed <= stops.backwardJd &&
				this.jd > stops.backwardJd
			) {
				this.jd = stops.backwardJd;
				this.pause();
				stops.onHit(stops.backwardJd);
				return;
			}
		}
		this.jd = proposed;
	}

	/** Arm or replace the boundary stops consulted by {@link tick}. Pass `null`
	 *  for either side to disable that direction; pass `null` to the whole
	 *  setter to clear both. */
	setBoundaryStops(stops: BoundaryStops | null): void {
		this.stops = stops;
	}

	/** Caller passes the unsigned magnitude; direction is applied here. */
	setTimeScale(magnitude: number): void {
		const signed = magnitude * this.direction;
		if (signed !== 0) this.prevScale = signed;
		this.timeScale = signed;
		// Reset timer so scale changes don't cause a large jump from accumulated delta.
		this.lastRealMs = performance.now();
	}

	toggleDirection(): void {
		this.direction = this.direction === 1 ? -1 : 1;
		this.timeScale = -this.timeScale;
		this.prevScale = -this.prevScale;
		this.lastRealMs = performance.now();
	}

	setJD(jd: number): void {
		this.jd = jd;
		this.lastRealMs = performance.now();
	}

	pause(): void {
		if (this.timeScale !== 0) this.prevScale = this.timeScale;
		this.timeScale = 0;
	}

	play(): void {
		if (this.timeScale === 0) {
			this.timeScale = this.prevScale || 1;
			this.lastRealMs = performance.now();
		}
	}

	now(): void {
		this.setJD(dateToJD(new Date()));
	}

	get playing(): boolean {
		return this.timeScale !== 0;
	}
}
