/**
 * Per-probe attitude: decoded keyframe stream + optional spin baseline, with a
 * per-frame evaluator returning a scene-frame body→world quaternion. Loaded
 * lazily on focus (see `loadBodyModel`); only the focused probe holds a track.
 *
 * Stored quaternions are `pxform("J2000", frame)` (J2000→body), so eval
 * conjugates for body→world, then rotates into the scene frame via `EQ_TO_SCENE`.
 */

import { Matrix4, Quaternion, Vector3 } from 'three';
import { DATA_BASE } from '$lib/fetch/data-base';
import type { ProbeAttitude } from '$lib/fetch/objects/object-data';
import { parseAttitudeChunk, type AttitudeChunk } from './parse';

const SECONDS_PER_DAY = 86400;
const DEG2RAD = Math.PI / 180;
const OBLIQUITY_RAD = 23.4392911 * DEG2RAD;
const COS_OBL = Math.cos(OBLIQUITY_RAD);
const SIN_OBL = Math.sin(OBLIQUITY_RAD);

/** Equatorial-J2000 → scene rotation; basis columns are the scene images of the
 *  eq axes, matching `equatorialToThreeJS` in `$lib/math/orientation`. */
const EQ_TO_SCENE = new Quaternion().setFromRotationMatrix(
	new Matrix4().makeBasis(
		new Vector3(1, 0, 0),
		new Vector3(0, -SIN_OBL, -COS_OBL),
		new Vector3(0, COS_OBL, -SIN_OBL)
	)
);

// Per-frame scratch — the evaluator runs once per focused probe per frame.
const _qa = new Quaternion();
const _qb = new Quaternion();
const _qBaseline = new Quaternion();
const _baselineAxis = new Vector3();

/** Load a flat `[w,x,y,z]` keyframe at index `i` into `out` (three.js xyzw). */
function loadQuat(quats: Float32Array, i: number, out: Quaternion): Quaternion {
	const b = i * 4;
	return out.set(quats[b + 1], quats[b + 2], quats[b + 3], quats[b]);
}

export class AttitudeTrack {
	private readonly times: Float64Array;
	private readonly quats: Float32Array;
	private readonly startJd: number;
	private readonly endJd: number;
	private readonly baseline: ProbeAttitude['baseline'];

	constructor(manifest: ProbeAttitude, chunks: AttitudeChunk[]) {
		this.startJd = manifest.start_jd;
		this.endJd = manifest.end_jd;
		this.baseline = manifest.baseline;
		// Time-ascending, non-overlapping; flatten for one binary search at eval.
		const total = chunks.reduce((n, c) => n + c.times.length, 0);
		this.times = new Float64Array(total);
		this.quats = new Float32Array(total * 4);
		let o = 0;
		for (const c of chunks) {
			this.times.set(c.times, o);
			this.quats.set(c.quats, o * 4);
			o += c.times.length;
		}
	}

	/** True when `jd` is inside the track's coverage window. */
	covers(jd: number): boolean {
		return jd >= this.startJd && jd <= this.endJd && this.times.length > 0;
	}

	/**
	 * Write the scene-frame body→world orientation at `jd` into `out`. Returns
	 * false when `jd` is outside coverage (caller falls back to pointing/nadir).
	 */
	orientationAt(jd: number, out: Quaternion): boolean {
		if (!this.covers(jd)) return false;
		const { times, quats } = this;

		// Bracket jd; clamp at the endpoints (rounded bounds can sit just outside).
		const n = times.length;
		let lo = 0;
		let hi = n - 1;
		if (jd <= times[0]) {
			loadQuat(quats, 0, _qa);
		} else if (jd >= times[n - 1]) {
			loadQuat(quats, n - 1, _qa);
		} else {
			while (hi - lo > 1) {
				const mid = (lo + hi) >> 1;
				if (times[mid] <= jd) lo = mid;
				else hi = mid;
			}
			const span = times[hi] - times[lo];
			const t = span > 0 ? (jd - times[lo]) / span : 0;
			loadQuat(quats, lo, _qa);
			loadQuat(quats, hi, _qb);
			// Handles antipodal pairs — smallest-three can flip sign between keyframes.
			_qa.slerpQuaternions(_qa, _qb, t);
		}

		// Recompose spin baseline: q_full = baseline(t)·anchor·residual, t since start.
		if (this.baseline) {
			const { axis, rate_rad_s, anchor } = this.baseline;
			const tSeconds = (jd - this.startJd) * SECONDS_PER_DAY;
			_baselineAxis.set(axis[0], axis[1], axis[2]);
			_qBaseline.setFromAxisAngle(_baselineAxis, rate_rad_s * tSeconds);
			_qb.set(anchor[1], anchor[2], anchor[3], anchor[0]);
			_qBaseline.multiply(_qb);
			_qa.copy(_qBaseline.multiply(_qa));
		}

		// J2000→body; invert for body→world, then rotate into scene.
		_qa.conjugate();
		out.copy(EQ_TO_SCENE).multiply(_qa);
		return true;
	}
}

/** Fetch + decode a probe's attitude chunks into a track. `probeId` is the bare
 *  id (no `probe-` prefix) = the export directory. Attitude isn't
 *  content-versioned, so fetch straight off `DATA_BASE` (no `?v=`). */
export async function fetchAttitudeTrack(
	probeId: string,
	manifest: ProbeAttitude
): Promise<AttitudeTrack> {
	const chunks = await Promise.all(
		manifest.files.map(async (f) => {
			const res = await fetch(`${DATA_BASE}/v1/attitude/${probeId}/${f.name}`);
			if (!res.ok) {
				throw new Error(`attitude: ${probeId}/${f.name} returned ${res.status}`);
			}
			const ds = new DecompressionStream('gzip');
			const buf = await new Response(res.body!.pipeThrough(ds)).arrayBuffer();
			return parseAttitudeChunk(buf);
		})
	);
	return new AttitudeTrack(manifest, chunks);
}
