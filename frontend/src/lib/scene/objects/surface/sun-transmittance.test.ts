import { describe, it, expect } from 'vitest';
import { Vector3 } from 'three';
import type { AtmosphereParams } from './atmosphere';
import { phaseAsymmetry, skyLightFraction, skyLightSplit, skySun } from './sun-transmittance';

/**
 * Contract tests for the CPU ports of the GLSL `atmoTSkySun` and
 * `atmoSkyLight`, and for the split of the noon light. The shader and these
 * functions must agree on the values.
 */

/** Henyey-Greenstein phase table of asymmetry `g`, in the 3×128 layout of the
 *  export (θ = π·(i/127)²), normalised to 1 over the sphere. */
function hgTable(g: number): number[] {
	const row = Array.from({ length: 128 }, (_, i) => {
		const cos = Math.cos(Math.PI * (i / 127) ** 2);
		return (1 - g * g) / (4 * Math.PI * (1 + g * g - 2 * g * cos) ** 1.5);
	});
	return [...row, ...row, ...row];
}

const BASE: AtmosphereParams = {
	topAltitudeKm: 100,
	rayleighScatterPerKm: [0, 0, 0],
	rayleighScaleHeightKm: 8,
	mieScatterPerKm: [0, 0, 0],
	mieAbsorptionPerKm: [0, 0, 0],
	mieScaleHeightKm: 8,
	miePhase: hgTable(0.7),
	absorptionPerKm: [0, 0, 0],
	absorptionCenterKm: 0,
	absorptionWidthKm: 1,
	bakedCompensation: 1,
	multiScatterGain: 0.3,
	sunIntensity: 5,
	sunColor: [1, 1, 1],
	groundAlbedo: 0.2
};

/** The air of the Earth and of Mars as the export has it. */
const EARTH: AtmosphereParams = {
	...BASE,
	rayleighScatterPerKm: [0.004848, 0.01149, 0.02871],
	rayleighScaleHeightKm: 8.4,
	mieScatterPerKm: [0.0513, 0.0694, 0.0952],
	mieAbsorptionPerKm: [0.0056, 0.0056, 0.0056],
	mieScaleHeightKm: 1.2,
	miePhase: hgTable(0.75),
	absorptionPerKm: [0.000730864, 0.001768046, 7.2549e-5],
	absorptionCenterKm: 25,
	absorptionWidthKm: 15,
	bakedCompensation: 0.35
};
const EARTH_KM = 6371;

const MARS: AtmosphereParams = {
	...BASE,
	rayleighScatterPerKm: [0.000102, 0.0002427, 0.0006099],
	rayleighScaleHeightKm: 11,
	mieScatterPerKm: [0.0133, 0.009, 0.0055],
	mieAbsorptionPerKm: [0.00034, 0.0046, 0.0082],
	mieScaleHeightKm: 11,
	miePhase: hgTable(0.685)
};
const MARS_KM = 3390;

const PLUTO: AtmosphereParams = {
	...BASE,
	rayleighScatterPerKm: [3.28e-7, 7.762e-7, 1.936e-6],
	rayleighScaleHeightKm: 24,
	mieScatterPerKm: [0.00019, 0.00036, 0.0007],
	mieAbsorptionPerKm: [5e-5, 5e-5, 5e-5],
	mieScaleHeightKm: 50,
	miePhase: hgTable(0.6)
};
const PLUTO_KM = 1188;

const lum = (c: readonly number[]) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];

describe('phaseAsymmetry', () => {
	it('is 0 for an isotropic table', () => {
		const g = phaseAsymmetry(new Array(384).fill(1 / (4 * Math.PI)));
		for (const v of g) expect(v).toBeCloseTo(0, 3);
	});

	it('finds the asymmetry of a Henyey-Greenstein table', () => {
		for (const g of [0.3, 0.7, 0.85]) {
			for (const v of phaseAsymmetry(hgTable(g))) expect(v).toBeCloseTo(g, 2);
		}
	});
});

describe('skySun', () => {
	const h = 11 / 3390;

	it('is the sine of the Sun far over the horizon', () => {
		const [mu, airmass] = skySun(0.8, h);
		expect(mu).toBeCloseTo(0.8, 2);
		expect(airmass).toBeCloseTo(1 / 0.8, 2);
	});

	it('gives the airmass of an exponential column at the horizon', () => {
		// √(πR/2H), the Chapman function at 90°.
		expect(skySun(1e-9, h)[1]).toBeCloseTo(Math.sqrt(Math.PI / (2 * h)), 6);
		expect(skySun(-0.05, h)[1]).toBe(skySun(0, h)[1]);
	});

	it('has no step and no kink at the horizon', () => {
		const e = 1e-6;
		expect(skySun(e, h)[0]).toBeCloseTo(skySun(-e, h)[0], 8);
		const slopeDay = (skySun(2 * e, h)[0] - skySun(e, h)[0]) / e;
		const slopeNight = (skySun(-e, h)[0] - skySun(-2 * e, h)[0]) / e;
		expect(Math.abs(slopeDay - slopeNight)).toBeLessThan(1e-3);
	});

	it('goes down past the horizon and is gone on the night side', () => {
		let last = skySun(0, h)[0];
		for (let deg = 1; deg <= 30; deg++) {
			const mu = skySun(-Math.sin((deg * Math.PI) / 180), h)[0];
			expect(mu).toBeLessThan(last);
			last = mu;
		}
		expect(skySun(-0.5, h)[0]).toBeLessThan(1e-12);
	});
});

