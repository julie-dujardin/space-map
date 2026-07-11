/**
 * Per-probe attitude: a lazily chunk-loaded keyframe stream + optional spin
 * baseline, evaluated per frame to a scene-frame body→world quaternion.
 * Coverage spans years, so chunks fetch on demand — only the one under the
 * playhead is resident. Created on focus; only the focused probe holds a track.
 *
 * Stored quaternions are `pxform("J2000", frame)` (J2000→body), so eval
 * conjugates for body→world, then rotates into the scene via `EQ_TO_SCENE`.
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
	private readonly startJd: number;
	private readonly endJd: number;
	private readonly baselines: ProbeAttitude['baselines'];
	private readonly files: ProbeAttitude['files'];
	private readonly chunks = new Map<number, AttitudeChunk>();
	private readonly inflight = new Set<number>();
	private readonly failed = new Set<number>();

	constructor(
		private readonly probeId: string,
		manifest: ProbeAttitude
	) {
		// Derive coverage from the chunk files, not manifest start/end_jd — those
		// echo CK-claimed windows, which can start years before the first real
		// keyframe (Spitzer claims 2000, first keyframe 2005). Trusting them
		// freeze-clamps the model where the pointing fallback should take over.
		this.startJd = manifest.files.length ? manifest.files[0].start_jd : 0;
		this.endJd = manifest.files.length ? manifest.files[manifest.files.length - 1].end_jd : 0;
		this.baselines = manifest.baselines;
		this.files = manifest.files;
	}

	/** True when `jd` is inside the track's keyframe coverage. */
	covers(jd: number): boolean {
		return jd >= this.startJd && jd <= this.endJd && this.files.length > 0;
	}

	/**
	 * Write the scene-frame body→world orientation at `jd` into `out`. Returns
	 * false when `jd` is outside coverage or its chunk isn't resident yet (the
	 * fetch is kicked off; caller falls back to pointing/nadir until it lands).
	 */
	orientationAt(jd: number, out: Quaternion): boolean {
		if (!this.covers(jd)) return false;
		const ci = this.fileIndexFor(jd);
		const chunk = this.ensure(ci);
		if (!chunk) return false;
		// Warm neighbours so scrubbing across a chunk edge doesn't stall.
		this.ensure(ci - 1);
		this.ensure(ci + 1);

		this.sampleChunk(jd, ci, chunk);

		// Recompose this chunk's spin baseline (if any): q_full =
		// spin(rate·(t−anchor_jd))·anchor·residual. A spinner that changes rate
		// across phases carries one baseline per phase; the chunk's
		// baseline_index picks the span active here.
		const baseline = this.baselines?.[this.files[ci].baseline_index ?? 0];
		if (baseline) {
			const { axis, rate_rad_s, anchor, anchor_jd } = baseline;
			const tSeconds = (jd - anchor_jd) * SECONDS_PER_DAY;
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

	/** Index of the last file whose window starts at or before `jd` (clamped). */
	private fileIndexFor(jd: number): number {
		const files = this.files;
		if (jd <= files[0].start_jd) return 0;
		let lo = 0;
		let hi = files.length - 1;
		while (hi - lo > 1) {
			const mid = (lo + hi) >> 1;
			if (files[mid].start_jd <= jd) lo = mid;
			else hi = mid;
		}
		return files[hi].start_jd <= jd ? hi : lo;
	}

	/** SLERP the keyframe quaternion at `jd` into `_qa`, bridging to the next
	 *  chunk's leading keyframe across a chunk boundary when it's resident. */
	private sampleChunk(jd: number, ci: number, chunk: AttitudeChunk): void {
		const { times, quats } = chunk;
		const n = times.length;
		if (jd <= times[0]) {
			loadQuat(quats, 0, _qa);
			return;
		}
		if (jd >= times[n - 1]) {
			const next = this.chunks.get(ci + 1);
			// Only bridge within a baseline span — residuals in different spin
			// frames aren't SLERP-compatible. At a span boundary both spans carry
			// the boundary attitude, so clamping here recomposes correctly.
			const sameSpan = this.files[ci + 1]?.baseline_index === this.files[ci].baseline_index;
			if (sameSpan && next && next.times.length > 0 && next.times[0] > times[n - 1]) {
				const span = next.times[0] - times[n - 1];
				const t = Math.min(1, (jd - times[n - 1]) / span);
				loadQuat(quats, n - 1, _qa);
				loadQuat(next.quats, 0, _qb);
				_qa.slerpQuaternions(_qa, _qb, t);
			} else {
				loadQuat(quats, n - 1, _qa); // clamp until the next chunk arrives
			}
			return;
		}
		let lo = 0;
		let hi = n - 1;
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

	/** Decoded chunk `i` if resident; otherwise kick off its fetch (once) and
	 *  return undefined so the caller falls back this frame. */
	private ensure(i: number): AttitudeChunk | undefined {
		if (i < 0 || i >= this.files.length) return undefined;
		const have = this.chunks.get(i);
		if (have) return have;
		if (this.inflight.has(i) || this.failed.has(i)) return undefined;
		this.inflight.add(i);
		void this.load(i);
		return undefined;
	}

	private async load(i: number): Promise<void> {
		const file = this.files[i];
		try {
			const res = await fetch(`${DATA_BASE}/v1/attitude/${this.probeId}/${file.name}`);
			if (!res.ok) throw new Error(`${res.status}`);
			const ds = new DecompressionStream('gzip');
			const buf = await new Response(res.body!.pipeThrough(ds)).arrayBuffer();
			this.chunks.set(i, parseAttitudeChunk(buf));
		} catch (e) {
			this.failed.add(i);
			console.warn(`attitude: chunk ${this.probeId}/${file.name} failed to load:`, e);
		} finally {
			this.inflight.delete(i);
		}
	}
}

/** Build a lazily chunk-loaded attitude track. No network here — chunks fetch
 *  on demand as `orientationAt` reaches them. `probeId` is the bare id (no
 *  `probe-` prefix) = the export directory. */
export function createAttitudeTrack(probeId: string, manifest: ProbeAttitude): AttitudeTrack {
	return new AttitudeTrack(probeId, manifest);
}
