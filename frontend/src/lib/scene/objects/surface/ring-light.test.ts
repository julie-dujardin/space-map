import { describe, it, expect } from 'vitest';
import { SUN_LIGHT_INTENSITY } from '$lib/scene/lighting';
import { lambertSpherePhase, SHINE_FLOOR } from './planetshine';
import {
	forwardWeight,
	particlePhase,
	PLANET_LIGHT_AZIMUTHS,
	PLANET_LIGHT_RADII,
	peakRingshine,
	planetLightOnRing,
	PROFILE_MU,
	type ProfileRows,
	reflectionGain,
	type RingProfile,
	ringProfile,
	RINGSHINE_PATCHES,
	ringshineAt,
	ringshinePatches,
	type Spheroid,
	unlitGain
} from './ring-light';

/**
 * Contract tests for the light between a planet and its rings, and for the CPU
 * port of the GLSL patch sum. The references here are fine sums over the
 * annulus and over the sphere that owe nothing to the patches or the grid.
 */

const ROWS: ProfileRows = {
	color: 0,
	backscattered: 1,
	forwardscattered: 2,
	unlitside: 3,
	transparency: 4
};

/** A ring strip of `width` samples from regions of [outer edge, back, forward, unlit, transparency]. */
function strip(
	width: number,
	inner: number,
	outer: number,
	regions: [number, number, number, number, number][],
	color: [number, number, number] = [230, 210, 180]
): Uint8ClampedArray {
	const pixels = new Uint8ClampedArray(width * 5 * 4);
	for (let i = 0; i < width; i++) {
		const r = inner + ((i + 0.5) / width) * (outer - inner);
		const region = regions.find(([edge]) => r < edge) ?? [0, 0, 0, 0, 1];
		const set = (row: number, rgb: [number, number, number]) => {
			pixels.set([...rgb, 255], (row * width + i) * 4);
		};
		set(ROWS.color, color);
		for (const [row, value] of [
			[ROWS.backscattered, region[1]],
			[ROWS.forwardscattered, region[2]],
			[ROWS.unlitside, region[3]],
			[ROWS.transparency, region[4]]
		]) {
			const byte = Math.round(value * 255);
			set(row, [byte, byte, byte]);
		}
	}
	return pixels;
}

/** Saturn's main rings in units of its equatorial radius: C, B, Cassini Division, A. */
const SATURN: Spheroid = { equatorial: 1, polar: 54364 / 60268 };
const SATURN_INNER = 74510 / 60268;
const SATURN_OUTER = 140390 / 60268;
function saturnRings(): RingProfile {
	const width = 2000;
	const pixels = strip(width, SATURN_INNER, SATURN_OUTER, [
		[1.527, 0.3, 0.4, 0.5, 0.85],
		[1.951, 0.9, 0.6, 0.1, 0.05],
		[2.025, 0.2, 0.5, 0.6, 0.85],
		[2.27, 0.7, 0.5, 0.3, 0.4]
	]);
	return ringProfile(pixels, width, ROWS, SATURN_INNER, SATURN_OUTER, 1);
}

type Triple = [number, number, number];

/** A point on the spheroid at parametric latitude `beta` and longitude
 *  `lambda` from the Sun (degrees), with its unit normal. */
function surface(planet: Spheroid, betaDeg: number, lambdaDeg: number): { q: Triple; n: Triple } {
	const beta = (betaDeg * Math.PI) / 180;
	const lambda = (lambdaDeg * Math.PI) / 180;
	const { equatorial: a, polar: c } = planet;
	const q: Triple = [
		a * Math.cos(beta) * Math.cos(lambda),
		a * Math.cos(beta) * Math.sin(lambda),
		c * Math.sin(beta)
	];
	const n: Triple = [
		(Math.cos(beta) * Math.cos(lambda)) / a,
		(Math.cos(beta) * Math.sin(lambda)) / a,
		Math.sin(beta) / c
	];
	const len = Math.hypot(...n);
	return { q, n: [n[0] / len, n[1] / len, n[2] / len] };
}

/** True where the Sun's ray from the point of the ring plane meets the
 *  spheroid: a root t > 0 of |x + t S|² on the spheroid's quadratic form. */