describe('skyLightFraction', () => {
	it('sends half of a thin Rayleigh column down', () => {
		const tau = 1e-3;
		const air = {
			...BASE,
			rayleighScatterPerKm: [tau / 8, tau / 8, tau / 8] as [number, number, number]
		};
		// Bird and Riordan take 0.95 of the optical depth.
		for (const v of skyLightFraction(air, 0, 6000, 1))
			expect(v / (0.5 * 0.95 * tau)).toBeCloseTo(1, 2);
	});

	it('sends down about the forward hemisphere of a thin aerosol column under a high Sun', () => {
		const tau = 1e-3;
		const air = {
			...BASE,
			mieScatterPerKm: [tau / 8, tau / 8, tau / 8] as [number, number, number]
		};
		// The forward hemisphere of the table, from a midpoint sum over θ.
		const g = 0.7;
		let forward = 0;
		for (let i = 0; i < 20000; i++) {
			const t = ((i + 0.5) / 20000) * (Math.PI / 2);
			forward +=
				((1 - g * g) / (4 * Math.PI * (1 + g * g - 2 * g * Math.cos(t)) ** 1.5)) *
				2 *
				Math.PI *
				Math.sin(t) *
				(Math.PI / 2 / 20000);
		}
		expect(skyLightFraction(air, 0, 6000, 1)[1] / tau).toBeCloseTo(forward, 1);
	});

	it('is blue on the Earth and red on Mars', () => {
		const [er, eg, eb] = skyLightFraction(EARTH, 0, EARTH_KM, 1);
		expect(eb).toBeGreaterThan(eg);
		expect(eg).toBeGreaterThan(er);
		const [mr, mg, mb] = skyLightFraction(MARS, 0, MARS_KM, 1);
		expect(mr).toBeGreaterThan(mg);
		expect(mg).toBeGreaterThan(mb);
	});

	it('is a few percent of the sunlight where the column is thin', () => {
		expect(lum(skyLightFraction(PLUTO, 0, PLUTO_KM, 1))).toBeLessThan(0.02);
		expect(lum(skyLightFraction(EARTH, 0, EARTH_KM, 1))).toBeGreaterThan(0.05);
	});

	it('is less over a cloud deck than on the ground', () => {
		expect(lum(skyLightFraction(EARTH, 12, EARTH_KM, 1))).toBeLessThan(
			0.5 * lum(skyLightFraction(EARTH, 0, EARTH_KM, 1))
		);
	});

	it('goes on through twilight and then is gone', () => {
		const at = (deg: number) =>
			lum(skyLightFraction(MARS, 0, MARS_KM, Math.sin((deg * Math.PI) / 180)));
		expect(at(-0.001)).toBeCloseTo(at(0.001), 6);
		expect(at(-3)).toBeGreaterThan(0.2 * at(0));
		expect(at(-12)).toBeLessThan(0.01 * at(0));
		expect(at(-30)).toBeLessThan(1e-9);
		for (let deg = -20; deg < 90; deg++) expect(at(deg + 1)).toBeGreaterThan(at(deg));
	});
});

describe('skyLightSplit', () => {
	it('keeps the light on open ground at noon', () => {
		for (const [air, km] of [
			[EARTH, EARTH_KM],
			[MARS, MARS_KM],
			[PLUTO, PLUTO_KM]
		] as const) {
			const direct = new Vector3();
			const gain = new Vector3();
			skyLightSplit(air, 0, km, direct, gain);
			const sky = skyLightFraction(air, 0, km, 1);
			const tau =
				air.rayleighScatterPerKm[1] * air.rayleighScaleHeightKm +
				(air.mieScatterPerKm[1] + air.mieAbsorptionPerKm[1]) * air.mieScaleHeightKm +
				air.absorptionPerKm[1] * air.absorptionWidthKm;
			const now = Math.exp(-(1 - air.bakedCompensation) * tau);
			expect(direct.y * now + gain.y * sky[1]).toBeCloseTo(now, 10);
			// The sky light over the direct light is that of the column.
			expect((gain.y * sky[1]) / (direct.y * now)).toBeCloseTo(sky[1] / Math.exp(-tau), 10);
		}
	});

	it('gives no sky light to a shell with no ground under it', () => {
		const direct = new Vector3();
		const gain = new Vector3(1, 1, 1);
		skyLightSplit({ ...MARS, groundAlbedo: undefined }, 0, MARS_KM, direct, gain);
		expect(direct.toArray()).toEqual([1, 1, 1]);
		expect(gain.toArray()).toEqual([0, 0, 0]);
	});

	it('leaves the ground of a deep column to that column', () => {
		const direct = new Vector3();
		const gain = new Vector3(1, 1, 1);
		const deep = { n: 2, topKm: 60, fluxDown: [], fluxUpRatio: [], extinctionPerKm: [] };
		skyLightSplit({ ...MARS, deepColumn: deep }, 0, MARS_KM, direct, gain);
		expect(direct.toArray()).toEqual([1, 1, 1]);
		expect(gain.toArray()).toEqual([0, 0, 0]);
	});
});
