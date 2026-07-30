import { describe, expect, it } from 'vitest';
import {
	gradientStops,
	regimeFor,
	scalePosition,
	HABITABLE_RANGE_K
} from '$lib/math/temperature-scale';

describe('regimeFor', () => {
	it('keeps every solar-system surface on the planetary scale', () => {
		// Sedna (coldest carried) through Venus (hottest surface carried).
		expect(regimeFor([12])).toBe('planetary');
		expect(regimeFor([183.95, 288.15, 329.85])).toBe('planetary');
		expect(regimeFor([737.15])).toBe('planetary');
	});

	it('switches to stellar once any reading passes the planetary ceiling', () => {
		expect(regimeFor([1000])).toBe('planetary');
		expect(regimeFor([1001])).toBe('stellar');
		// The Sun's photosphere drags its whole bar onto the stellar scale.
		expect(regimeFor([5772, 2e6, 1.571e7])).toBe('stellar');
	});
});

describe('scalePosition', () => {
	it('is linear across the planetary domain', () => {
		expect(scalePosition(0, 'planetary')).toBe(0);
		expect(scalePosition(500, 'planetary')).toBe(0.5);
		expect(scalePosition(1000, 'planetary')).toBe(1);
	});

	it('is logarithmic across the stellar domain', () => {
		expect(scalePosition(1e3, 'stellar')).toBe(0);
		expect(scalePosition(1e8, 'stellar')).toBe(1);
		// Each decade is a fifth of the bar.
		expect(scalePosition(1e4, 'stellar')).toBeCloseTo(0.2);
		expect(scalePosition(1e6, 'stellar')).toBeCloseTo(0.6);
	});

	it('clamps out-of-domain readings to the ends', () => {
		expect(scalePosition(-50, 'planetary')).toBe(0);
		expect(scalePosition(5000, 'planetary')).toBe(1);
		// Below the stellar floor: log of a smaller value must not go negative.
		expect(scalePosition(300, 'stellar')).toBe(0);
		expect(scalePosition(1e12, 'stellar')).toBe(1);
	});

	it('spreads the three solar readings across the stellar bar', () => {
		const [photosphere, corona, core] = [5772, 2e6, 1.571e7].map((k) =>
			scalePosition(k, 'stellar')
		);
		expect(photosphere).toBeGreaterThan(0.1);
		expect(photosphere).toBeLessThan(corona);
		expect(corona).toBeLessThan(core);
		expect(core).toBeLessThan(1);
	});
});

describe('gradientStops', () => {
	it('parks the green plateau on the liquid-water band', () => {
		const stops = gradientStops('planetary');
		const green = stops.filter((s) => s.color === stops[2].color);
		expect(green).toHaveLength(2);
		expect(green[0].at).toBeCloseTo(scalePosition(HABITABLE_RANGE_K[0], 'planetary'));
		expect(green[1].at).toBeCloseTo(scalePosition(HABITABLE_RANGE_K[1], 'planetary'));
	});

	it('emits stops in ascending order spanning the full bar', () => {
		for (const regime of ['planetary', 'stellar'] as const) {
			const stops = gradientStops(regime);
			expect(stops[0].at).toBe(0);
			expect(stops[stops.length - 1].at).toBe(1);
			for (let i = 1; i < stops.length; i++) {
				expect(stops[i].at).toBeGreaterThanOrEqual(stops[i - 1].at);
			}
		}
	});
});
