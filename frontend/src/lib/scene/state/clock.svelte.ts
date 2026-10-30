import { dateToJD, FIRST_DATE_JD, jdToDate, LAST_DATE_JD, MS_PER_DAY } from '$lib/time/jd';

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
 *
 * The clock holds only dates that a `Date` holds. A seek past them stops it at
 * the end of that range.
 */
export class SimClock {
	jd = $state(0);
	/** @internal The date that the last seek asked for. It differs from `jd`
	 *  only past the range of `Date`. A trip's craft and its timeline read it,
	 *  so that a trip runs on to an arrival that the clock cannot hold. */
	askedJd = $state(0);
	timeScale = $state(1);
	direction = $state<1 | -1>(1);
	/** @internal Set by {@link setJD}; the renderer reads and clears it to tell a
	 *  deliberate date jump from playback. */
	seeked = false;
	/** @internal Bumped by {@link jumpTo} only — a one-off jump the URL should
	 *  reflect at once. Scrubs stay on {@link setJD} so a drag doesn't spam
	 *  history. */
	jumps = $state(0);
	/** @internal The date for readers that can't afford a per-frame one — a whole porkchop
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
	/** The promises of {@link jumpTo} that wait for a frame at their date. */
	private arrivals: { jumps: number; resolve: () => void }[] = [];

	constructor(initialJd: number, live = false) {
		this.move(initialJd);
		this.settledJd = this.jd;
		this.live = live;
		this.lastRealMs = performance.now();
	}

	/** @internal Advance jd by real elapsed time. Clamps to an armed boundary
	 *  stop and pauses. */
	tick(nowMs: number): void {
		const dt = nowMs - this.lastRealMs;
		this.lastRealMs = nowMs;
		if (this.timeScale === 0) return;
		// From the date asked for: past the range of `Date`, `jd` is only its edge.
		const from = this.askedJd;
		const proposed = from + (dt / MS_PER_DAY) * this.timeScale;
		const stops = this.stops;
		if (stops !== null) {
			if (
				this.timeScale > 0 &&
				stops.forwardJd !== null &&
				proposed >= stops.forwardJd &&
				from < stops.forwardJd
			) {
				this.move(stops.forwardJd);
				this.pause();
				stops.onHit(stops.forwardJd);
				return;
			}
			if (
				this.timeScale < 0 &&
				stops.backwardJd !== null &&
				proposed <= stops.backwardJd &&
				from > stops.backwardJd
			) {
				this.move(stops.backwardJd);
				this.pause();
				stops.onHit(stops.backwardJd);
				return;
			}
		}
		this.move(proposed);
		if (this.askedJd === this.jd) return;
		// Time does not run past the dates the clock can hold. A run that leaves
		// the range stops at its edge. Past the range, a run goes on only back
		// toward it. A step further out holds, and has no new date to settle on.
		const inside = from >= FIRST_DATE_JD && from <= LAST_DATE_JD;
		const further = from > LAST_DATE_JD ? proposed > from : proposed < from;
		if (inside) {
			this.move(this.jd);
			this.pause();
		} else if (further) {
			this.move(from);
			this.hold();
		}
	}

	/** Put the clock on `jd`, or on the nearest date it can hold. */
	private move(jd: number): void {
		this.askedJd = jd;
		this.jd = Math.min(Math.max(jd, FIRST_DATE_JD), LAST_DATE_JD);
	}

	/** @internal Arm or replace the boundary stops consulted by {@link tick};
	 *  `null` clears. */
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

	/** @internal Seek without marking the move as a jump — for a dragged slider,
	 *  which would otherwise fill the history with every frame of the drag. */
	setJD(jd: number): void {
		this.move(jd);
		this.seeked = true;
		this.live = false;
		this.lastRealMs = performance.now();
		this.settleAfterPause();
	}

	/** Move the clock to `jd` in one jump, so that listeners react to it once.
	 *  The promise resolves when a frame shows the bodies at that date. Until
	 *  the data of the date loads, the map shows the date before the jump, and
	 *  the measures answer for that date. */
	jumpTo(jd: number): Promise<void> {
		this.setJD(jd);
		this.jumps++;
		this.settle();
		const jumps = this.jumps;
		return new Promise((resolve) => this.arrivals.push({ jumps, resolve }));
	}

	/** @internal A frame shows the date of jump `jumps`. This resolves the
	 *  promises of that jump and of the jumps before it. */
	placed(jumps: number): void {
		if (this.arrivals.length === 0) return;
		this.arrivals = this.arrivals.filter((arrival) => {
			if (arrival.jumps > jumps) return true;
			arrival.resolve();
			return false;
		});
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

	/** @internal Move the clock like playback, one frame at a time, rather than jumping.
	 *  Deliberately doesn't set {@link seeked} — that flag re-anchors the focus,
	 *  and firing it every sweep frame would drag the camera off its target. */
	sweepTo(jd: number): void {
		this.move(jd);
		this.live = false;
		this.lastRealMs = performance.now();
	}

	pause(): void {
		this.hold();
		this.settle();
	}

	/** @internal Pause, and leave the settled date where it is. For playback,
	 *  which moves the clock to show a trip, not to plan one from. */
	hold(): void {
		if (this.timeScale !== 0) this.prevScale = this.timeScale;
		this.timeScale = 0;
		this.live = false;
		if (this.settleTimer !== null) clearTimeout(this.settleTimer);
		this.settleTimer = null;
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

	/** The moment the map is showing. */
	get date(): Date {
		return jdToDate(this.jd);
	}

	/** Move the clock to `date` in one jump. The promise resolves as the promise
	 *  of {@link jumpTo} does. */
	setDate(date: Date): Promise<void> {
		return this.jumpTo(dateToJD(date));
	}
}
