import { describe, it, expect } from 'vitest';
import {
	EARTH,
	ESCAPING_PROBE,
	JUPITER,
	LONG_PERIOD_COMET,
	MARS,
	MOON,
	PARABOLIC_COMET
} from '$lib/math/travel/test-fixtures';
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

	it('starts at a chosen departure date and searches forward from it', () => {
		const picked = NOW + 500;
		const options = searchWindow({
			origin: EARTH,
			target: MARS,
			nowJd: NOW,
			timeMode: 'depart',
			pickedJd: picked
		})!;
		const synodic = synodicPeriodDays(EARTH, MARS)!;
		expect(options.departFromJd).toBe(picked);
		expect(options.departToJd - options.departFromJd).toBeCloseTo(synodic, 0);
	});

	// The clock is a place to stand, not a floor: a reader who has wound it
	// forward and then asks about a launch behind it is asking about that launch.
	it('searches from a departure date behind the clock', () => {
		const picked = NOW - 500;
		const options = searchWindow({
			origin: EARTH,
			target: MARS,
			nowJd: NOW,
			timeMode: 'depart',
			pickedJd: picked
		})!;
		expect(options.departFromJd).toBe(picked);
		expect(options.departToJd).toBeGreaterThan(picked);
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

	it('grids no cruise that outlasts the deadline', () => {
		const deadline = NOW + 400;
		const options = searchWindow({
			origin: EARTH,
			target: MARS,
			nowJd: NOW,
			timeMode: 'arrive',
			pickedJd: deadline
		})!;
		expect(options.deadlineJd).toBe(deadline);
		expect(options.departFromJd + options.tofMaxDays).toBeLessThanOrEqual(deadline + 1e-6);
	});

	// Shaping the axes to an impossible deadline would leave nothing to search,
	// and "no route arrives in time" has to be found rather than assumed.
	it('keeps the open bounds when the deadline is too soon to shape them', () => {
		const options = searchWindow({
			origin: EARTH,
			target: MARS,
			nowJd: NOW,
			timeMode: 'arrive',
			pickedJd: NOW + 5
		})!;
		const open = searchWindow({ origin: EARTH, target: MARS, nowJd: NOW, timeMode: 'now' })!;
		expect(options.tofMaxDays).toBe(open.tofMaxDays);
		expect(options.deadlineJd).toBe(NOW + 5);
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

	// An escaping probe has no semi-major axis and no Hohmann time, which must
	// not read as "no grid" — the pair does have an orbit to search.
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

		// Most of the comet catalogue is fitted as a parabola, which reaches the
		// same chase path from the other side: a and n are zero rather than
		// unbound, and the geometry comes from q and tp instead.
		it('takes the same path for a parabolic comet', () => {
			const options = searchWindow({ ...chase, target: PARABOLIC_COMET })!;
			const crossing = crossingTimeDays(EARTH, PARABOLIC_COMET, NOW)!;
			expect(options.tofMinDays).toBeLessThan(crossing * 0.1);
			expect(options.tofMaxDays).toBeGreaterThan(options.tofMinDays);
		});

		// The rest of it is fitted as an ellipse with a semi-major axis in the
		// thousands of AU. That is a closed orbit on paper, so the grid took its
		// Hohmann time and offered nothing under seven thousand years.
		it('grids the crossing, not the 123,000-year orbit, for a long-period comet', () => {
			const options = searchWindow({ ...chase, target: LONG_PERIOD_COMET })!;
			expect(options.tofMaxDays / 365.25).toBeLessThan(20);
			expect(options.tofMinDays).toBeGreaterThan(0);
		});
	});

	// Having no window to wait for doesn't make the date nothing to wait for:
	// it's a floor here as much as it is between planets.
	it('starts an in-system search at a chosen departure date too', () => {
		const picked = NOW + 200;
		const options = searchWindow({
			origin: EARTH,
			target: MOON,
			nowJd: NOW,
			timeMode: 'depart',
			pickedJd: picked,
			systemPrimary: 'departure'
		})!;
		expect(options.departFromJd).toBe(picked);
		expect(options.departToJd).toBeGreaterThan(picked);
	});

	it('returns null when a body has no usable orbit', () => {
		const broken = { ...MARS, elements: { ...MARS.elements, a: NaN } };
		expect(searchWindow({ origin: EARTH, target: broken, nowJd: NOW, timeMode: 'now' })).toBeNull();
	});
});
