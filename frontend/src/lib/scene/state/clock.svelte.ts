import { dateToJD } from '$lib/format/date';

const MS_PER_DAY = 86_400_000;

/** Optional boundary stops consulted only inside `tick()`. `setJD` bypasses
 *  them — slider scrubs cross freely. */
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
	/** Set by {@link setJD}; the renderer reads and clears it to tell a deliberate
	 *  date jump from playback. */
	seeked = false;
	private lastRealMs = 0;
	private prevScale = 1;
	private stops: BoundaryStops | null = null;

	constructor(initialJd: number) {
		this.jd = initialJd;
		this.lastRealMs = performance.now();
	}

	/** Advance jd by real elapsed time. Clamps to an armed boundary stop and pauses. */
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

	/** Arm or replace the boundary stops consulted by {@link tick}; `null` clears. */
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
		this.seeked = true;
		this.lastRealMs = performance.now();
	}

	/** Move the clock like playback, one frame at a time, rather than jumping.
	 *  Deliberately doesn't set {@link seeked} — that flag re-anchors the focus,
	 *  and firing it every sweep frame would drag the camera off its target. */
	sweepTo(jd: number): void {
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
