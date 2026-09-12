import { describe, expect, it } from 'vitest';
import { AU_KM, AU_SCALE, EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionTEME } from '$lib/math/orbit/sgp4';
import { twoline2satrec } from 'satellite.js';
import type { OrbitalElements } from '$lib/types/objects';
import { resolveAnchor } from './anchor';
import { elements, fixed, interpolateSamples, kmToAu, samples, tle } from './trajectory';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { PositionedBody } from '$lib/types/objects';

/** A stand-in for the map's data layer with one body at the origin, so a
 *  trajectory's own offset is what the anchor resolves to. */
function fakeCtx(id: string): ContextManager {
	const body = {
		data: { id, radiusKm: 1000 },
		position: [0, 0, 0]
	} as unknown as PositionedBody;
	return {
		getBody: (asked: string) => (asked === id ? body : undefined)
	} as unknown as ContextManager;
}

/** The offset a trajectory's anchor reads at `jd`, in kilometres. */
function offsetKm(
	anchor: { offsetKm?: unknown },
	jd: number
): readonly [number, number, number] | null {
	return (anchor.offsetKm as (jd: number) => readonly [number, number, number] | null)(jd);
}

const ISS_LINE1 = '1 25544U 98067A   24274.51782528 -.00002182  00000-0 -11606-4 0  9990';
const ISS_LINE2 = '2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537';

describe('fixed', () => {
	it('is the place it was given', () => {
		const place = { body: 'naif-499', latitude: 18.4, longitude: 77.5, altitudeKm: 3 };
		expect(fixed(place)).toBe(place);
	});
});

describe('interpolateSamples', () => {
	const line = [
		{ jd: 2460000, km: [0, 0, 0] as const },
		{ jd: 2460001, km: [100, 0, 0] as const },
		{ jd: 2460002, km: [200, 0, 0] as const },
		{ jd: 2460003, km: [300, 0, 0] as const }
	];

	it('passes through every state it was given', () => {
		for (const state of line) {
			expect(interpolateSamples(line, state.jd)).toEqual([...state.km]);
		}
	});

	it('reproduces a straight line exactly between states', () => {
		expect(interpolateSamples(line, 2460001.5)?.[0]).toBeCloseTo(150, 9);
		expect(interpolateSamples(line, 2460000.25)?.[0]).toBeCloseTo(25, 9);
	});

	it('says nothing outside the range the states cover', () => {
		expect(interpolateSamples(line, 2459999.9)).toBeNull();
		expect(interpolateSamples(line, 2460003.1)).toBeNull();
	});

	it('says nothing for a list too short to describe a path', () => {
		expect(interpolateSamples([line[0]], 2460000)).toBeNull();
		expect(interpolateSamples([], 2460000)).toBeNull();
	});

	it('follows a curve more closely than a straight line between states', () => {
		// A twelfth of a circle a day: the chord between two states cuts inside
		// the arc, and the cubic follows it.
		const radius = 7000;
		const step = (2 * Math.PI) / 12;
		const circle = [];
		for (let i = 0; i <= 12; i++) {
			circle.push({
				jd: 2460000 + i,
				km: [radius * Math.cos(i * step), radius * Math.sin(i * step), 0] as const
			});
		}
		let worstCubic = 0;
		let worstChord = 0;
		for (let n = 1; n < 40; n++) {
			const s = n / 40;
			const jd = 2460002 + s;
			const angle = (2 + s) * step;
			const exact = [radius * Math.cos(angle), radius * Math.sin(angle)];
			const cubic = interpolateSamples(circle, jd)!;
			const chord = [
				circle[2].km[0] * (1 - s) + circle[3].km[0] * s,
				circle[2].km[1] * (1 - s) + circle[3].km[1] * s
			];
			worstCubic = Math.max(worstCubic, Math.hypot(cubic[0] - exact[0], cubic[1] - exact[1]));
			worstChord = Math.max(worstChord, Math.hypot(chord[0] - exact[0], chord[1] - exact[1]));
		}
		expect(worstChord).toBeGreaterThan(200);
		expect(worstCubic).toBeLessThan(worstChord / 10);
	});

	it('reads states given at uneven intervals at their own dates', () => {
		const uneven = [
			{ jd: 2460000, km: [0, 0, 0] as const },
			{ jd: 2460000.1, km: [10, 0, 0] as const },
			{ jd: 2460004, km: [400, 0, 0] as const }
		];
		expect(interpolateSamples(uneven, 2460000.1)).toEqual([10, 0, 0]);
		expect(interpolateSamples(uneven, 2460000.05)?.[0]).toBeGreaterThan(0);
		expect(interpolateSamples(uneven, 2460000.05)?.[0]).toBeLessThan(10);
	});
});

