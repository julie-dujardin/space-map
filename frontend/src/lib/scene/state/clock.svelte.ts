import { dateToJD } from '$lib/format/date';

const MS_PER_DAY = 86_400_000;

/**
 * Simulation clock. Advances Julian Date by real elapsed time * timeScale.
 * timeScale === 0 means paused. Read `jd` each frame (reactive).
 *
 * TODO: when time-varying elements land (osculating / SPK interpolation),
 * trail curves will need regeneration once sim-time drifts too far
 * from the curve's epoch. Fixed Keplerian elements don't require this.
 */
export class SimClock {
	jd = $state(0);
	timeScale = $state(1);
	direction = $state<1 | -1>(1);
	private lastRealMs = 0;
	private prevScale = 1;

	constructor(initialJd: number) {
		this.jd = initialJd;
		this.lastRealMs = performance.now();
	}

	/** Advance jd based on real elapsed time since last tick. */
	tick(nowMs: number): void {
		const dt = nowMs - this.lastRealMs;
		this.lastRealMs = nowMs;
		if (this.timeScale !== 0) {
			this.jd += (dt / MS_PER_DAY) * this.timeScale;
		}
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
