/**
 * Repro harness for probe trail accuracy/cost under fast time playback.
 *
 * Drives the REAL buffer-maintenance code (`TrailBuffer`,
 * `deriveProbeTrailParams`, `backfillTrailFromSampler`, `extendProbeTrailBuffer`)
 * through the same per-frame branch `updatePositions` runs, against a Kepler
 * ground-truth trajectory (`orbitalElementsToPositionJD` — exactly what a
 * kepler-fit probe sub-chunk evaluates). Reports, per object and per app time
 * scale, how far the rendered polyline drifts from the true orbit and what it
 * costs (sampler evals/frame).
 *
 * Models the FOCUSED probe's path, which reseeds a full osculating period each
 * frame once `dt/frame > span` (see the `reseed` branch / eval spike for tight
 * orbits). Unfocused probes skip that reseed for a one-append fallback
 * (`updatePositions`), so the eval/frame column is the per-focused-probe cost.
 *
 * Not a pass/fail test — run with:
 *   npx vitest run src/lib/scene/objects/trail/trail-accuracy.repro.test.ts
 * and read the console table.
 */

import { describe, it } from 'vitest';
import type { OrbitalElements } from '$lib/types/objects';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { AU_KM, AU_SCALE } from '$lib/math/units';
import { TrailBuffer, ADAPTIVE_MIN_STEP_FACTOR } from '$lib/fetch/position/trail-buffer';
import {
	deriveProbeTrailParams,
	backfillTrailFromSampler,
	extendProbeTrailBuffer
} from '$lib/fetch/position/probes/trail';

type Vec3 = [number, number, number];
type Sampler = (t: number) => Vec3 | null;

/** Matches NUM_TRAIL_POINTS — the buffer capacity the real probe path uses. */
const CAP = 512;

const sceneToKm = (s: number) => (s / AU_SCALE) * AU_KM;
const dist = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

// Real app time scales (sim-seconds per real second); dt/frame at 60 fps.
const FPS = 60;
const TIME_SCALES: { label: string; simSecPerSec: number }[] = [
	{ label: 'hour/s', simSecPerSec: 3600 },
	{ label: 'day/s', simSecPerSec: 86400 },
	{ label: 'week/s', simSecPerSec: 604800 },
	{ label: 'month/s', simSecPerSec: 2_592_000 },
	{ label: 'year/s', simSecPerSec: 31_557_600 }
];

interface TestOrbit {
	label: string;
	/** Parent-relative semi-major axis in km, eccentricity, period in days. */
	aKm: number;
	e: number;
	periodDays: number;
	/** Rough body/scene radius (km) errors are judged visible against. */
	bodyRadiusKm: number;
}

// Representative captured orbits spanning tight-fast to wide-slow. Angles are
// arbitrary — only the geometry (a, e, period) drives sampling error.
const ORBITS: TestOrbit[] = [
	{ label: 'MRO @ Mars', aKm: 3631, e: 0.006, periodDays: 0.0778, bodyRadiusKm: 3389 },
	{ label: 'LRO @ Moon', aKm: 1837, e: 0.0013, periodDays: 0.0805, bodyRadiusKm: 1737 },
	{ label: 'ISS-ish @ Earth', aKm: 6778, e: 0.0007, periodDays: 0.0645, bodyRadiusKm: 6371 },
	{ label: 'Cassini @ Saturn', aKm: 200_000, e: 0.7, periodDays: 7, bodyRadiusKm: 58_232 },
	{ label: 'Juno @ Jupiter', aKm: 4_000_000, e: 0.95, periodDays: 53, bodyRadiusKm: 69_911 }
];

function makeElements(o: TestOrbit): OrbitalElements {
	return {
		a: o.aKm / AU_KM,
		e: o.e,
		i: 63,
		om: 40,
		w: 110,
		ma: 0,
		n: 360 / o.periodDays,
		epoch: 2460000.5,
		equatorial: false
	};
}

/** Ground-truth parent-relative scene position at t. */
function truthSampler(el: OrbitalElements): Sampler {
	return (t) => orbitalElementsToPositionJD(el, t);
}

/** Sampler that counts evaluations (perf proxy). */
function counting(s: Sampler): { sample: Sampler; count: () => number } {
	let n = 0;
	return {
		sample: (t) => {
			n++;
			return s(t);
		},
		count: () => n
	};
}

/**
 * One frame of the exact maintenance branch from update-positions.ts. Returns
 * the branch taken. Elements are stable here, so param re-derivation on reseed
 * is a no-op (we keep the buffer's configured values).
 */
function maintainFrame(
	buf: TrailBuffer,
	sample: Sampler,
	jd: number
): 'reseed' | 'extend' | 'append' | 'seed' | 'skip' {
	const last = buf.newestJd;
	const dt = jd - last;
	const span = buf.stepDays * buf.capacity;
	if (isFinite(last) && (dt < 0 || dt > span)) {
		buf.clear();
		backfillTrailFromSampler(buf, sample, jd);
		return 'reseed';
	} else if (!isFinite(last)) {
		const p = sample(jd);
		if (p) buf.append(jd, p[0], p[1], p[2]);
		return 'seed';
	} else if (isFinite(buf.epsilonScene)) {
		const minStep = buf.stepDays * ADAPTIVE_MIN_STEP_FACTOR;
		const scratch: Vec3 = [0, 0, 0];
		if (dt >= minStep && buf.readNewestPos(scratch)) {
			extendProbeTrailBuffer(buf, sample, last, [scratch[0], scratch[1], scratch[2]], jd);
			return 'extend';
		}
		return 'skip';
	} else if (dt >= buf.stepDays) {
		const p = sample(jd);
		if (p) buf.append(jd, p[0], p[1], p[2]);
		return 'append';
	}
	return 'skip';
}

