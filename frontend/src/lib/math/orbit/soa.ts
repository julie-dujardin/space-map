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
	/** 1 when i/om/w are in Earth-equatorial J2000 (TEME) instead of ecliptic. */
	equatorial: Uint8Array;
	a: Float64Array;
	e: Float64Array;
	i: Float64Array;
	om: Float64Array;
	w: Float64Array;
	ma: Float64Array;
	n: Float64Array;
	epoch: Float64Array;
	q: Float64Array;
	tp: Float64Array;
	/** Per-row SGP4 satrec — non-null iff kind[i] === KIND_SGP4. */
	satrec: (SatRec | null)[];
	/** SBDB bits per point (0 = NEO, 1 = PHA); zero on non-SBDB rows. */
	flags: Uint8Array;
	/** Whether `writePositions` honours the tick's `requiredFlags` mask. False
	 *  for groups whose flags are meaningless (Earth sats) so a global NEO/PHA
	 *  filter doesn't erase them. */
	applyFlagFilter: boolean;
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
 * main-thread callers can map back by index. `applyFlagFilter` opts the group
 * into the per-tick NEO/PHA mask (leave false for Earth sats / probes).
 */
export function packBodies(
	bodies: PositionedBody[],
	skip?: Set<string>,
	applyFlagFilter: boolean = false
): OrbitColumns {
	const count = bodies.length;
	const cols = allocColumns(count);
	cols.applyFlagFilter = applyFlagFilter;
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
		} else if (d.q != null && d.tp != null && isFinite(d.q) && isFinite(d.tp)) {
			cols.kind[idx] = KIND_PARABOLIC;
			cols.q[idx] = d.q;
			cols.tp[idx] = d.tp;
		} else if (d.a !== 0 && isFinite(d.a)) {
			cols.kind[idx] = KIND_KEPLER;
		} else {
			cols.kind[idx] = KIND_SKIP;
			continue;
		}
		cols.a[idx] = d.a;
		cols.e[idx] = d.e;
		cols.i[idx] = d.i;
		cols.om[idx] = d.om;
		cols.w[idx] = d.w;
		cols.ma[idx] = d.ma;
		cols.n[idx] = d.n;
		cols.epoch[idx] = d.epoch;
		cols.equatorial[idx] = d.equatorial ? 1 : 0;
		cols.flags[idx] = d.flags ?? 0;
		if (d.validityStart < start) start = d.validityStart;
		if (d.validityEnd > end) end = d.validityEnd;
	}
	cols.validityStart = start === Infinity ? -Infinity : start;
	cols.validityEnd = end === -Infinity ? Infinity : end;
	return cols;
}

/** Buffers of OrbitColumns as a transferable list. Used when posting to a worker. */
export function columnsTransferList(cols: OrbitColumns): Transferable[] {
	return [
		cols.kind.buffer,
		cols.equatorial.buffer,
		cols.a.buffer,
		cols.e.buffer,
		cols.i.buffer,
		cols.om.buffer,
		cols.w.buffer,
		cols.ma.buffer,
		cols.n.buffer,
		cols.epoch.buffer,
		cols.q.buffer,
		cols.tp.buffer,
		cols.flags.buffer
	] as Transferable[];
}

export function allocColumns(count: number): OrbitColumns {
	return {
		count,
		kind: new Uint8Array(count),
		equatorial: new Uint8Array(count),
		a: new Float64Array(count),
		e: new Float64Array(count),
		i: new Float64Array(count),
		om: new Float64Array(count),
		w: new Float64Array(count),
		ma: new Float64Array(count),
		n: new Float64Array(count),
		epoch: new Float64Array(count),
		q: new Float64Array(count),
		tp: new Float64Array(count),
		satrec: new Array<SatRec | null>(count).fill(null),
		flags: new Uint8Array(count),
		applyFlagFilter: false,
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
	out: Float32Array,
	requiredFlags: number = 0
): number {
	// Bail on the whole group when jd sits outside the chunk's validity window
	// — avoids a full SGP4 sweep that would error on every row and flood the
	// console. Returning 0 hides the cloud via setDrawRange.
	if (jd < cols.validityStart || jd > cols.validityEnd) return 0;
	const { count, kind, equatorial, a, e, i, om, w, ma, n, epoch, q, tp, satrec, flags } = cols;
	const filterActive = requiredFlags !== 0 && cols.applyFlagFilter;
	const capacity = (out.length / 3) | 0;
	let writeIdx = 0;

	for (let idx = 0; idx < count; idx++) {
		if (writeIdx >= capacity) break;
		const k = kind[idx];
		if (k === KIND_SKIP) continue;
		if (filterActive && (flags[idx] & requiredFlags) !== requiredFlags) continue;

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
		const ii = i[idx];
		const omi = om[idx];
		const wi = w[idx];

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

		// Inline orbitalToThreeJS — avoids tuple alloc in the hot loop.
		const cosW = Math.cos(wi * DEG2RAD);
		const sinW = Math.sin(wi * DEG2RAD);
		const cosI = Math.cos(ii * DEG2RAD);
		const sinI = Math.sin(ii * DEG2RAD);
		const cosOm = Math.cos(omi * DEG2RAD);
		const sinOm = Math.sin(omi * DEG2RAD);

		const x =
			(cosOm * cosW - sinOm * sinW * cosI) * xOrb + (-cosOm * sinW - sinOm * cosW * cosI) * yOrb;
		let y =
			(sinOm * cosW + cosOm * sinW * cosI) * xOrb + (-sinOm * sinW + cosOm * cosW * cosI) * yOrb;
		let z = sinW * sinI * xOrb + cosW * sinI * yOrb;

		if (equatorial[idx]) {
			// TLE elements are in Earth-equatorial J2000 (TEME); rotate about X by ε
			// to match the ecliptic frame everything else uses.
			const yEcl = y * COS_EPS + z * SIN_EPS;
			const zEcl = -y * SIN_EPS + z * COS_EPS;
			y = yEcl;
			z = zEcl;
		}

		// Three.js mapping: ecliptic X→X, Z→Y, Y→−Z. Matches orbitalToThreeJS.
		const sx = x * AU_SCALE;
		const sy = z * AU_SCALE;
		const sz = -y * AU_SCALE;

		out[writeIdx * 3] = parentX + sx - basisX;
		out[writeIdx * 3 + 1] = parentY + sy - basisY;
		out[writeIdx * 3 + 2] = parentZ + sz - basisZ;
		writeIdx++;
	}
	return writeIdx;
}