function shadowed(x: number, y: number, sinB: number, planet: Spheroid): boolean {
	const cosB = Math.sqrt(1 - sinB * sinB);
	const a2 = planet.equatorial ** 2;
	const c2 = planet.polar ** 2;
	const qa = (cosB * cosB) / a2 + (sinB * sinB) / c2;
	const qb = (2 * x * cosB) / a2;
	const qc = (x * x + y * y) / a2 - 1;
	return qb < 0 && qb * qb - 4 * qa * qc >= 0;
}

/** Ringshine at `q` by a fine sum over the annulus: the phase of each sample
 *  toward `q`, and its own shadow test. */
function ringshineReference(
	profile: RingProfile,
	sinB: number,
	planet: Spheroid,
	q: Triple,
	n: Triple
): number {
	const radial = 512;
	const azimuths = 720;
	const cosB = Math.sqrt(1 - sinB * sinB);
	const mu0 = Math.abs(sinB);
	const dr = (profile.outer - profile.inner) / radial;
	const dPhi = (2 * Math.PI) / azimuths;
	const sunSide = sinB >= 0 === q[2] >= 0;
	const litGain = (bin: number) =>
		reflectionGain(mu0, mu0, -Math.log(Math.max(profile.transmission[bin], 1e-6)));
	let e = 0;
	for (let j = 0; j < azimuths; j++) {
		const phi = (j + 0.5) * dPhi;
		const c = Math.cos(phi);
		const s = Math.sin(phi);
		for (let i = 0; i < radial; i++) {
			const r = profile.inner + (i + 0.5) * dr;
			const vx = r * c - q[0];
			const vy = r * s - q[1];
			const vz = -q[2];
			const d = Math.hypot(vx, vy, vz);
			const facing = (n[0] * vx + n[1] * vy + n[2] * vz) / d;
			if (facing <= 0) continue;
			if (shadowed(r * c, r * s, sinB, planet)) continue;
			const bin = Math.floor(((i + 0.5) / radial) * profile.back.length);
			const mu = Math.abs(vz) / d;
			const cosPhase = -(vx * cosB + vz * sinB) / d;
			const radiance = sunSide
				? (profile.back[bin] * particlePhase(cosPhase) +
						(profile.forward[bin] - profile.back[bin] * particlePhase(cosPhase)) *
							forwardWeight(cosPhase)) *
					litGain(bin)
				: profile.unlit[bin];
			e += ((radiance * unlitGain(mu0, mu) * facing * mu) / (d * d)) * r * dr * dPhi;
		}
	}
	return e;
}

describe('forwardWeight', () => {
	it('is 0 at phase 0, 1 at phase 180 deg and 0.5 edge-on', () => {
		expect(forwardWeight(1)).toBe(0);
		expect(forwardWeight(-1)).toBe(1);
		expect(forwardWeight(0)).toBeCloseTo(0.5, 12);
	});
});

describe('particlePhase', () => {
	it('is 1 at phase 0 and falls as a power of π minus the phase', () => {
		expect(particlePhase(1)).toBe(1);
		expect(particlePhase(0)).toBeCloseTo(0.5 ** 3.09, 12);
		expect(particlePhase(-1)).toBe(0);
	});
});

describe('reflectionGain', () => {
	const deg = (d: number) => Math.sin((d * Math.PI) / 180);

	it('is 1 in the geometry of the profiles at any depth', () => {
		for (const tau of [1e-6, 0.01, 0.1, 1, 5]) {
			expect(reflectionGain(PROFILE_MU, PROFILE_MU, tau)).toBeCloseTo(1, 4);
		}
	});

	it('goes to 0 when the Sun is in the ring plane', () => {
		for (const tau of [0.05, 0.5, 2]) {
			expect(reflectionGain(deg(0.05), deg(25), tau)).toBeLessThan(0.01);
			expect(reflectionGain(0, deg(25), tau)).toBe(0);
		}
	});

	it('is Lommel-Seeliger for a dense ring', () => {
		for (const [mu0, mu] of [
			[0.4, 0.4],
			[0.1, 0.8],
			[0.9, 0.05]
		]) {
			expect(reflectionGain(mu0, mu, 8)).toBeCloseTo(unlitGain(mu0, mu), 3);
		}
	});

	it('gives the change in I/F that HST measured from 4.5° to 23.6°', () => {
		// Salo and French (2010), F555W at phase 0.27-0.46°: C ring at a depth of
		// 0.09, 0.168 to 0.0657; A ring at 0.45, 0.528 to 0.412.
		const tilt = (tau: number) => {
			const low = deg(4.5);
			const high = deg(23.6);
			return reflectionGain(high, high, tau) / reflectionGain(low, low, tau);
		};
		expect(tilt(0.09) / (0.0657 / 0.168)).toBeCloseTo(1, 1);
		expect(tilt(0.45) / (0.412 / 0.528)).toBeGreaterThan(1);
		expect(tilt(0.45) / (0.412 / 0.528)).toBeLessThan(1.2);
	});
});

