import { solveKepler, solveKeplerHyperbolic, solveBarker } from './solvers';
import { AU_SCALE, AU_KM, EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import type { PositionedBody } from '$lib/types/objects';
import { sgp4, SatRecError, type SatRec } from 'satellite.js';

const DEG2RAD = Math.PI / 180;
const COS_EPS = Math.cos(EARTH_OBLIQUITY_DEG * DEG2RAD);
const SIN_EPS = Math.sin(EARTH_OBLIQUITY_DEG * DEG2RAD);
/** Precomputed km -> scene-unit scale. */
const KM_TO_SCENE = AU_SCALE / AU_KM;

export const KIND_SKIP = 0;
export const KIND_KEPLER = 1;
export const KIND_PARABOLIC = 2;
export const KIND_SGP4 = 3;

/**
 * SoA view of one point-cloud group, packed for a worker to solve in a tight loop.
 *
 * `kind[i]` selects the solver per body:
 *   0 = skip (promoted, a≈0 degenerate, etc.)
 *   1 = Keplerian: uses a, e, i, om, w, ma, n, epoch
 *   2 = Parabolic: uses e, i, om, w, epoch, q, tp
 *   3 = SGP4: uses satrec[i] (plain JS array, structured-cloned across the
 *       worker boundary since SatRec is pure data and not transferable)
 *
 * Arrays are length `count`. Use Float64 throughout — preserves precision for TNO
 * epochs and near-parabolic eccentricities; output positions are the only Float32.
 */
export interface OrbitColumns {
	count: number;
	kind: Uint8Array;
	a: Float64Array;
	e: Float64Array;
	ma: Float64Array;
	n: Float64Array;
	epoch: Float64Array;
	q: Float64Array;
	tp: Float64Array;
	/**
	 * Precomputed (xOrb, yOrb) → (sx, sy, sz) rotation matrix per body, in
	 * scene units. Folds in the i/om/w rotation, the equatorial→ecliptic
	 * rotation (when applicable), the ecliptic→Three.js axis swap, and the
	 * AU_SCALE multiplier. Computed once at pack time so the inner tick loop
	 * is just 6 multiplications and 4 additions per body — saves 6 trig calls
	 * × ~250k bodies × 60 fps = ~90M trig/sec across the worker pool.
	 */
	m00: Float32Array;
	m01: Float32Array;
	m10: Float32Array;
	m11: Float32Array;
	m20: Float32Array;
	m21: Float32Array;
	/** Per-row SGP4 satrec — non-null iff kind[i] === KIND_SGP4. */
	satrec: (SatRec | null)[];
	/**
	 * Group-level validity window (JD TDB). Written once at pack time from the
	 * widest span across bodies — bodies in a pool group always come from one
	 * zone export so in practice they share a single chunk window. `writePositions`
	 * early-exits (returning 0) when the tick's jd falls outside this range,
	 * avoiding a futile SGP4 loop that would spam propagation warnings.
	 */
	validityStart: number;
	validityEnd: number;
}

/**
 * Pack AoS PositionedBody list into SoA columns for worker consumption.
 * Bodies whose IDs are in `skip` (e.g. promoted to full meshes) are tagged
 * KIND_SKIP. Degenerate Keplerian entries (a=0 with no q/tp) are also skipped.
 * Returns columns sized to bodies.length; order matches `bodies` exactly so
 * main-thread callers can map back by index.
 */
export function packBodies(bodies: PositionedBody[], skip?: Set<string>): OrbitColumns {
	const count = bodies.length;
	const cols = allocColumns(count);
	// Widen the group's validity window to the union of all bodies' windows.
	// In practice all bodies in one pool group share a single chunk window, so
	// min/max collapses to that shared value — but the widening keeps us safe
	// if a caller ever mixes chunks with differing windows into one group.
	let start = Infinity;
	let end = -Infinity;
	for (let idx = 0; idx < count; idx++) {
		const b = bodies[idx];
		const d = b.data;
		if (skip?.has(d.id)) {
			cols.kind[idx] = KIND_SKIP;
			continue;
		}
		if (d.satrec) {
			cols.kind[idx] = KIND_SGP4;
			cols.satrec[idx] = d.satrec;
			// SGP4 path computes its own scene-frame rotation from the satrec
			// output; the precomputed orientation matrix below isn't used for
			// these bodies.
		} else if (d.q != null && d.tp != null && isFinite(d.q) && isFinite(d.tp)) {
			cols.kind[idx] = KIND_PARABOLIC;
			cols.q[idx] = d.q;
			cols.tp[idx] = d.tp;
			writeOrientationMatrix(cols, idx, d.i, d.om, d.w, d.equatorial === true);
		} else if (d.a !== 0 && isFinite(d.a)) {
			cols.kind[idx] = KIND_KEPLER;
			writeOrientationMatrix(cols, idx, d.i, d.om, d.w, d.equatorial === true);
		} else {
			cols.kind[idx] = KIND_SKIP;
			continue;
		}
		cols.a[idx] = d.a;
		cols.e[idx] = d.e;
		cols.ma[idx] = d.ma;
		cols.n[idx] = d.n;
		cols.epoch[idx] = d.epoch;
		if (d.validityStart < start) start = d.validityStart;
		if (d.validityEnd > end) end = d.validityEnd;
	}
	cols.validityStart = start === Infinity ? -Infinity : start;
	cols.validityEnd = end === -Infinity ? Infinity : end;
	return cols;
}

/**
 * Compose the orbital-element rotation (Ω-i-ω), optional equatorial→ecliptic
 * step, ecliptic→Three.js axis swap, and AU_SCALE factor into a 3×2 matrix
 * that maps (x_orbit, y_orbit) → (sx, sy, sz) scene units. Written into
 * `cols` at row `idx`.
 */
function writeOrientationMatrix(
	cols: OrbitColumns,
	idx: number,
	iDeg: number,
	omDeg: number,
	wDeg: number,
	equatorial: boolean
): void {
	const cosW = Math.cos(wDeg * DEG2RAD);
	const sinW = Math.sin(wDeg * DEG2RAD);
	const cosI = Math.cos(iDeg * DEG2RAD);
	const sinI = Math.sin(iDeg * DEG2RAD);
	const cosOm = Math.cos(omDeg * DEG2RAD);
	const sinOm = Math.sin(omDeg * DEG2RAD);

	// Orbital plane → ecliptic (or TEME if `equatorial`).
	const a = cosOm * cosW - sinOm * sinW * cosI;
	const b = -cosOm * sinW - sinOm * cosW * cosI;
	const c = sinOm * cosW + cosOm * sinW * cosI;
	const dd = -sinOm * sinW + cosOm * cosW * cosI;
	const e = sinW * sinI;
	const f = cosW * sinI;

	cols.m00[idx] = a * AU_SCALE;
	cols.m01[idx] = b * AU_SCALE;
	if (equatorial) {
		// Rotate (y, z) about scene-X by ε, then apply the Three.js axis swap
		// (sy = z_ecl, sz = -y_ecl). Combined coefficients per row below.
		cols.m10[idx] = (-c * SIN_EPS + e * COS_EPS) * AU_SCALE;
		cols.m11[idx] = (-dd * SIN_EPS + f * COS_EPS) * AU_SCALE;
		cols.m20[idx] = -(c * COS_EPS + e * SIN_EPS) * AU_SCALE;
		cols.m21[idx] = -(dd * COS_EPS + f * SIN_EPS) * AU_SCALE;
	} else {
		cols.m10[idx] = e * AU_SCALE;
		cols.m11[idx] = f * AU_SCALE;
		cols.m20[idx] = -c * AU_SCALE;
		cols.m21[idx] = -dd * AU_SCALE;
	}
}

/** Buffers of OrbitColumns as a transferable list. Used when posting to a worker. */
export function columnsTransferList(cols: OrbitColumns): Transferable[] {
	return [
		cols.kind.buffer,
		cols.a.buffer,
		cols.e.buffer,
		cols.ma.buffer,
		cols.n.buffer,
		cols.epoch.buffer,
		cols.q.buffer,
		cols.tp.buffer,
		cols.m00.buffer,
		cols.m01.buffer,
		cols.m10.buffer,
		cols.m11.buffer,
		cols.m20.buffer,
		cols.m21.buffer
	] as Transferable[];
}

export function allocColumns(count: number): OrbitColumns {
	return {
		count,
		kind: new Uint8Array(count),
		a: new Float64Array(count),
		e: new Float64Array(count),
		ma: new Float64Array(count),
		n: new Float64Array(count),
		epoch: new Float64Array(count),
		q: new Float64Array(count),
		tp: new Float64Array(count),
		m00: new Float32Array(count),
		m01: new Float32Array(count),
		m10: new Float32Array(count),
		m11: new Float32Array(count),
		m20: new Float32Array(count),
		m21: new Float32Array(count),
		satrec: new Array<SatRec | null>(count).fill(null),
		validityStart: -Infinity,
		validityEnd: Infinity
	};
}

/**
 * Write basis-relative Float32 positions for every body in `cols` into `out`.
 * Positions are computed as (parent + offset − basis), all in AU_SCALE scene units.
 * Output layout: `[x0, y0, z0, x1, y1, z1, ...]`. Skipped bodies and bodies with
 * non-finite offsets get (NaN, NaN, NaN) — caller should track `writtenCount`
 * and use `setDrawRange` rather than relying on the raw buffer length.
 *
 * Returns the number of valid (non-skipped, finite) bodies written to contiguous
 * slots at the *start* of `out`. This mirrors the current
 * {@link writeMinorPointCloud} behaviour where skipped bodies don't occupy a
 * slot — later bodies slide down — and callers use setDrawRange to render only
 * the packed prefix.
 */
export function writePositions(
	cols: OrbitColumns,
	jd: number,
	parentX: number,
	parentY: number,
	parentZ: number,
	basisX: number,
	basisY: number,
	basisZ: number,
	out: Float32Array
): number {
	// Bail on the whole group when jd sits outside the chunk's validity window
	// — avoids a full SGP4 sweep that would error on every row and flood the
	// console. Returning 0 hides the cloud via setDrawRange.
	if (jd < cols.validityStart || jd > cols.validityEnd) return 0;
	const { count, kind, a, e, ma, n, epoch, q, tp, m00, m01, m10, m11, m20, m21, satrec } = cols;
	const capacity = (out.length / 3) | 0;
	let writeIdx = 0;

	for (let idx = 0; idx < count; idx++) {
		if (writeIdx >= capacity) break;
		const k = kind[idx];
		if (k === KIND_SKIP) continue;

		if (k === KIND_SGP4) {
			const sat = satrec[idx];
			if (!sat) continue;
			const tsince = (jd - sat.jdsatepoch) * 1440;
			const result = sgp4(sat, tsince);
			if (!result || sat.error !== SatRecError.None) continue;
			const xk = result.position.x;
			const yk = result.position.y;
			const zk = result.position.z;
			// km -> scene units, then TEME -> ecliptic rotation about X, then
			// ecliptic -> Three.js basis swap (see position.ts for reference).
			const xs = xk * KM_TO_SCENE;
			const yk_s = yk * KM_TO_SCENE;
			const zk_s = zk * KM_TO_SCENE;
			const yEcl = yk_s * COS_EPS + zk_s * SIN_EPS;
			const zEcl = -yk_s * SIN_EPS + zk_s * COS_EPS;
			const sx = xs;
			const sy = zEcl;
			const sz = -yEcl;
			if (!isFinite(sx) || !isFinite(sy) || !isFinite(sz)) continue;
			out[writeIdx * 3] = parentX + sx - basisX;
			out[writeIdx * 3 + 1] = parentY + sy - basisY;
			out[writeIdx * 3 + 2] = parentZ + sz - basisZ;
			writeIdx++;
			continue;
		}

		let xOrb: number, yOrb: number;
		const ei = e[idx];

		if (k === KIND_PARABOLIC) {
			const result = solveBarker(q[idx], tp[idx], jd);
			if (!result) continue;
			xOrb = result.r * Math.cos(result.nu);
			yOrb = result.r * Math.sin(result.nu);
		} else {
			// Keplerian (elliptic or hyperbolic)
			const ai = a[idx];
			if (!isFinite(ai) || !isFinite(ei) || !isFinite(ma[idx]) || !isFinite(n[idx])) continue;
			const dt = jd - epoch[idx];
			const M = (ma[idx] + n[idx] * dt) * DEG2RAD;

			let nu: number, r: number;
			if (ei < 1 || ai > 0) {
				const eClamped = Math.min(ei, 1 - 1e-7);
				const E = solveKepler(M, eClamped);
				const sinNu =
					(Math.sqrt(1 - eClamped * eClamped) * Math.sin(E)) / (1 - eClamped * Math.cos(E));
				const cosNu = (Math.cos(E) - eClamped) / (1 - eClamped * Math.cos(E));
				nu = Math.atan2(sinNu, cosNu);
				r = ai * (1 - eClamped * Math.cos(E));
			} else {
				const H = solveKeplerHyperbolic(M, ei);
				if (!isFinite(H)) continue;
				const denom = ei * Math.cosh(H) - 1;
				if (Math.abs(denom) < 1e-15) continue;
				const sinNu = (Math.sqrt(ei * ei - 1) * Math.sinh(H)) / denom;
				const cosNu = (ei - Math.cosh(H)) / denom;
				nu = Math.atan2(sinNu, cosNu);
				r = ai * (1 - ei * Math.cosh(H));
			}
			xOrb = r * Math.cos(nu);
			yOrb = r * Math.sin(nu);
		}

		if (!isFinite(xOrb) || !isFinite(yOrb)) continue;

		// Apply the precomputed orientation matrix (folds i/om/w rotation,
		// equatorial→ecliptic if applicable, axis swap, and AU_SCALE).
		const sx = m00[idx] * xOrb + m01[idx] * yOrb;
		const sy = m10[idx] * xOrb + m11[idx] * yOrb;
		const sz = m20[idx] * xOrb + m21[idx] * yOrb;

		out[writeIdx * 3] = parentX + sx - basisX;
		out[writeIdx * 3 + 1] = parentY + sy - basisY;
		out[writeIdx * 3 + 2] = parentZ + sz - basisZ;
		writeIdx++;
	}
	return writeIdx;
}
