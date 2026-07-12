import { describe, it, expect } from 'vitest';
import { Vector3 } from 'three';
import {
	setSphereOccluder,
	setEllipsoidOccluder,
	ellipsoidAnchorOffset,
	type EllipsoidAxes
} from './ellipsoid';
import { isScreenOccluded, type ScreenOccluder } from '../label/culling';

const F = 800; // projScale (px)
const HW = 640;
const HH = 360;

function emptyOcc(): ScreenOccluder {
	return {
		cx0: 0,
		cy0: 0,
		f: 0,
		gxx: 0,
		gxy: 0,
		gxz: 0,
		gyx: 0,
		gyy: 0,
		gyz: 0,
		gzx: 0,
		gzy: 0,
		gzz: 0,
		cpx: 0,
		cpy: 0,
		cpz: 0,
		K: 0,
		id: '',
		dist: 0,
		ccx: 0,
		ccy: 0,
		ccz: 0
	};
}

// Camera at origin looking −z. Screen point of a camera-space point.
function screenOf(x: number, y: number, z: number): [number, number] {
	const m = -z;
	return [HW + (F * x) / m, HH - (F * y) / m];
}

// Ground truth: does the ray toward screen (sx,sy) hit the ellipsoid?
function rayHits(
	c: [number, number, number],
	e: [Vector3, Vector3, Vector3],
	a: [number, number, number],
	sx: number,
	sy: number
): boolean {
	const d = [sx - HW, HH - sy, -F];
	const dotE = (v: number[], k: number) => v[0] * e[k].x + v[1] * e[k].y + v[2] * e[k].z;
	const cp = [dotE(c, 0) / a[0], dotE(c, 1) / a[1], dotE(c, 2) / a[2]];
	const dp = [dotE(d, 0) / a[0], dotE(d, 1) / a[1], dotE(d, 2) / a[2]];
	const dd = dp[0] * dp[0] + dp[1] * dp[1] + dp[2] * dp[2];
	const t = (dp[0] * cp[0] + dp[1] * cp[1] + dp[2] * cp[2]) / dd;
	if (t <= 0) return false;
	const px = t * dp[0] - cp[0];
	const py = t * dp[1] - cp[1];
	const pz = t * dp[2] - cp[2];
	return Math.hypot(px, py, pz) <= 1;
}

describe('ellipsoid occlusion cone test', () => {
	it('matches sphere ray-hit truth over random rays', () => {
		const e: [Vector3, Vector3, Vector3] = [
			new Vector3(1, 0, 0),
			new Vector3(0, 1, 0),
			new Vector3(0, 0, 1)
		];
		const r = 0.8;
		const c: [number, number, number] = [0.5, -0.3, -4];
		const occ = emptyOcc();
		setSphereOccluder(occ, c[0], c[1], c[2], r, F, HW, HH, 'b', Math.hypot(...c));
		for (let i = 0; i < 2000; i++) {
			const sx = HW + (Math.random() * 2 - 1) * 400;
			const sy = HH + (Math.random() * 2 - 1) * 400;
			const truth = rayHits(c, e, [r, r, r], sx, sy);
			const test = isScreenOccluded(sx, sy, 1e9, 'x', [occ]);
			expect(test).toBe(truth);
		}
	});

	it('matches oblate-ellipsoid ray-hit truth over random rays', () => {
		// Flat disc: two long axes, one short — rotated off the camera axes.
		const e: [Vector3, Vector3, Vector3] = [
			new Vector3(0.6, 0.8, 0).normalize(),
			new Vector3(-0.8, 0.6, 0).normalize(),
			new Vector3(0, 0, 1)
		];
		const a: [number, number, number] = [1.5, 1.4, 0.3];
		const c: [number, number, number] = [0.4, 0.2, -5];
		const ax: EllipsoidAxes = { e, a };
		const occ = emptyOcc();
		setEllipsoidOccluder(occ, c[0], c[1], c[2], ax, F, HW, HH, 'b', Math.hypot(...c));
		let mismatch = 0;
		for (let i = 0; i < 4000; i++) {
			const sx = HW + (Math.random() * 2 - 1) * 350;
			const sy = HH + (Math.random() * 2 - 1) * 350;
			const truth = rayHits(c, e, a, sx, sy);
			const test = isScreenOccluded(sx, sy, 1e9, 'x', [occ]);
			if (test !== truth) mismatch++;
		}
		expect(mismatch).toBe(0);
	});
});

