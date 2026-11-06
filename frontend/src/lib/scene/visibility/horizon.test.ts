import { describe, expect, it } from 'vitest';
import { behindGround } from './horizon';

const R = 3390;

/** A point `heightKm` over a sphere of radius R, `deg` round from +x. */
function at(deg: number, heightKm = 0): [number, number, number] {
	const a = (deg * Math.PI) / 180;
	return [(R + heightKm) * Math.cos(a), (R + heightKm) * Math.sin(a), 0];
}

describe('behindGround', () => {
	it('hides a point on the ground past the horizon', () => {
		// 4 km up, the horizon is ~165 km off: 600 km round is past it.
		expect(behindGround(...at(600 / R / (Math.PI / 180)), ...at(0, 4))).toBe(true);
	});

	it('shows a point on the ground short of the horizon', () => {
		expect(behindGround(...at(100 / R / (Math.PI / 180)), ...at(0, 4))).toBe(false);
	});

	it('matches the tangent-plane test for a point on the sphere', () => {
		for (const deg of [10, 60, 80, 89, 91, 120, 179]) {
			const p = at(deg);
			const c: [number, number, number] = [2 * R, 0, 0];
			const tangent = p[0] * c[0] + p[1] * c[1] <= R * R;
			expect(behindGround(...p, ...c)).toBe(tangent);
		}
	});

	it('lets a camera in a basin see a lander up on the rim', () => {
		expect(behindGround(...at(0.05, 2), ...at(0, -3))).toBe(false);
	});

	it('hides an orbiter behind the body from a camera on the ground', () => {
		expect(behindGround(...at(180, 400), ...at(0, 0.05), R)).toBe(true);
		expect(behindGround(...at(10, 400), ...at(0, 0.05), R)).toBe(false);
	});

	it('tests an orbiter seen from afar against the ground, not its own orbit', () => {
		// Camera 7000 km out, orbiter 6000 km up 90° round: clear of the ground.
		const orbiter: [number, number, number] = [0, R + 6000, 0];
		const camera: [number, number, number] = [R + 7000, 0, 0];
		expect(behindGround(...orbiter, ...camera, R)).toBe(false);
	});
});
