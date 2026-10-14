import { describe, it, expect } from 'vitest';
import { Color } from 'three';
import {
	lambertSpherePhase,
	makePlanetshineUniforms,
	MAX_SHINERS,
	planetshineFraction,
	selectShiners,
	SHINE_FLOOR,
	type Shiner,
	sphereLightCosine
} from './planetshine';

/**
 * Contract tests for the planetshine maths and for the CPU port of the GLSL
 * `sphereLightCosine`. The shader and these functions must agree on the values.
 */

/** Light of a disc of even radiance and angular radius `alpha` on a facet whose
 *  normal is `theta` from its centre, over the light on a facet that faces it.
 *  Midpoint sum over the disc, as a check that owes nothing to the formula. */
function discOnFacet(theta: number, alpha: number, steps = 400): number {
	// Normal in the x-z plane; the disc is centred on +z.
	const nx = Math.sin(theta);
	const nz = Math.cos(theta);
	let lit = 0;
	let full = 0;
	for (let i = 0; i < steps; i++) {
		const t = ((i + 0.5) / steps) * alpha;
		const solid = Math.sin(t) * (alpha / steps) * ((2 * Math.PI) / steps);
		for (let j = 0; j < steps; j++) {
			const p = ((j + 0.5) / steps) * 2 * Math.PI;
			const cosToNormal = Math.sin(t) * Math.cos(p) * nx + Math.cos(t) * nz;
			lit += Math.max(cosToNormal, 0) * solid;
			full += Math.cos(t) * solid;
		}
	}
	return lit / full;
}

function shiner(
	pos: [number, number, number],
	radius: number,
	toSun: [number, number, number],
	albedo = 1,
	sunlight = 1
): Shiner {
	const len = Math.hypot(...toSun);
	return {
		x: pos[0],
		y: pos[1],
		z: pos[2],
		radius,
		sunX: toSun[0] / len,
		sunY: toSun[1] / len,
		sunZ: toSun[2] / len,
		sunlight,
		albedo: new Color(albedo, albedo, albedo)
	};
}

describe('lambertSpherePhase', () => {
	it('is 1 at full phase, 1/pi at quarter phase and 0 at new phase', () => {
		expect(lambertSpherePhase(0)).toBeCloseTo(1, 12);
		expect(lambertSpherePhase(Math.PI / 2)).toBeCloseTo(1 / Math.PI, 12);
		expect(lambertSpherePhase(Math.PI)).toBeCloseTo(0, 12);
	});

	it('goes down as the phase angle goes up', () => {
		for (let deg = 1; deg <= 180; deg++) {
			expect(lambertSpherePhase((deg * Math.PI) / 180)).toBeLessThan(
				lambertSpherePhase(((deg - 1) * Math.PI) / 180)
			);
		}
	});
});

describe('planetshineFraction', () => {
	it('is the geometric albedo times the solid angle term', () => {
		expect(planetshineFraction(1, 10, 0)).toBeCloseTo((2 / 3) * 0.01, 15);
		expect(planetshineFraction(2, 10, Math.PI / 2)).toBeCloseTo(((2 / 3) * 0.04) / Math.PI, 15);
	});

	it('gives the sizes the scene must show', () => {
		// Saturn from Mimas, Mars from Phobos, Jupiter from Io, the Earth from the Moon (km).
		expect(planetshineFraction(58232, 185539, 0)).toBeCloseTo(0.0657, 3);
		expect(planetshineFraction(3389.5, 9376, 0)).toBeCloseTo(0.0871, 3);
		expect(planetshineFraction(69911, 421700, 0)).toBeCloseTo(0.0183, 3);
		expect(planetshineFraction(6371, 384400, 0)).toBeCloseTo(1.83e-4, 5);
	});
});

describe('sphereLightCosine', () => {
	it('is the cosine where all of the disc is above the horizon', () => {
		expect(sphereLightCosine(1, 0.3)).toBe(1);
		expect(sphereLightCosine(0.5, 0.3)).toBe(0.5);
		expect(sphereLightCosine(0.3, 0.3)).toBeCloseTo(0.3, 15);
	});

	it('is 0 where all of the disc is below the horizon', () => {
		expect(sphereLightCosine(-0.3, 0.3)).toBe(0);
		expect(sphereLightCosine(-0.9, 0.3)).toBe(0);
	});

	it('has no step and no kink at the edges of the band', () => {
		const s = 0.36;
		const e = 1e-7;
		for (const edge of [s, -s]) {
			expect(sphereLightCosine(edge + e, s)).toBeCloseTo(sphereLightCosine(edge - e, s), 6);
			const slopeAbove = (sphereLightCosine(edge + 2 * e, s) - sphereLightCosine(edge + e, s)) / e;
			const slopeBelow = (sphereLightCosine(edge - e, s) - sphereLightCosine(edge - 2 * e, s)) / e;
			expect(slopeAbove).toBeCloseTo(slopeBelow, 4);
		}
	});

	it('is close to the light of a disc across the horizon', () => {
		// Mars from Phobos (21 deg), Saturn from Mimas (19 deg), Jupiter from Io (9.5 deg).
		for (const alphaDeg of [21, 19, 9.5]) {
			const alpha = (alphaDeg * Math.PI) / 180;
			for (let deg = 0; deg <= 180; deg += 5) {
				const theta = (deg * Math.PI) / 180;
				const exact = discOnFacet(theta, alpha);
				expect(Math.abs(sphereLightCosine(Math.cos(theta), Math.sin(alpha)) - exact)).toBeLessThan(
					0.015
				);
			}
		}
	});
});