/**
 * Rendered polyline = live head at the true current position, then buffer
 * samples newest→oldest (mirrors writeBufferVerticesWithLiveHead). Returns the
 * vertices and their jds (live head jd = current frame jd).
 */
function renderPolyline(buf: TrailBuffer, truth: Sampler, jd: number): Vec3[] {
	const out = new Float32Array((buf.capacity + 1) * 3);
	const n = buf.writeVertices(out.subarray(3) as Float32Array, 0, 0, 0);
	const verts: Vec3[] = [truth(jd)!];
	for (let k = 0; k < n; k++) {
		verts.push([out[3 + k * 3], out[3 + k * 3 + 1], out[3 + k * 3 + 2]]);
	}
	return verts;
}

/**
 * Max facet (chord) error of the rendered polyline vs the true orbit, plus the
 * first-facet length (live head → newest sample = the "spike"). Because we lack
 * per-vertex jds from the buffer, we measure each segment's deviation by its
 * arc: find the true-orbit point nearest each segment midpoint via a dense
 * scan, then the perpendicular gap. Reported in km.
 */
function polylineError(verts: Vec3[], truthDense: Vec3[]): { maxChordKm: number; spikeKm: number } {
	let maxChord = 0;
	// Only the near-body portion is visible when focused; the apoapsis tail of a
	// highly eccentric orbit is off-screen. Cap the scan for cost and relevance.
	const scanTo = Math.min(verts.length - 1, 48);
	for (let i = 0; i < scanTo; i++) {
		const a = verts[i];
		const b = verts[i + 1];
		const mid: Vec3 = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
		// Nearest true-orbit point to the segment midpoint.
		let best = Infinity;
		for (const p of truthDense) {
			const d = dist(mid, p);
			if (d < best) best = d;
		}
		if (best > maxChord) maxChord = best;
	}
	const spike = verts.length > 1 ? dist(verts[0], verts[1]) : 0;
	return { maxChordKm: sceneToKm(maxChord), spikeKm: sceneToKm(spike) };
}

function denseTruth(el: OrbitalElements, jd0: number, periodDays: number): Vec3[] {
	const pts: Vec3[] = [];
	const N = 2000;
	for (let k = 0; k < N; k++) {
		const t = jd0 - periodDays + (periodDays * 2 * k) / N;
		const p = orbitalElementsToPositionJD(el, t);
		if (p) pts.push(p);
	}
	return pts;
}

describe('probe trail accuracy under fast playback (report only)', () => {
	it('sweeps orbits × time scales', { timeout: 120_000 }, () => {
		const rows: string[] = [];
		rows.push(
			[
				'object'.padEnd(18),
				'period_d'.padStart(9),
				'scale'.padStart(8),
				'dt/frame_d'.padStart(11),
				'branch'.padStart(7),
				'samples'.padStart(8),
				'spike_km'.padStart(11),
				'maxChord_km'.padStart(12),
				'chord/rBody'.padStart(11),
				'eval/frame'.padStart(11)
			].join(' ')
		);

		for (const o of ORBITS) {
			const el = makeElements(o);
			const truth = truthSampler(el);
			const jd0 = el.epoch;
			const dense = denseTruth(el, jd0, o.periodDays);

			for (const ts of TIME_SCALES) {
				const dtFrame = ts.simSecPerSec / 86400 / FPS; // days per frame
				const params = deriveProbeTrailParams(el, o.periodDays, CAP);
				const buf = new TrailBuffer(CAP, params.stepDays, params.epsilonScene, params.spanDays);
				// Cold start: initial back-fill at jd0.
				backfillTrailFromSampler(buf, truth, jd0);

				let jd = jd0;
				let maxSpike = 0;
				let maxChord = 0;
				let branch = 'skip';
				let evalTotal = 0;
				const FRAMES = 80;
				for (let f = 0; f < FRAMES; f++) {
					jd += dtFrame;
					const c = counting(truth);
					branch = maintainFrame(buf, c.sample, jd);
					evalTotal += c.count();
					const verts = renderPolyline(buf, truth, jd);
					const err = polylineError(verts, dense);
					if (err.spikeKm > maxSpike) maxSpike = err.spikeKm;
					if (err.maxChordKm > maxChord) maxChord = err.maxChordKm;
				}
				rows.push(
					[
						o.label.padEnd(18),
						o.periodDays.toFixed(3).padStart(9),
						ts.label.padStart(8),
						dtFrame.toFixed(4).padStart(11),
						branch.padStart(7),
						String(buf.count).padStart(8),
						maxSpike.toFixed(1).padStart(11),
						maxChord.toFixed(1).padStart(12),
						(maxChord / o.bodyRadiusKm).toFixed(3).padStart(11),
						(evalTotal / FRAMES).toFixed(0).padStart(11)
					].join(' ')
				);
			}
			rows.push('');
		}

		console.log('\n' + rows.join('\n') + '\n');
	});
});
