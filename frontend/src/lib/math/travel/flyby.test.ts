import { describe, it, expect } from 'vitest';
import { minFlybyRadiusKm, solveFlyby, turnAngleRad } from './flyby';
import { JUPITER, MARS } from './test-fixtures';
import { scale, type Vec3 } from './vec3';

const DEG = Math.PI / 180;

/** A vector of the given speed, turned `deg` from +X in the XY plane. */
function at(speedKms: number, deg: number): Vec3 {
	return [speedKms * Math.cos(deg * DEG), speedKms * Math.sin(deg * DEG), 0];
}

describe('turnAngleRad', () => {
	it('turns further the closer and the slower the pass', () => {
		const close = turnAngleRad(JUPITER.mu, 100_000, 6);
		const far = turnAngleRad(JUPITER.mu, 2_000_000, 6);
		const slow = turnAngleRad(JUPITER.mu, 100_000, 3);
		expect(close).toBeGreaterThan(far);
		expect(slow).toBeGreaterThan(close);
	});

	it('falls to nothing at infinite distance and never reaches half a turn', () => {
		expect(turnAngleRad(JUPITER.mu, 1e12, 6)).toBeLessThan(1e-3);
		expect(turnAngleRad(JUPITER.mu, 1, 0.001)).toBeLessThan(Math.PI);
	});

	it('is the angle between the asymptotes of the hyperbola it describes', () => {
		// e = 1 + r·v∞²/μ, and the turn is 2·asin(1/e) by definition of the asymptote.
		const r = 500_000;
		const v = 7;
		const e = 1 + (r * v * v) / JUPITER.mu;
		expect(turnAngleRad(JUPITER.mu, r, v)).toBeCloseTo(2 * Math.asin(1 / e), 12);
	});

	it('says nothing turns without a mass, a distance or a speed', () => {
		expect(turnAngleRad(0, 500_000, 6)).toBe(0);
		expect(turnAngleRad(JUPITER.mu, 0, 6)).toBe(0);
		expect(turnAngleRad(JUPITER.mu, 500_000, 0)).toBe(0);
	});
});

describe('solveFlyby', () => {
	it('is free when only the direction changes', () => {
		const pass = solveFlyby(JUPITER, at(6, 0), at(6, 40))!;
		expect(pass).not.toBeNull();
		expect(pass.dvKms).toBeCloseTo(0, 9);
		expect(pass.turnRad).toBeCloseTo(40 * DEG, 9);
	});

	it('picks the radius that delivers exactly the turn asked of it', () => {
		const pass = solveFlyby(JUPITER, at(6, 0), at(6, 40))!;
		// Same speed either side, so the two branches turn equally: each supplies
		// half, and together they are the angle between the two asymptotes.
		expect(turnAngleRad(JUPITER.mu, pass.periapsisKm, 6)).toBeCloseTo(40 * DEG, 6);
	});

	it('passes closer for a sharper turn', () => {
		const gentle = solveFlyby(JUPITER, at(6, 0), at(6, 20))!;
		const sharp = solveFlyby(JUPITER, at(6, 0), at(6, 80))!;
		expect(sharp.periapsisKm).toBeLessThan(gentle.periapsisKm);
	});

	it('charges for the speed the geometry cannot supply', () => {
		const pass = solveFlyby(JUPITER, at(6, 0), at(8, 40))!;
		expect(pass.dvKms).toBeGreaterThan(0);
		// The burn is at periapsis, where the craft is going far faster than v∞, so
		// it buys the 2 km/s difference for much less than 2 km/s.
		expect(pass.dvKms).toBeLessThan(2);
	});

	it('refuses a turn the body cannot make', () => {
		// Mars is small and 20 km/s is fast: even grazing the atmosphere bends this
		// by a couple of degrees, nowhere near the 90° asked for.
		expect(solveFlyby(MARS, at(20, 0), at(20, 90))).toBeNull();
		// The same turn at a speed it can handle is fine.
		expect(solveFlyby(MARS, at(2, 0), at(2, 90))).not.toBeNull();
	});

	it('keeps every pass clear of the body', () => {
		const pass = solveFlyby(MARS, at(1.5, 0), at(1.5, 100))!;
		expect(pass.periapsisKm).toBeGreaterThanOrEqual(minFlybyRadiusKm(MARS));
		expect(pass.periapsisKm).toBeGreaterThan(MARS.radiusKm);
	});

	it('does not credit a pass beyond the sphere of influence', () => {
		const ceiling = 1e6;
		const pass = solveFlyby(JUPITER, at(6, 0), at(6, 0.01), ceiling)!;
		expect(pass.periapsisKm).toBeLessThanOrEqual(ceiling);
	});

	it('has nothing to say without a velocity on both sides', () => {
		expect(solveFlyby(JUPITER, [0, 0, 0], at(6, 40))).toBeNull();
		expect(solveFlyby(JUPITER, at(6, 0), scale(at(6, 40), 0))).toBeNull();
	});
});
