import { describe, it, expect } from 'vitest';
import { G0_M_S2 } from '$lib/math/travel/constants';
import {
	dvParts,
	formatAcceleration,
	formatDv,
	formatDvBrief,
	formatSpeed,
	lightPercent
} from './format';

describe('formatAcceleration', () => {
	it('quotes a drive you could stand up in as a fraction of a gravity', () => {
		expect(formatAcceleration(G0_M_S2 / 3)).toBe('0.33 g');
		expect(formatAcceleration(G0_M_S2 * 1.5)).toBe('1.5 g');
	});

	// A hundredth of a gravity is where the fraction stops saying anything.
	it('drops to m/s² for a drive you would never feel', () => {
		expect(formatAcceleration(0.002)).toBe('0.002 m/s²');
	});

	it('refuses to render an acceleration that is not one', () => {
		expect(formatAcceleration(0)).toBe('—');
		expect(formatAcceleration(NaN)).toBe('—');
	});
});

describe('formatDv', () => {
	it('stays in km/s below ten thousand of them', () => {
		expect(formatDv(9999.99)).toBe('9,999.99 km/s');
		expect(formatDvBrief(7586.04)).toBe('7,586.0 km/s');
		expect(dvParts(7586.04)).toEqual({ value: '7,586.0', unit: 'km/s' });
	});

	it('climbs to Mm/s where six figures of km/s would not fit', () => {
		expect(formatDv(62500)).toBe('62.5 Mm/s');
		expect(formatDvBrief(125_000)).toBe('125 Mm/s');
		expect(dvParts(1_250_000)).toEqual({ value: '1,250', unit: 'Mm/s' });
	});
});

describe('formatSpeed', () => {
	it('stays in km/s below a hundredth of c', () => {
		expect(formatSpeed(993)).toBe('993.00 km/s');
		expect(lightPercent(993)).toBeNull();
	});

	it('flips to a percentage of c from 1% up', () => {
		expect(formatSpeed(2997.92458)).toBe('1% c');
		expect(formatSpeed(6500)).toBe('2.2% c');
	});

	// Newtonian arithmetic on a fictional drive can pass c; the figure is the
	// model's honest output, so it is shown rather than capped.
	it('does not cap a superluminal figure', () => {
		expect(formatSpeed(449688.687)).toBe('150% c');
	});

	it('refuses to render a nonsense speed', () => {
		expect(formatSpeed(NaN)).toBe('—');
	});
});
