import { dateToJD } from '$lib/format/date';

const MS_PER_DAY = 86_400_000;

/** How long a scrub has to hold still to count as come to rest. */
const SETTLE_MS = 400;

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
	/** Bumped by {@link jumpTo} only — a one-off jump the URL should reflect at
	 *  once. Scrubs stay on {@link setJD} so a drag doesn't spam history. */
	jumps = $state(0);
	/** The date for readers that can't afford a per-frame one — a whole porkchop
	 *  grid, say. Playback leaves it behind and it catches up once the clock comes
	 *  to rest, at once on a jump or a pause since those are the reader's own doing. */
	settledJd = $state(0);
	/** True while the clock still tracks wall-clock time: started at now and
	 *  never paused, jumped, reversed or run at another speed since. The URL
	 *  writes `now` instead of a date while this holds, so a shared link stays
	 *  live. */
	live = $state(false);
	private lastRealMs = 0;
	private prevScale = 1;
	private stops: BoundaryStops | null = null;
	private settleTimer: ReturnType<typeof setTimeout> | null = null;

	constructor(initialJd: number, live = false) {
		this.jd = initialJd;
		this.settledJd = initialJd;
		this.live = live;
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
		if (signed !== 1) this.live = false;
		// Reset timer so scale changes don't cause a large jump from accumulated delta.
		this.lastRealMs = performance.now();
	}

	toggleDirection(): void {
		this.direction = this.direction === 1 ? -1 : 1;
		this.timeScale = -this.timeScale;
		this.prevScale = -this.prevScale;
		this.live = false;
		this.lastRealMs = performance.now();
	}

	setJD(jd: number): void {
		this.jd = jd;
		this.seeked = true;
		this.live = false;
		this.lastRealMs = performance.now();
		this.settleAfterPause();
	}

	/** Seek, and mark it as a discrete jump so listeners can react to the one
	 *  move rather than to a stream of them. */
	jumpTo(jd: number): void {
		this.setJD(jd);
		this.jumps++;
		this.settle();
	}

	/** Rest the settled date on where the clock stands now. */
	private settle(): void {
		if (this.settleTimer !== null) clearTimeout(this.settleTimer);
		this.settleTimer = null;
		this.settledJd = this.jd;
	}

	/** The same, once a drag holds still. A clock still playing is left alone: it
	 *  never comes to rest, and the pause that ends it settles it anyway. */
	private settleAfterPause(): void {
		if (this.settleTimer !== null) clearTimeout(this.settleTimer);
		this.settleTimer = null;
		if (this.playing) return;
		this.settleTimer = setTimeout(() => this.settle(), SETTLE_MS);
	}

	/** Move the clock like playback, one frame at a time, rather than jumping.
	 *  Deliberately doesn't set {@link seeked} — that flag re-anchors the focus,
	 *  and firing it every sweep frame would drag the camera off its target. */
	sweepTo(jd: number): void {
		this.jd = jd;
		this.live = false;
		this.lastRealMs = performance.now();
	}

	pause(): void {
		if (this.timeScale !== 0) this.prevScale = this.timeScale;
		this.timeScale = 0;
		this.live = false;
		this.settle();
	}

	play(): void {
		if (this.timeScale === 0) {
			this.timeScale = this.prevScale || 1;
			this.lastRealMs = performance.now();
		}
	}

	/** Back to wall-clock time; live again only if playback is at 1×, since a
	 *  paused or fast clock drifts off it at once. */
	now(): void {
		this.jumpTo(dateToJD(new Date()));
		this.live = this.timeScale === 1;
	}

	get playing(): boolean {
		return this.timeScale !== 0;
	}
}