describe('selectShiners', () => {
	it('starts from empty slots', () => {
		const out = makePlanetshineUniforms();
		for (const v of out.uShineDir.value) expect(v.toArray()).toEqual([0, 0, 0, 0]);
		for (const v of out.uShineLight.value) expect(v.toArray()).toEqual([0, 0, 0]);
	});

	it('keeps the two strongest shiners, strongest first', () => {
		const out = makePlanetshineUniforms();
		const sun: [number, number, number] = [-1, 0, 0];
		// Full at 10, half at 5, half at 20, half at 8: the second is the strongest.
		const list = [
			shiner([10, 0, 0], 1, sun),
			shiner([0, 5, 0], 1, sun),
			shiner([0, 0, 20], 1, sun),
			shiner([0, 0, 8], 1, sun)
		];
		expect(MAX_SHINERS).toBe(2);
		expect(selectShiners(out, 0, 0, 0, list, list.length)).toBe(2);
		const [a, b] = out.uShineDir.value;
		expect(a.toArray()).toEqual([0, 1, 0, 0.2]);
		expect(b.toArray()).toEqual([1, 0, 0, 0.1]);
	});

	it('gives the irradiance of the shiner in the units of its sunlight', () => {
		const out = makePlanetshineUniforms();
		// The Sun is behind the receiver: the shiner is full.
		const s = shiner([10, 0, 0], 2, [-1, 0, 0], 0.5, 3.5);
		s.albedo.setRGB(0.6, 0.5, 0.4);
		selectShiners(out, 0, 0, 0, [s], 1);
		const light = out.uShineLight.value[0];
		const fraction = (2 / 3) * 0.04;
		expect(light.x).toBeCloseTo(3.5 * fraction * 0.6, 12);
		expect(light.y).toBeCloseTo(3.5 * fraction * 0.5, 12);
		expect(light.z).toBeCloseTo(3.5 * fraction * 0.4, 12);
	});

	it('takes the phase angle at the shiner', () => {
		const out = makePlanetshineUniforms();
		// The Sun is beside the shiner, 90 deg from the receiver.
		selectShiners(out, 0, 0, 0, [shiner([10, 0, 0], 2, [0, 1, 0])], 1);
		expect(out.uShineLight.value[0].x).toBeCloseTo(((2 / 3) * 0.04) / Math.PI, 12);
		// The Sun is behind the shiner: the receiver sees its night side.
		expect(selectShiners(out, 0, 0, 0, [shiner([10, 0, 0], 2, [1, 0, 0])], 1)).toBe(0);
	});

	it('skips the receiver itself', () => {
		const out = makePlanetshineUniforms();
		expect(selectShiners(out, 1, 2, 3, [shiner([1, 2, 3], 0.5, [1, 0, 0])], 1)).toBe(0);
	});

	it('skips a shiner below the floor and clears the slots it does not fill', () => {
		const out = makePlanetshineUniforms();
		out.uShineDir.value[0].set(1, 0, 0, 0.5);
		out.uShineDir.value[1].set(0, 1, 0, 0.5);
		out.uShineLight.value[1].set(1, 1, 1);
		// The Earth from the Moon at full phase, with a bright albedo.
		const earth = shiner([384400, 0, 0], 6371, [-1, 0, 0], 0.4);
		expect(planetshineFraction(6371, 384400, 0) * 0.4).toBeLessThan(SHINE_FLOOR);
		const mars = shiner([0, 9376, 0], 3389.5, [0, -1, 0], 0.25);
		expect(selectShiners(out, 0, 0, 0, [earth, mars], 2)).toBe(1);
		expect(out.uShineDir.value[0].y).toBeCloseTo(1, 12);
		expect(out.uShineDir.value[1].toArray()).toEqual([0, 0, 0, 0]);
		expect(out.uShineLight.value[1].toArray()).toEqual([0, 0, 0]);
	});
});