describe('samples', () => {
	it('sorts what it is given, so states may arrive in any order', () => {
		const anchor = samples({
			body: 'naif-399',
			samples: [
				{ jd: 2460002, km: [200, 0, 0] },
				{ jd: 2460000, km: [0, 0, 0] }
			]
		});
		expect(offsetKm(anchor, 2460001)?.[0]).toBeCloseTo(100, 9);
	});

	it('is measured from the Sun when no body is named', () => {
		expect(samples({ samples: [] }).body).toBe('naif-10');
	});

	it('leaves what it carries undrawn outside its range', () => {
		const ctx = fakeCtx('naif-399');
		const anchor = samples({
			body: 'naif-399',
			samples: [
				{ jd: 2460000, km: [0, 0, 0] },
				{ jd: 2460001, km: [7000, 0, 0] }
			]
		});
		expect(resolveAnchor(anchor, ctx, 2460000.5)).not.toBeNull();
		expect(resolveAnchor(anchor, ctx, 2460002)).toBeNull();
	});
});

describe('elements', () => {
	const circular: OrbitalElements = {
		a: kmToAu(20000),
		e: 0,
		i: 30,
		om: 40,
		w: 0,
		ma: 0,
		n: 20,
		epoch: 2460000
	};

	it('propagates to the same place the map draws the orbit at', () => {
		const anchor = elements({ body: 'naif-399', elements: circular });
		for (const jd of [2460000, 2460001.37, 2460009]) {
			const km = offsetKm(anchor, jd)!;
			// The map's own propagation, in scene units on the scene's axes.
			const scene = orbitalElementsToPositionJD(circular, jd)!;
			const k = AU_SCALE / AU_KM;
			expect(km[0] * k).toBeCloseTo(scene[0], 9);
			expect(km[2] * k).toBeCloseTo(scene[1], 9);
			expect(-km[1] * k).toBeCloseTo(scene[2], 9);
		}
	});

	it('keeps a circular orbit at its own radius all the way round', () => {
		const anchor = elements({ elements: circular });
		for (let jd = 2460000; jd < 2460018; jd += 1.5) {
			expect(Math.hypot(...offsetKm(anchor, jd)!)).toBeCloseTo(20000, 3);
		}
	});

	it('is round the Sun when no body is named', () => {
		expect(elements({ elements: circular }).body).toBe('naif-10');
	});
});

describe('tle', () => {
	const satrec = twoline2satrec(ISS_LINE1, ISS_LINE2);

	it('orbits Earth', () => {
		expect(tle(ISS_LINE1, ISS_LINE2).body).toBe('naif-399');
	});

	it('is what SGP4 says, turned onto the ecliptic', () => {
		const anchor = tle(ISS_LINE1, ISS_LINE2);
		const jd = satrec.jdsatepoch + 0.01;
		const teme = sgp4PositionTEME(satrec, jd)!;
		const km = offsetKm(anchor, jd)!;
		const eps = (EARTH_OBLIQUITY_DEG * Math.PI) / 180;
		expect(km[0]).toBeCloseTo(teme[0], 9);
		expect(km[1]).toBeCloseTo(teme[1] * Math.cos(eps) + teme[2] * Math.sin(eps), 9);
		expect(km[2]).toBeCloseTo(-teme[1] * Math.sin(eps) + teme[2] * Math.cos(eps), 9);
		// The turn is a rotation, so the distance from Earth is unchanged.
		expect(Math.hypot(...km)).toBeCloseTo(Math.hypot(...teme), 9);
	});

	it('holds a low orbit and comes back round in its own period', () => {
		const anchor = tle(ISS_LINE1, ISS_LINE2);
		const epoch = satrec.jdsatepoch;
		const start = offsetKm(anchor, epoch)!;
		for (let minutes = 0; minutes <= 180; minutes += 5) {
			const r = Math.hypot(...offsetKm(anchor, epoch + minutes / 1440)!);
			expect(r).toBeGreaterThan(6500);
			expect(r).toBeLessThan(6900);
		}
		// 15.72 revolutions a day: one period is 91.6 minutes.
		const period = 1 / 15.72125391;
		const later = offsetKm(anchor, epoch + period)!;
		const drift = Math.hypot(later[0] - start[0], later[1] - start[1], later[2] - start[2]);
		expect(drift).toBeLessThan(60);
		// Half a period away it is on the other side of the planet.
		const opposite = offsetKm(anchor, epoch + period / 2)!;
		expect(
			Math.hypot(opposite[0] - start[0], opposite[1] - start[1], opposite[2] - start[2])
		).toBeGreaterThan(13000);
	});

	it('moves, so a satellite is somewhere else a minute later', () => {
		const anchor = tle(ISS_LINE1, ISS_LINE2);
		const epoch = satrec.jdsatepoch;
		const a = offsetKm(anchor, epoch)!;
		const b = offsetKm(anchor, epoch + 1 / 1440)!;
		const moved = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
		// Near 7.66 km/s, so about 460 km a minute.
		expect(moved).toBeGreaterThan(400);
		expect(moved).toBeLessThan(500);
	});

	it('says nothing for an element set SGP4 will not take', () => {
		// An eccentricity of 0.9999999, which SGP4 rejects at initialisation.
		const broken = tle(ISS_LINE1, ISS_LINE2.replace('0006703', '9999999'));
		expect(offsetKm(broken, 2460584)).toBeNull();
	});
});