describe('ringProfile', () => {
	it('bins the light as the ring shader draws it', () => {
		const width = 512;
		// White colour, back 1, forward 0.5, unlit 0.25, half transparent, intensity 0.5.
		const pixels = strip(width, 1, 2, [[3, 1, 0.5, 0.25, 0.5]], [255, 255, 255]);
		const p = ringProfile(pixels, width, ROWS, 1, 2, 0.5);
		const opacity = (1 - 128 / 255) * 0.5;
		const weight = opacity * 0.5;
		expect(p.back[0]).toBeCloseTo(0.5, 6);
		expect(p.forward[10]).toBeCloseTo(
			(128 / 255) * weight * (0.2126 * 1.02 + 0.7152 * 0.99 + 0.0722 * 0.97),
			6
		);
		expect(p.unlit[100]).toBeCloseTo(
			(64 / 255) * weight * (0.2126 + 0.7152 * 0.97075 + 0.0722 * 0.952),
			6
		);
		expect(p.transmission[255]).toBeCloseTo(1 - opacity, 6);
		expect(p.litTint.r).toBeCloseTo(1, 6);
	});

	it('keeps the light of a ring narrower than a bin', () => {
		// One dense sample among 40 in its bin.
		const width = 40 * 256;
		const pixels = strip(width, 0, 1, [
			[0.5, 0, 0, 0, 1],
			[0.5001, 1, 1, 1, 0],
			[2, 0, 0, 0, 1]
		]);
		const p = ringProfile(pixels, width, ROWS, 0, 1, 1);
		const linear = (byte: number) => ((byte / 255 + 0.055) / 1.055) ** 2.4;
		const colour = 0.2126 * linear(230) + 0.7152 * linear(210) + 0.0722 * linear(180);
		expect(p.back[128] * 40).toBeCloseTo(colour, 6);
		expect(p.back.reduce((a, b) => a + b, 0)).toBeCloseTo(p.back[128], 12);
	});

	it('splits the light in bands of at least one bin each', () => {
		const p = saturnRings();
		for (let b = 1; b < p.bands.length; b++) expect(p.bands[b]).toBeGreaterThan(p.bands[b - 1]);
		expect(p.bands[0]).toBe(0);
		expect(p.bands[p.bands.length - 1]).toBe(p.back.length);
	});
});

describe('ringshinePatches', () => {
	it('holds the light of the lit annulus', () => {
		const profile = saturnRings();
		const sinB = Math.sin((20 * Math.PI) / 180);
		const patches = new Float64Array(4 * RINGSHINE_PATCHES);
		ringshinePatches(patches, profile, sinB, SATURN);
		let held = 0;
		for (let i = 0; i < RINGSHINE_PATCHES; i++)
			held += 2 * (patches[4 * i + 2] + patches[4 * i + 3]);
		// Unshadowed light of both faces, phase toward the centre.
		const cosB = Math.sqrt(1 - sinB * sinB);
		const bins = profile.back.length;
		const dr = (profile.outer - profile.inner) / bins;
		const steps = 720;
		let direct = 0;
		for (let j = 0; j < steps; j++) {
			const phi = ((j + 0.5) / steps) * 2 * Math.PI;
			const w = forwardWeight(-cosB * Math.cos(phi));
			const phase = particlePhase(-cosB * Math.cos(phi));
			for (let i = 0; i < bins; i++) {
				const r = profile.inner + (i + 0.5) * dr;
				if (shadowed(r * Math.cos(phi), r * Math.sin(phi), sinB, SATURN)) continue;
				const gain = reflectionGain(sinB, sinB, -Math.log(Math.max(profile.transmission[i], 1e-6)));
				const lit =
					(profile.back[i] * phase + (profile.forward[i] - profile.back[i] * phase) * w) * gain;
				direct += (lit + profile.unlit[i]) * r * dr * ((2 * Math.PI) / steps);
			}
		}
		expect(held / direct).toBeCloseTo(1, 2);
	});

	it('puts the lit face on the side of the Sun', () => {
		const profile = saturnRings();
		const above = new Float64Array(4 * RINGSHINE_PATCHES);
		const below = new Float64Array(4 * RINGSHINE_PATCHES);
		ringshinePatches(above, profile, 0.4, SATURN);
		ringshinePatches(below, profile, -0.4, SATURN);
		for (let i = 0; i < RINGSHINE_PATCHES; i++) {
			expect(below[4 * i + 2]).toBeCloseTo(above[4 * i + 3], 12);
			expect(below[4 * i + 3]).toBeCloseTo(above[4 * i + 2], 12);
		}
	});
});

