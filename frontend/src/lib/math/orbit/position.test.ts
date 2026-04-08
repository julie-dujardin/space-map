import { describe, it, expect, vi } from 'vitest';
import { ELLIPTIC_ORBITS, EMB, CATALINA_HYP } from './test-helpers';

vi.mock('$lib/format/date', () => ({
	dateToJD: (d: Date) => d.getTime() / 86400000 + 2440587.5
}));

import { orbitalElementsToPosition } from './position';

const AU_SCALE = 10;

describe('orbitalElementsToPosition', () => {
	it.each(ELLIPTIC_ORBITS)('returns finite position for $name', ({ el }) => {
		const pos = orbitalElementsToPosition(el);
		expect(pos).not.toBeNull();
		expect(pos!.every(isFinite)).toBe(true);
	});

	it('Earth-Moon Barycenter is near 1 AU from origin', () => {
		const pos = orbitalElementsToPosition(EMB)!;
		const r = Math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2) / AU_SCALE;
		expect(r).toBeGreaterThan(0.95);
		expect(r).toBeLessThan(1.05);
	});

	it('returns finite position for Catalina (hyperbolic)', () => {
		const pos = orbitalElementsToPosition(CATALINA_HYP);
		expect(pos).not.toBeNull();
	});
});
