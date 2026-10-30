import { describe, expect, it } from 'vitest';
import { PerspectiveCamera, Vector3 } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import {
	narrowHalfFov,
	openArea,
	tripVantage,
	type OpenArea,
	type ScreenInsets,
	type TripCamera
} from './trip-view';

/** One light-year in scene units (1 AU = 10). */
const LY = 632_410;
const WIDE = 16 / 9;
const HALF_FOV = narrowHalfFov(60, WIDE);
const NORTH: Vec3 = [0, 1, 0];
const ALL_OPEN: OpenArea = { top: 1, right: 1, bottom: 1, left: 1 };
/** A desktop page on a trip: the sidebar, the chips and the trip timeline. */
const DESKTOP: ScreenInsets = { top: 64, right: 72, bottom: 272, left: 390 };

function camera(aspect = WIDE, open = ALL_OPEN): TripCamera {
	return { fovDeg: 60, aspect, up: NORTH, open };
}

/** The angle at the camera between the target and the origin, rad. */
function seen(target: Vec3, origin: Vec3, at: Vec3): number {
	const a = target.map((v, i) => v - at[i]);
	const b = origin.map((v, i) => v - at[i]);
	const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
	return Math.acos(dot / (Math.hypot(...a) * Math.hypot(...b)));
}

/** Where three.js draws `point` from a camera at `offset` from `target`, looking at it. */
function drawn(point: Vec3, target: Vec3, offset: Vec3, aspect = WIDE): Vector3 {
	const lens = new PerspectiveCamera(60, aspect, 1, 1e12);
	lens.up.set(...NORTH);
	lens.position.set(...offset);
	lens.lookAt(0, 0, 0);
	lens.updateMatrixWorld();
	return new Vector3(point[0] - target[0], point[1] - target[1], point[2] - target[2]).project(
		lens
	);
}

