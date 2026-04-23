/**
 * Fixed-capacity ring buffer of past trail positions for a chebyshev-backed
 * body. Positions are stored in the body's orbital-centre-relative frame (same
 * frame as `ChebyshevStore.positionScene`), so rendering just adds the
 * current centre position at draw time.
 *
 * Capacity is a constant; `append` overwrites the oldest entry when full. The
 * buffer is agnostic to time speed — callers sample `positionScene` at jd
 * values spaced by `stepDays`, so the trail covers one orbital period once
 * full and keeps that time-coverage regardless of how fast sim time moves.
 */
export class TrailBuffer {
	readonly capacity: number;
	/** Target time between consecutive samples (days). */
	readonly stepDays: number;
	private readonly positions: Float32Array;
	private readonly jds: Float64Array;
	/** Index of the next write slot. `(head − 1) mod capacity` is the newest. */
	private head = 0;
	private _count = 0;

	constructor(capacity: number, stepDays: number) {
		this.capacity = capacity;
		this.stepDays = stepDays;
		this.positions = new Float32Array(capacity * 3);
		this.jds = new Float64Array(capacity);
	}

	get count(): number {
		return this._count;
	}

	/** JD of the most-recent sample, or NaN when empty. */
	get newestJd(): number {
		if (this._count === 0) return NaN;
		const idx = (this.head - 1 + this.capacity) % this.capacity;
		return this.jds[idx];
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
	 */
	writeVertices(out: Float32Array, ox: number, oy: number, oz: number): number {
		const n = Math.min(this._count, (out.length / 3) | 0);
		for (let k = 0; k < n; k++) {
			const idx = (this.head - 1 - k + this.capacity) % this.capacity;
			const src = idx * 3;
			const dst = k * 3;
			out[dst] = this.positions[src] + ox;
			out[dst + 1] = this.positions[src + 1] + oy;
			out[dst + 2] = this.positions[src + 2] + oz;
		}
		return n;
	}
}