describe('ringshineAt', () => {
	const profile = saturnRings();

	it('is close to a fine sum over the annulus', () => {
		const sinB = Math.sin((20 * Math.PI) / 180);
		const patches = new Float64Array(4 * RINGSHINE_PATCHES);
		ringshinePatches(patches, profile, sinB, SATURN);
		const points: [number, number][] = [];
		for (const beta of [5, 10, 20, 30, 45]) {
			for (const lambda of [0, 60, 90, 120, 150, 180]) points.push([beta, lambda]);
		}
		for (const beta of [-10, -20, -30]) {
			for (const lambda of [0, 90, 120, 180]) points.push([beta, lambda]);
		}
		const pairs = points.map(([beta, lambda]) => {
			const { q, n } = surface(SATURN, beta, lambda);
			return {
				at: `${beta}/${lambda}`,
				reference: ringshineReference(profile, sinB, SATURN, q, n),
				patches: ringshineAt(patches, sinB, q[0], q[1], q[2], n[0], n[1], n[2])
			};
		});
		const peak = Math.max(...pairs.map((p) => p.reference));
		// The ringshine at its peak is some percent of the sunlight.
		expect(peak / SUN_LIGHT_INTENSITY).toBeGreaterThan(0.01);
		// A patch takes the phase toward the planet's centre. The phase function of
		// the particles is steep, so the sum is off most where the light is low.
		for (const { at, reference, patches: sum } of pairs) {
			const error = Math.abs(sum - reference) / Math.max(reference, 0.05 * peak);
			expect(error, at).toBeLessThan(0.25);
		}
	});

	it('goes to 0 when the Sun is in the ring plane', () => {
		const patches = new Float64Array(4 * RINGSHINE_PATCHES);
		const { q, n } = surface(SATURN, 20, 120);
		const at = (sinB: number) => {
			ringshinePatches(patches, profile, sinB, SATURN);
			return ringshineAt(patches, Math.abs(sinB), q[0], q[1], q[2], n[0], n[1], n[2]);
		};
		const levels = [20, 10, 5, 2, 0.5, 0.001].map((deg) => at(Math.sin((deg * Math.PI) / 180)));
		for (let i = 1; i < levels.length; i++) expect(levels[i]).toBeLessThan(levels[i - 1]);
		expect(levels[3] / levels[0]).toBeLessThan(0.25);
		expect(levels[5] / levels[0]).toBeLessThan(1e-3);
	});

	it('is 0 on the equator and on a fragment that faces away from the rings', () => {
		const patches = new Float64Array(4 * RINGSHINE_PATCHES);
		ringshinePatches(patches, profile, 0.4, SATURN);
		const equator = surface(SATURN, 0, 120);
		expect(ringshineAt(patches, 0.4, ...equator.q, ...equator.n)).toBe(0);
		const pole = surface(SATURN, 90, 0);
		expect(ringshineAt(patches, 0.4, ...pole.q, ...pole.n)).toBe(0);
	});
});

