import { describe, expect, it } from 'vitest';
import { AU_KM, KM_PER_PC } from '$lib/math/units';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { STARS_IN_AU } from '$lib/scene/starfield/band';
import {
	CENTRE_FAR_POWER,
	CENTRE_LEAST_GAIN,
	FAR_FROM_PC,
	FAR_FULL_PC,
	JOIN_FULL_PC,
	OUTSIDE_GAIN_MAG,
	PLACE_GAIN_MAG,
	joinShare,
	placeGain
} from './exposure';

/** The Galactic centre of the model, on nest axes. */
const CENTRE: Vec3 = [8_277, 0, -21];

describe('placeGain', () => {
	const join = (STARS_IN_AU * AU_KM) / KM_PER_PC;
	const mag = (gain: number) => 2.5 * Math.log10(gain);
	const fromCentre = (d: number, dir: Vec3 = [0, -1, 0]): Vec3 => [
		CENTRE[0] + d * dir[0],
		CENTRE[1] + d * dir[1],
		CENTRE[2] + d * dir[2]
	];

	it('is one at the join and inside it, and rises with no step past it', () => {
		expect(placeGain([0, 0, 0], CENTRE)).toBe(1);
		expect(placeGain([join, 0, 0], CENTRE)).toBe(1);
		expect(placeGain([0, 0, -join], CENTRE)).toBe(1);
		expect(placeGain([-join * (1 + 1e-4), 0, 0], CENTRE) - 1).toBeLessThan(1e-8);
	});

	it('rises with distance in the plane to the band’s gain deep in the disc', () => {
		expect(mag(placeGain([-1, 0, 0], null))).toBeCloseTo(PLACE_GAIN_MAG * joinShare(1), 6);
		expect(mag(placeGain([-JOIN_FULL_PC, 0, 0], null))).toBeCloseTo(PLACE_GAIN_MAG, 6);
		expect(mag(placeGain([-100, 0, 10], null))).toBeGreaterThan(PLACE_GAIN_MAG - 0.02);
		expect(mag(placeGain([-1000, 300, 100], null))).toBeGreaterThan(PLACE_GAIN_MAG - 0.01);
		let last = 1;
		for (let d = 1e-3; d < 2e4; d *= 1.2) {
			const gain = placeGain([d, 0, 0], null);
			expect(gain).toBeGreaterThanOrEqual(last);
			expect(mag(gain)).toBeLessThanOrEqual(PLACE_GAIN_MAG + 1e-12);
			last = gain;
		}
	});

	it('rises with the march’s share, so a zoom out never dims the sky the march takes over', () => {
		// The march over the sky from the Sun toward the centre, where it holds least.
		const ratio = 0.41;
		let last = 0;
		for (let d = join; d < 2 * JOIN_FULL_PC; d *= 1.05) {
			const j = joinShare(d);
			const sky = placeGain([d, 0, 0], null) * (j * ratio + 1 - j);
			expect(sky).toBeGreaterThanOrEqual(last);
			last = sky;
		}
	});

	it('falls with height above the plane in the disc', () => {
		expect(placeGain([0, 0, 8000], null)).toBeLessThan(1.4);
		expect(placeGain([0, 0, -8000], null)).toBe(placeGain([0, 0, 8000], null));
	});

	it('rises with the distance from the Galactic centre past the Sun’s, and falls nearer it', () => {
		const centre = (at: Vec3) => placeGain(at, CENTRE) / placeGain(at, null);
		// Within the disc the part far outside is 1, so this is the centre's part.
		expect(centre(fromCentre(12_000, [-1, 0, 0]))).toBeCloseTo(
			(12_000 / Math.hypot(...CENTRE)) ** CENTRE_FAR_POWER,
			3
		);
		expect(centre([5_000, 0, 30])).toBeLessThan(1);
		expect(centre([8_000, 0, 0])).toBeGreaterThanOrEqual(CENTRE_LEAST_GAIN);
		let last = 0;
		for (let d = 500; d < 8_000; d += 100) {
			const gain = centre(fromCentre(d, [-1, 0, 0]));
			expect(gain).toBeGreaterThanOrEqual(last);
			last = gain;
		}
	});

	it('rises far outside the Galaxy with no step, then holds, so the Galaxy keeps its brightness as it shrinks', () => {
		const outside = (d: number) => placeGain(fromCentre(d, [0, 0, 1]), CENTRE);
		let last = outside(FAR_FROM_PC);
		for (let d = FAR_FROM_PC; d <= FAR_FULL_PC; d += 100) {
			const gain = outside(d);
			expect(gain).toBeGreaterThanOrEqual(last);
			expect(mag(gain / last)).toBeLessThan(0.03);
			last = gain;
		}
		const full = outside(FAR_FULL_PC);
		// The disc's part, a few percent at 30 kpc above it, is all that changes.
		expect(Math.abs(mag(outside(1e5) / full))).toBeLessThan(0.03);
		expect(mag(full / placeGain(fromCentre(FAR_FULL_PC, [0, 0, 1]), null))).toBeCloseTo(
			OUTSIDE_GAIN_MAG + mag(FAR_FULL_PC / Math.hypot(...CENTRE)),
			3
		);
		// The views of the disc, 8 kpc above the Sun included, take no part of it.
		for (const view of [
			[-1000, 300, 100],
			[5000, 0, 30],
			[0, 0, 8000]
		] as const) {
			const d = Math.hypot(view[0] - CENTRE[0], view[1] - CENTRE[1], view[2] - CENTRE[2]);
			expect(d).toBeLessThan(FAR_FROM_PC);
		}
	});

	it('takes the Galactic centre from the model, and has the disc’s gain alone without one', () => {
		const moved: Vec3 = [CENTRE[0] + 5_000, CENTRE[1] - 2_000, CENTRE[2]];
		const at: Vec3 = [-3_000, 22_000, 400];
		expect(placeGain(at, CENTRE)).not.toBeCloseTo(placeGain(at, moved), 3);
		expect(placeGain(at, null)).toBeCloseTo(
			10 ** ((0.4 * PLACE_GAIN_MAG) / (1 + (400 / 4_000) ** 2)),
			5
		);
	});
});

describe('joinShare', () => {
	const join = (STARS_IN_AU * AU_KM) / KM_PER_PC;

	it('is 0 at the join and inside it, so the sky past it starts as the one inside', () => {
		expect(joinShare(0)).toBe(0);
		expect(joinShare(join)).toBe(0);
		expect(joinShare(join * 1.001)).toBeLessThan(1e-5);
	});

	it('rises with no step to 1 at its full distance, and holds past it', () => {
		let last = 0;
		for (let d = join; d <= JOIN_FULL_PC; d *= 1.05) {
			const share = joinShare(d);
			expect(share).toBeGreaterThanOrEqual(last);
			expect(share - last).toBeLessThan(0.02);
			last = share;
		}
		expect(joinShare(JOIN_FULL_PC)).toBe(1);
		expect(joinShare(1e6)).toBe(1);
	});
});
