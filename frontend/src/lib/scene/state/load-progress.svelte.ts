/**
 * Progress model for the "Loading data" bar. Milestones raise a monotonic
 * floor as each load stage finishes; streamed boot bytes fill the gap toward
 * the next floor, so the bar tracks real download activity, not a timer. Fill
 * is capped short of the floor so a milestone always moves the bar, and it
 * never regresses when a later fetch enlarges the announced total mid-gap.
 */

/** Cumulative fraction per stage — rough cold-cache wall-clock share, widest
 *  band for ephemeris (planets + probes). */
const MILESTONES = {
	metadata: 0.12,
	ephemeris: 0.55,
	majors: 0.8,
	labels: 0.92,
	done: 1
} as const;
export type Milestone = keyof typeof MILESTONES;
const ORDER: Milestone[] = ['metadata', 'ephemeris', 'majors', 'labels', 'done'];

const GAP_FILL_CAP = 0.9;

class LoadProgress {
	#floor = 0;
	#nextTarget: number = MILESTONES.metadata;
	// Bytes since the last milestone; reset each gap.
	#loaded = 0;
	#total = 0;
	#active = false;

	/** 0..1, monotonic within a load. Bound by the bar. */
	value = $state(0);

	/** True while the loading screen is up and boot fetches should be counted. */
	get active(): boolean {
		return this.#active;
	}

	#recompute(): void {
		const gap = this.#nextTarget - this.#floor;
		const frac = this.#total > 0 ? Math.min(this.#loaded / this.#total, 1) : 0;
		const v = this.#floor + gap * frac * GAP_FILL_CAP;
		if (v > this.value) this.value = v;
	}

	reset(): void {
		this.#floor = 0;
		this.#nextTarget = MILESTONES.metadata;
		this.#loaded = 0;
		this.#total = 0;
		this.#active = true;
		this.value = 0;
	}

	/** A load stage finished — raise the floor and open the next gap. */
	reach(key: Milestone): void {
		if (!this.#active) return;
		const target = MILESTONES[key];
		if (target <= this.#floor) return; // duplicate / out-of-order
		this.#floor = target;
		if (this.value < target) this.value = target;
		const next = ORDER[ORDER.indexOf(key) + 1];
		this.#nextTarget = next ? MILESTONES[next] : target;
		this.#loaded = 0;
		this.#total = 0;
		if (key === 'done') {
			this.value = 1;
			this.#active = false;
		}
	}

	/** A boot fetch's expected size (gzipped Content-Length). */
	announce(total: number): void {
		if (!this.#active || total <= 0) return;
		this.#total += total;
		this.#recompute();
	}

	/** Compressed bytes as they stream in for an in-flight boot fetch. */
	addBytes(loaded: number): void {
		if (!this.#active) return;
		this.#loaded += loaded;
		this.#recompute();
	}
}

/** Singleton shared by the loading bar and boot fetches. */
export const loadProgress = new LoadProgress();