describe('planetLightOnRing', () => {
	const empty = ringProfile(strip(64, 1, 2, []), 64, ROWS, 1, 2, 1);
	const noPatches = new Float64Array(4 * RINGSHINE_PATCHES);
	const sphere: Spheroid = { equatorial: 1, polar: 1 };
	const out = new Float32Array(4 * PLANET_LIGHT_AZIMUTHS * PLANET_LIGHT_RADII);
	const node = (j: number, k: number) => 4 * (j * PLANET_LIGHT_AZIMUTHS + k);

	it('is the light of a Lambert sphere far away', () => {
		const sinB = 0.3;
		planetLightOnRing(out, 300, 400, sinB, sphere, empty, noPatches);
		const cosB = Math.sqrt(1 - sinB * sinB);
		for (const k of [0, 9, 12]) {
			const cosPhi = 1 - (2 * k) / (PLANET_LIGHT_AZIMUTHS - 1);
			const phase = Math.acos(cosB * cosPhi);
			const expected = (2 / 3) * lambertSpherePhase(phase) * (1 / 300) ** 2;
			expect((out[node(0, k)] + out[node(0, k) + 1]) / expected).toBeCloseTo(1, 1);
		}
	});

	it('comes in at the sine of the planet as the ring sees it', () => {
		const sinB = 0.3;
		planetLightOnRing(out, 300, 400, sinB, sphere, empty, noPatches);
		// A far planet is a point in the ring plane: it lights both faces at grazing incidence.
		expect(out[node(0, 0) + 2]).toBeLessThan(0.01);
		planetLightOnRing(out, 1.3, 2.3, sinB, SATURN, empty, noPatches);
		const near = out[node(0, 0) + 2];
		const far = out[node(PLANET_LIGHT_RADII - 1, 0) + 2];
		expect(near).toBeGreaterThan(far);
		expect(near).toBeLessThan(0.6);
		expect(far).toBeGreaterThan(0.05);
	});

	it('lights the face on the side of the Sun more at full phase', () => {
		planetLightOnRing(out, 1.3, 2.3, 0.4, SATURN, empty, noPatches);
		expect(out[node(0, 0)]).toBeGreaterThan(out[node(0, 0) + 1]);
		planetLightOnRing(out, 1.3, 2.3, -0.4, SATURN, empty, noPatches);
		expect(out[node(0, 0) + 1]).toBeGreaterThan(out[node(0, 0)]);
	});

	it('gives no day light in the shadow of the planet', () => {
		planetLightOnRing(out, 1.3, 2.3, 0.2, SATURN, empty, noPatches);
		const last = PLANET_LIGHT_AZIMUTHS - 1;
		expect(out[node(0, last)]).toBe(0);
		expect(out[node(0, last) + 1]).toBe(0);
		expect(out[node(0, 0)]).toBeGreaterThan(0.1);
	});

	it('gives the ringshine of the night side in the shadow of the planet', () => {
		const profile = saturnRings();
		const sinB = Math.sin((20 * Math.PI) / 180);
		const patches = new Float64Array(4 * RINGSHINE_PATCHES);
		ringshinePatches(patches, profile, sinB, SATURN);
		planetLightOnRing(out, SATURN_INNER, SATURN_OUTER, sinB, SATURN, profile, patches);
		const shadow = node(3, PLANET_LIGHT_AZIMUTHS - 1);
		// The lit face sees the night side under the lit face of the rings.
		expect(out[shadow]).toBeGreaterThan(1e-4);
		expect(out[shadow]).toBeLessThan(1e-2);
		expect(out[shadow]).toBeGreaterThan(1.5 * out[shadow + 1]);
	});

	it('darkens the light from under the ring shadow', () => {
		const opaque = ringProfile(strip(64, 1.3, 2.3, [[3, 0, 0, 0, 0]]), 64, ROWS, 1.3, 2.3, 1);
		planetLightOnRing(out, 1.3, 2.3, 0.4, sphere, empty, noPatches);
		const open = out.slice();
		planetLightOnRing(out, 1.3, 2.3, 0.4, sphere, opaque, noPatches);
		expect(out[node(4, 0)]).toBeCloseTo(open[node(4, 0)], 6);
		expect(out[node(4, 0) + 1]).toBeLessThan(0.8 * open[node(4, 0) + 1]);
	});
});

describe('peakRingshine', () => {
	it('is over the floor for Saturn-like rings and 0 for empty ones', () => {
		expect(peakRingshine(saturnRings(), SATURN)).toBeGreaterThan(SHINE_FLOOR);
		const empty = ringProfile(strip(64, 1.3, 2.3, []), 64, ROWS, 1.3, 2.3, 1);
		expect(peakRingshine(empty, SATURN)).toBe(0);
	});
});
