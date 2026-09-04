/**
 * Fixed-capacity ring buffer of past trail positions for a probe with
 * chebyshev sub-chunks, stored in the fit-center-relative frame so rendering
 * just adds the current parent position. `append` overwrites the oldest entry
 * when full; time-speed agnostic since samples are spaced by `stepDays` on
 * average, keeping one orbital period of coverage once full.
 *
 * When `epsilonScene` is finite, callers may sample non-uniformly via
 * chord-error adaptive subdivision (dense near periapsis, sparse near
 * apoapsis); `stepDays` is then the canonical/average step, bracketed by
 * `ADAPTIVE_MIN/MAX_STEP_FACTOR`.
 */

/** Per-segment bounds for adaptive sampling, as multipliers of `stepDays`.
 *  The min floor is deep so periapsis passages can subdivide finely; it's
 *  only a floor, so cruise arcs still stop early and don't over-sample. */
export const ADAPTIVE_MAX_STEP_FACTOR = 16;
export const ADAPTIVE_MIN_STEP_FACTOR = 1 / 256;

export class TrailBuffer {
	readonly capacity: number;
	/** Canonical/average time between consecutive samples (days). */
	stepDays: number;
	/** Chord-error tolerance in scene units. `Infinity` disables adaptive
	 *  sampling — callers fall back to uniform `stepDays` spacing. */
	epsilonScene: number;
	/** How far back the back-fill may walk (days). One orbital period for
	 *  ellipses; `Infinity` for hyperbolic flybys, where capacity and zone
	 *  coverage bound the walk instead of one chunk window. */
	spanDays: number;
	/** Back-fill still owed: it runs the first frame the trail is visible, not
	 *  at load, since most probe trails never show. */
	needsPopulate = false;
	private readonly positions: Float32Array;
	private readonly jds: Float64Array;
	/** Index of the next write slot. `(head − 1) mod capacity` is the newest. */
	private head = 0;
	private _count = 0;

	constructor(capacity: number, stepDays: number, epsilonScene = Infinity, spanDays?: number) {
		this.capacity = capacity;
		this.stepDays = stepDays;
		this.epsilonScene = epsilonScene;
		this.spanDays = spanDays ?? stepDays * capacity;
		this.positions = new Float32Array(capacity * 3);
		this.jds = new Float64Array(capacity);
	}

	get count(): number {
		return this._count;
	}

	/** Re-derive sampling parameters for a new frame or orbit. Must be called
	 *  on every reseed against a different parent — stepDays/epsilonScene are
	 *  orbit-scale-dependent, so reusing heliocentric-cruise values for a
	 *  planet-frame flyby samples far too coarsely or too little time.
	 *  Non-finite/non-positive `stepDays` keeps the previous value. */
	reconfigure(stepDays: number, epsilonScene: number, spanDays?: number): void {
		if (Number.isFinite(stepDays) && stepDays > 0) this.stepDays = stepDays;
		this.epsilonScene = epsilonScene;
		this.spanDays = spanDays ?? this.stepDays * this.capacity;
	}

	/** JD of the most-recent sample, or NaN when empty. */
	get newestJd(): number {
		if (this._count === 0) return NaN;
		const idx = (this.head - 1 + this.capacity) % this.capacity;
		return this.jds[idx];
	}

	/**
	 * Write the newest sample's position into `out`. Returns true on success,
	 * false when the buffer is empty (in which case `out` is untouched).
	 */
	readNewestPos(out: [number, number, number]): boolean {
		if (this._count === 0) return false;
		const idx = (this.head - 1 + this.capacity) % this.capacity;
		const base = idx * 3;
		out[0] = this.positions[base];
		out[1] = this.positions[base + 1];
		out[2] = this.positions[base + 2];
		return true;
	}

	append(jd: number, x: number, y: number, z: number): void {
		const h = this.head;
		this.jds[h] = jd;
		this.positions[h * 3] = x;
		this.positions[h * 3 + 1] = y;
		this.positions[h * 3 + 2] = z;
		this.head = (h + 1) % this.capacity;
		if (this._count < this.capacity) this._count++;
	}

	clear(): void {
		this.head = 0;
		this._count = 0;
	}

	/**
	 * Write the buffered positions into `out` in newest-to-oldest order, each
	 * shifted by `(ox, oy, oz)` (typically `orbitCenter − basisPos`). Returns
	 * the number of points written (`≤ count`, capped by `out` capacity).
	 * `transform` rewrites each sample in place (given its jd) before the
	 * shift, for drawing the stored inertial samples in another frame.
	 */
	writeVertices(
		out: Float32Array,
		ox: number,
		oy: number,
		oz: number,
		transform?: (jd: number, v: Float64Array) => void
	): number {
		const n = Math.min(this._count, (out.length / 3) | 0);
		const v = transform ? new Float64Array(3) : null;
		for (let k = 0; k < n; k++) {
			const idx = (this.head - 1 - k + this.capacity) % this.capacity;
			const src = idx * 3;
			const dst = k * 3;
			if (transform && v) {
				v[0] = this.positions[src];
				v[1] = this.positions[src + 1];
				v[2] = this.positions[src + 2];
				transform(this.jds[idx], v);
				out[dst] = v[0] + ox;
				out[dst + 1] = v[1] + oy;
				out[dst + 2] = v[2] + oz;
				continue;
			}
			out[dst] = this.positions[src] + ox;
			out[dst + 1] = this.positions[src + 1] + oy;
			out[dst + 2] = this.positions[src + 2] + oz;
		}
		return n;
	}
}