function plus(a: Vec3, b: Vec3): Vec3 {
	return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

describe('tripVantage', () => {
	const SUN: Vec3 = [0, 0, 0];
	// 4.24 ly away at ecliptic longitude 239°, latitude −44.8°. Scene axes are
	// ecliptic x, ecliptic z (north) and minus ecliptic y.
	const PROXIMA: Vec3 = [-0.3655 * 4.24 * LY, -0.7046 * 4.24 * LY, 0.6082 * 4.24 * LY];
	const AT_EARTH: Vec3 = [10, 0, 0];

	it('leaves the solar system to show both ends from the side', () => {
		const vantage = tripVantage(PROXIMA, SUN, AT_EARTH, camera())!;
		expect(vantage.kept).toBe(false);
		const at = plus(PROXIMA, vantage.offset);
		expect(seen(PROXIMA, SUN, at)).toBeCloseTo(0.7 * HALF_FOV, 9);
		const length = Math.hypot(...PROXIMA);
		expect(Math.hypot(...vantage.offset)).toBeGreaterThan(length);
		// Off the line, so the line is not seen end on.
		const along = PROXIMA.map((v) => -v / length);
		const out = vantage.offset.map((v) => v / Math.hypot(...vantage.offset));
		const cos = along[0] * out[0] + along[1] * out[1] + along[2] * out[2];
		expect(Math.acos(cos)).toBeCloseTo(Math.PI / 3, 9);
	});

	it('stays at a vantage that already shows the trip', () => {
		const first = tripVantage(PROXIMA, SUN, AT_EARTH, camera())!;
		const at = plus(PROXIMA, first.offset);
		const again = tripVantage(PROXIMA, SUN, at, camera())!;
		expect(again.kept).toBe(true);
		expect(again.offset.map((v, i) => v - first.offset[i]).every((d) => Math.abs(d) < 1)).toBe(
			true
		);
	});

	it('moves out when the origin would be off the screen, or a speck', () => {
		const length = Math.hypot(...PROXIMA);
		const side: Vec3 = [0, length * 0.6, 0];
		expect(tripVantage(PROXIMA, SUN, plus(PROXIMA, side), camera())!.kept).toBe(false);
		const far: Vec3 = [0, length * 1000, 0];
		expect(tripVantage(PROXIMA, SUN, plus(PROXIMA, far), camera())!.kept).toBe(false);
	});

	it('goes north of the line when the camera is on it', () => {
		const target: Vec3 = [4 * LY, 0, 0];
		const vantage = tripVantage(target, SUN, [-LY, 0, 0], camera())!;
		expect(vantage.offset[1]).toBeGreaterThan(0);
		expect(Math.abs(vantage.offset[2])).toBeLessThan(1e-6);
	});

	it('keeps to the side of the line the camera is on', () => {
		const target: Vec3 = [4 * LY, 0, 0];
		const vantage = tripVantage(target, SUN, [2 * LY, 0, -LY], camera())!;
		expect(vantage.offset[2]).toBeLessThan(0);
	});

	it('stands farther out on a screen taller than it is wide', () => {
		const wide = tripVantage(PROXIMA, SUN, AT_EARTH, camera(WIDE))!;
		const tall = tripVantage(PROXIMA, SUN, AT_EARTH, camera(9 / 19.5))!;
		expect(Math.hypot(...tall.offset)).toBeGreaterThan(1.5 * Math.hypot(...wide.offset));
	});

	it('has nothing to show when the two ends are in one place', () => {
		expect(tripVantage(SUN, SUN, AT_EARTH, camera())).toBeNull();
	});

	describe('beside the page', () => {
		const open = openArea(DESKTOP, 1920, 1080);
		/** The bottom of the open area in normalised device units. */
		const floor = -open.bottom;

		/** On the line, past the Sun: a new vantage starts from north of the line. */
		const ON_LINE: Vec3 = [-PROXIMA[0] * 1e-5, -PROXIMA[1] * 1e-5, -PROXIMA[2] * 1e-5];

		it('keeps the origin clear of the timeline when it lies south of the target', () => {
			// Proxima to Earth: from Earth, Proxima is 44° south of the ecliptic, so
			// from north of the line it is straight under the target.
			const bare = tripVantage(SUN, PROXIMA, ON_LINE, camera())!;
			expect(drawn(PROXIMA, SUN, bare.offset).y).toBeLessThan(floor);

			const vantage = tripVantage(SUN, PROXIMA, ON_LINE, camera(WIDE, open))!;
			const origin = drawn(PROXIMA, SUN, vantage.offset);
			expect(origin.z).toBeLessThan(1);
			expect(origin.y).toBeGreaterThanOrEqual(floor - 1e-9);
			expect(origin.x).toBeGreaterThanOrEqual(-open.left - 1e-9);
			expect(origin.x).toBeLessThanOrEqual(open.right + 1e-9);
			expect(origin.y).toBeLessThanOrEqual(open.top + 1e-9);
			// Still at the vantage angle, and not shrunk to a speck.
			expect(seen(SUN, PROXIMA, vantage.offset)).toBeGreaterThan(0.25 * HALF_FOV);
		});

		it('frames a trip as close as the open area lets it', () => {
			const bare = tripVantage(PROXIMA, SUN, AT_EARTH, camera())!;
			const vantage = tripVantage(PROXIMA, SUN, AT_EARTH, camera(WIDE, open))!;
			// From Proxima the Sun is to the north: there is room above the target.
			expect(Math.hypot(...vantage.offset)).toBeCloseTo(Math.hypot(...bare.offset), 3);
			const origin = drawn(SUN, PROXIMA, vantage.offset);
			expect(origin.y).toBeGreaterThan(floor);
		});

		it('moves a camera that shows the origin under the page', () => {
			const bare = tripVantage(SUN, PROXIMA, ON_LINE, camera())!;
			expect(tripVantage(SUN, PROXIMA, bare.offset, camera())!.kept).toBe(true);
			expect(tripVantage(SUN, PROXIMA, bare.offset, camera(WIDE, open))!.kept).toBe(false);
		});

		it('keeps a camera that shows the trip clear of it', () => {
			const first = tripVantage(SUN, PROXIMA, ON_LINE, camera(WIDE, open))!;
			expect(tripVantage(SUN, PROXIMA, first.offset, camera(WIDE, open))!.kept).toBe(true);
		});
	});
});

describe('openArea', () => {
	it('gives the share of each half of the screen that is open, less room for labels', () => {
		const open = openArea({ top: 0, right: 0, bottom: 500, left: 0 }, 1000, 1080);
		expect(open.bottom).toBeCloseTo(0, 9);
		expect(open.top).toBeCloseTo(1 - 80 / 1080, 9);
		expect(open.left).toBeCloseTo(1 - 80 / 1000, 9);
		// A label runs to the right of its point.
		expect(open.right).toBeLessThan(open.left);
	});

	it('is never less than nothing', () => {
		expect(openArea({ top: 0, right: 0, bottom: 900, left: 0 }, 1000, 1000).bottom).toBe(0);
	});
});
