import { describe, it, expect } from 'vitest';
import { EARTH, ESCAPING_PROBE, JUPITER, MARS } from '$lib/math/travel/test-fixtures';
import { crossingTimeDays, hohmannTransferDays, synodicPeriodDays } from '$lib/math/travel';
import { searchWindow } from './search-window';

const NOW = 2461000;

describe('searchWindow', () => {
	it('spans a synodic period so a window is always inside the grid', () => {
		const options = searchWindow({ origin: EARTH, target: MARS, nowJd: NOW, timeMode: 'now' })!;
		const synodic = synodicPeriodDays(EARTH, MARS)!;
		expect(options.departFromJd).toBe(NOW);
		expect(options.departToJd - options.departFromJd).toBeCloseTo(synodic, 0);
	});

	it('brackets the Hohmann time with the cruise bounds', () => {
		const options = searchWindow({ origin: EARTH, target: MARS, nowJd: NOW, timeMode: 'now' })!;
		const hohmann = hohmannTransferDays(EARTH, MARS)!;
		expect(options.tofMinDays).toBeLessThan(hohmann);
		expect(options.tofMaxDays).toBeGreaterThan(hohmann);
	});

	it('caps the search for a slow pair rather than gridding a decade', () => {
		const options = searchWindow({ origin: EARTH, target: JUPITER, nowJd: NOW, timeMode: 'now' })!;
		expect(options.departToJd - options.departFromJd).toBeLessThanOrEqual(3 * 365.25 + 1);
	});

	it('centres on a chosen departure date', () => {
		const picked = NOW + 500;
		const options = searchWindow({
			origin: EARTH,
			target: MARS,
			nowJd: NOW,
			timeMode: 'depart',
			pickedJd: picked
		})!;
		expect((options.departFromJd + options.departToJd) / 2).toBeCloseTo(picked, 6);
	});

	it('never searches departures already in the past', () => {
		const options = searchWindow({
			origin: EARTH,
			target: MARS,
			nowJd: NOW,
			timeMode: 'depart',
			pickedJd: NOW + 5
		})!;
		expect(options.departFromJd).toBeGreaterThanOrEqual(NOW);
	});

	it('stops departures early enough to meet an arrival deadline', () => {
		const deadline = NOW + 400;
		const options = searchWindow({
			origin: EARTH,
			target: MARS,
			nowJd: NOW,
			timeMode: 'arrive',
			pickedJd: deadline
		})!;
		// The last departure plus the shortest cruise still lands by the deadline.
		expect(options.departToJd + options.tofMinDays).toBeLessThanOrEqual(deadline + 1e-6);
	});

	it('always yields a non-empty departure range', () => {
		const options = searchWindow({
			origin: EARTH,
			target: MARS,
			nowJd: NOW,
			timeMode: 'arrive',
			pickedJd: NOW - 100
		})!;
		expect(options.departToJd).toBeGreaterThan(options.departFromJd);
	});

	// An escaping probe used to fall out here: no semi-major axis, no Hohmann
	// time, no grid, and the panel said the pair had no orbit at all.
	describe('chasing an unbound target', () => {
		const chase = { origin: EARTH, target: ESCAPING_PROBE, nowJd: NOW, timeMode: 'now' as const };

		it('still produces a grid', () => {
			expect(searchWindow(chase)).not.toBeNull();
		});

		it('opens the cruise bounds well below the crossing time', () => {
			const options = searchWindow(chase)!;
			const crossing = crossingTimeDays(EARTH, ESCAPING_PROBE, NOW)!;
			// The target is leaving, so the arcs worth seeing are the fast ones; a
			// planetary 0.35 floor would put the whole grid past a century out.
			expect(options.tofMinDays).toBeLessThan(crossing * 0.1);
			expect(options.tofMaxDays).toBeGreaterThan(options.tofMinDays);
		});

		it('searches departures over the cap, having no alignment to wait for', () => {
			const options = searchWindow(chase)!;
			expect(options.departToJd - options.departFromJd).toBeCloseTo(3 * 365.25, 0);
		});
	});

	it('returns null when a body has no usable orbit', () => {
		const broken = { ...MARS, elements: { ...MARS.elements, a: NaN } };
		expect(searchWindow({ origin: EARTH, target: broken, nowJd: NOW, timeMode: 'now' })).toBeNull();
	});
});