describe('occlusion depth gate', () => {
	// Camera near the surface: unit sphere whose centre is 1.39 units ahead, so
	// surface points span 0.39–2.39 in distance. A far-side point off the centre
	// line can then be NEARER than the centre — the regression a centre-distance
	// gate mishandled. The perspective-horizon test keys off the label's own
	// distance, so it also spares near-side points sitting below the mean radius.
	const c: [number, number, number] = [0, 0, -1.39];
	const occ = emptyOcc();
	setSphereOccluder(occ, c[0], c[1], c[2], 1, F, HW, HH, 'b', Math.hypot(...c));

	// A surface point at outward normal n (unit): near cap iff n_z > 0.719 here.
	const at = (n: [number, number, number], radius = 1): [number, number, number] => [
		c[0] + radius * n[0],
		c[1] + radius * n[1],
		c[2] + radius * n[2]
	];
	const occludedAt = (p: [number, number, number]) =>
		isScreenOccluded(...screenOf(...p), Math.hypot(...p), 'x', [occ]);

	it('occludes a far-side label that is nearer than the occluder centre', () => {
		// n_z = 0.5 → far cap; the point lands at distance ~1.24 < 1.39 (centre).
		expect(occludedAt(at([0.866, 0, 0.5]))).toBe(true);
	});

	it('occludes a far-side label behind the body', () => {
		expect(occludedAt(at([0.866, 0, -0.5]))).toBe(true);
	});

	it('leaves a near-side label visible', () => {
		expect(occludedAt(at([0.436, 0, 0.9]))).toBe(false);
	});

	it('leaves a near-side label below the mean radius visible', () => {
		// Sits inside the mean sphere (radius 0.99): a mean-radius near-surface gate
		// wrongly hid it, hiding probes in front of the planet.
		expect(occludedAt(at([0.436, 0, 0.9], 0.99))).toBe(false);
	});

	it('leaves a label off to the side of the body visible', () => {
		expect(occludedAt([2.5, 0, -1.2])).toBe(false);
	});
});

describe('ellipsoid label anchor', () => {
	it('reduces to the sphere β-offset', () => {
		const e: [Vector3, Vector3, Vector3] = [
			new Vector3(1, 0, 0),
			new Vector3(0, 1, 0),
			new Vector3(0, 0, 1)
		];
		const r = 0.7;
		const c: [number, number, number] = [0.9, 0.4, -3];
		const out = { ox: 0, oy: 0 };
		ellipsoidAnchorOffset(c[0], c[1], c[2], { e, a: [r, r, r] }, F, out);
		const beta1 = (r * r) / (c[2] * c[2] - r * r);
		expect(out.ox).toBeCloseTo(beta1 * c[0], 9);
		expect(out.oy).toBeCloseTo(beta1 * c[1], 9);
	});

	it('places the anchor at the projected silhouette center of a flat body', () => {
		const e: [Vector3, Vector3, Vector3] = [
			new Vector3(1, 0, 0),
			new Vector3(0, 1, 0),
			new Vector3(0, 0, 1)
		];
		const a: [number, number, number] = [1.2, 1.2, 0.25];
		const c: [number, number, number] = [1.5, 0.8, -6];
		const out = { ox: 0, oy: 0 };
		ellipsoidAnchorOffset(c[0], c[1], c[2], { e, a }, F, out);
		// Anchor screen point = projection of (c + offset) at the body depth.
		const [ax, ay] = screenOf(c[0] + out.ox, c[1] + out.oy, c[2]);

		// Exact silhouette: limb circle of the unit sphere in normalized space
		// (X = c + aᵢnᵢeᵢ; here axis-aligned so cp = c/a), mapped back + projected.
		// An ellipse's screen bbox is centered on the ellipse, so its bbox center
		// is the true silhouette center the anchor should land on.
		const cp = [c[0] / a[0], c[1] / a[1], c[2] / a[2]];
		const L2 = cp[0] * cp[0] + cp[1] * cp[1] + cp[2] * cp[2];
		const L = Math.sqrt(L2);
		const hk = (L2 - 1) / L2;
		const rho = Math.sqrt(L2 - 1) / L;
		const u = [cp[0] / L, cp[1] / L, cp[2] / L];
		// basis ⊥ u
		const t = Math.abs(u[2]) > 0.9 ? [1, 0, 0] : [0, 0, 1];
		let b1 = [u[1] * t[2] - u[2] * t[1], u[2] * t[0] - u[0] * t[2], u[0] * t[1] - u[1] * t[0]];
		const b1n = Math.hypot(...b1);
		b1 = b1.map((v) => v / b1n);
		const b2 = [
			u[1] * b1[2] - u[2] * b1[1],
			u[2] * b1[0] - u[0] * b1[2],
			u[0] * b1[1] - u[1] * b1[0]
		];
		let minx = Infinity,
			maxx = -Infinity,
			miny = Infinity,
			maxy = -Infinity;
		for (let i = 0; i < 360; i++) {
			const ph = (i / 360) * Math.PI * 2;
			const cs = Math.cos(ph),
				sn = Math.sin(ph);
			const y = [0, 1, 2].map((k) => cp[k] * hk + rho * (cs * b1[k] + sn * b2[k]));
			const X = [a[0] * y[0], a[1] * y[1], a[2] * y[2]]; // axis-aligned: X = Σ aᵢyᵢeᵢ
			const [sx, sy] = screenOf(X[0], X[1], X[2]);
			minx = Math.min(minx, sx);
			maxx = Math.max(maxx, sx);
			miny = Math.min(miny, sy);
			maxy = Math.max(maxy, sy);
		}
		const bcx = (minx + maxx) / 2;
		const bcy = (miny + maxy) / 2;
		const span = Math.hypot(maxx - minx, maxy - miny);
		expect(Math.hypot(ax - bcx, ay - bcy) / span).toBeLessThan(0.01);
	});
});
