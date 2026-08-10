/**
 * Flying the trip on the simulation clock.
 *
 * The timeline can seek — that is one `setJD` — but watching a trip happen is
 * the point of having one: the destination sweeps round to meet the craft, and
 * a jump from departure to arrival shows the two ends without ever showing that.
 * So playback sweeps the clock leg by leg, pausing at each entry on the way.
 *
 * It drives the clock a frame at a time rather than by setting a time scale.
 * Both would move the clock, but the scale is the user's — a magnitude, a
 * direction, and a speed to resume at — and a run of playback should give it
 * back untouched. This also keeps the boundary stops free, which the focused
 * probe's coverage window already owns.
 */

import type { SimClock } from '$lib/scene/state/clock.svelte';
import { entryIndexAt, type TimelineEntry } from './timeline';

/** Real seconds the whole trip takes, before the per-phase floor. */
const TRIP_SECONDS = 12;
/** No phase goes by faster than this, however short a part of the trip it is. */
const MIN_PHASE_SECONDS = 1.6;
/** Time to look at a phase's end before setting off again. */
const DWELL_MS = 900;
/** The same for a burn, which is over the moment it happens — long enough to
 *  read, short enough that four in a row are not a wait. */
const INSTANT_DWELL_MS = 450;

export interface PlaybackHost {
	clock: SimClock;
	/** Read fresh each time: the route can be re-picked mid-run. */
	entries: () => readonly TimelineEntry[];
	/** Point the camera at where this part of the trip happens. */
	focus: (entry: TimelineEntry) => void;
}

/** Ease in and out, so a leg starts and ends at rest instead of snapping. */
function smoothstep(t: number): number {
	return t * t * (3 - 2 * t);
}

/** How long a stretch of `days` should take, out of a trip of `totalDays`.
 *  Zero for a burn: nothing moves, so there is nothing to watch go by. */
export function legSeconds(days: number, totalDays: number): number {
	if (!(days > 0)) return 0;
	if (!(totalDays > 0)) return MIN_PHASE_SECONDS;
	return Math.max(MIN_PHASE_SECONDS, (TRIP_SECONDS * days) / totalDays);
}

export class TripPlayback {
	playing = $state(false);

	private host: PlaybackHost;
	private frame = 0;
	/** The entry being flown to. */
	private toIndex = 0;
	private fromJd = 0;
	private toJd = 0;
	private startedMs = 0;
	private durationMs = 0;
	/** Set while dwelling on an entry; the next leg starts when it passes. */
	private dwellUntilMs = 0;

	constructor(host: PlaybackHost) {
		this.host = host;
	}

	/** Put the clock on `entries[index]` and look at where it happens. */
	go(index: number): void {
		const entry = this.host.entries()[index];
		if (!entry) return;
		this.host.clock.setJD(entry.startJd);
		this.host.focus(entry);
	}

	/** Move `delta` entries from wherever the clock currently is. */
	step(delta: number): void {
		const entries = this.host.entries();
		if (entries.length === 0) return;
		this.stop();
		const at = entryIndexAt(entries, this.host.clock.jd);
		// Stepping back from inside a phase means the start of that phase, not the
		// entry before it — the clock is not on `at`, it is past it.
		const onEntry = entries[at].startJd === this.host.clock.jd;
		const next = delta < 0 && !onEntry ? at : at + delta;
		this.go(Math.min(entries.length - 1, Math.max(0, next)));
	}

	toggle(): void {
		if (this.playing) this.stop();
		else this.start();
	}

	start(): void {
		const entries = this.host.entries();
		if (entries.length < 2) return;
		this.stop();
		// Resume from where the clock is, unless the trip is already over — then the
		// button means "watch it again" rather than "do nothing". Over means past
		// the last entry's whole span: inside the final phase there is still a leg
		// to fly.
		const last = entries[entries.length - 1];
		const at = entryIndexAt(entries, this.host.clock.jd);
		const over = at >= entries.length - 1 && !(this.host.clock.jd < last.endJd);
		const from = over ? 0 : at;
		this.go(from);
		this.host.clock.pause();
		this.playing = true;
		this.beginLeg(from + 1);
		this.frame = requestAnimationFrame(this.tick);
	}

	stop(): void {
		if (this.frame !== 0) cancelAnimationFrame(this.frame);
		this.frame = 0;
		this.playing = false;
	}

	dispose(): void {
		this.stop();
	}

	private beginLeg(index: number): void {
		const entries = this.host.entries();
		const from = entries[index - 1];
		// One past the end is the last leg: the final entry's own span, which the
		// legs between startJds never cover — without it the trip stops at the
		// start of its last phase instead of at its arrival.
		const to = entries[index] ?? null;
		if (!from || (!to && !(from.endJd > from.startJd))) {
			this.stop();
			return;
		}
		this.toIndex = index;
		this.fromJd = from.startJd;
		this.toJd = to ? to.startJd : from.endJd;
		this.startedMs = performance.now();
		const trip = entries[entries.length - 1].endJd - entries[0].startJd;
		this.durationMs = legSeconds(this.toJd - this.fromJd, trip) * 1000;
		this.dwellUntilMs = 0;
	}

	private tick = (): void => {
		if (!this.playing) return;
		const entries = this.host.entries();
		const final = this.toIndex >= entries.length;
		const to = entries[final ? entries.length - 1 : this.toIndex];
		// The route changed under the run — its entries are no longer these ones,
		// and carrying on would fly a leg of one trip into another.
		if (!to || (final ? to.endJd : to.startJd) !== this.toJd) {
			this.stop();
			return;
		}

		const now = performance.now();
		if (this.dwellUntilMs !== 0) {
			if (now >= this.dwellUntilMs) this.beginLeg(this.toIndex + 1);
		} else {
			const t = this.durationMs > 0 ? Math.min(1, (now - this.startedMs) / this.durationMs) : 1;
			this.host.clock.sweepTo(this.fromJd + (this.toJd - this.fromJd) * smoothstep(t));
			if (t >= 1) {
				this.host.focus(to);
				// Done once the last leg is flown — or once the last entry is reached
				// with no span of its own left to fly.
				if (final || (this.toIndex === entries.length - 1 && !(to.endJd > to.startJd))) {
					this.stop();
					return;
				}
				this.dwellUntilMs = now + (this.toJd > this.fromJd ? DWELL_MS : INSTANT_DWELL_MS);
			}
		}
		this.frame = requestAnimationFrame(this.tick);
	};
}
