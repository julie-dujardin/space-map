import { describe, it, expect } from 'vitest';
import { busiestPad, isLaunchSiteSlug, padAt, padsOf } from './launch-pad';
import type { GcatSite } from '$lib/fetch/groups/details';

/** The Eastern Range as the export describes it: one collection, three places,
 *  each with its own pads — which is the case a single pin would misrepresent. */
const EASTERN_RANGE: GcatSite[] = [
	{
		code: 'CC',
		name: 'Cape Canaveral',
		launches: 700,
		pads: [
			{
				code: 'LC40',
				name: 'Space Launch Complex 40, Cape Canaveral',
				label: 'Space Launch Complex 40',
				lat: 28.5619,
				lon: -80.5772,
				launches: 300
			},
			{ code: 'LC41', name: 'Cape Canaveral SLC-41', lat: 28.5833, lon: -80.5831, launches: 100 }
		]
	},
	{
		code: 'KSC',
		name: 'Kennedy Space Center',
		launches: 200,
		pads: [
			{ code: 'LC39A', name: 'Kennedy LC-39A', lat: 28.6084, lon: -80.6041, launches: 180 },
			// GCAT names pads it has never attributed a launch to, and one it cannot
			// place at all.
			{ code: 'LC39C', name: 'Kennedy LC-39C', lat: 28.6, lon: -80.62, launches: 0 },
			{ code: 'X', name: 'Unplaced', lat: NaN, lon: NaN, launches: 5 }
		]
	}
];

describe('padsOf', () => {
	it('flattens a range into its pads, busiest first', () => {
		expect(padsOf(EASTERN_RANGE).map((p) => p.code)).toEqual(['LC40', 'LC39A', 'LC41', 'LC39C']);
	});

	it('drops a pad nobody can place — a trip cannot leave from nowhere', () => {
		expect(padsOf(EASTERN_RANGE).some((p) => p.code === 'X')).toBe(false);
	});

	it('calls a pad by the label the export trimmed, where there is one', () => {
		const pads = padsOf(EASTERN_RANGE);
		expect(pads.find((p) => p.code === 'LC40')?.name).toBe('Space Launch Complex 40');
		expect(pads.find((p) => p.code === 'LC41')?.name).toBe('Cape Canaveral SLC-41');
	});

	it('keeps the place a pad belongs to, not the range', () => {
		const pad = padsOf(EASTERN_RANGE).find((p) => p.code === 'LC39A')!;
		expect(pad.siteName).toBe('Kennedy Space Center');
	});

	it('has nothing to say about a collection with no places', () => {
		expect(padsOf(undefined)).toEqual([]);
		expect(padsOf([{ code: 'ZZ', name: 'Nowhere', launches: 0 }])).toEqual([]);
	});
});

describe('busiestPad', () => {
	it('is the one the place is known for', () => {
		expect(busiestPad(padsOf(EASTERN_RANGE))?.code).toBe('LC40');
	});

	it('is nothing at all when there is nothing to leave from', () => {
		expect(busiestPad([])).toBeNull();
	});
});

describe('padAt', () => {
	const pads = padsOf(EASTERN_RANGE);

	it('finds the pad a shared link came back with', () => {
		// What the URL carries: the same point, rounded to five places.
		expect(padAt(pads, 28.6084, -80.60415)?.code).toBe('LC39A');
	});

	it('takes the code the link names over the point it carries', () => {
		expect(padAt(pads, 28.5619, -80.5772, 'LC39A')?.code).toBe('LC39A');
		// A code from another collection names nothing here, so the point decides.
		expect(padAt(pads, 28.5619, -80.5772, 'PU1S')?.code).toBe('LC40');
	});

	it('tells two pads a kilometre apart from each other', () => {
		expect(padAt(pads, 28.5619, -80.5772)?.code).toBe('LC40');
		expect(padAt(pads, 28.5833, -80.5831)?.code).toBe('LC41');
	});

	it('names nothing for a point that is not a pad', () => {
		expect(padAt(pads, 45.9, 63.3)).toBeNull();
		expect(padAt([], 28.6084, -80.6041)).toBeNull();
	});
});

describe('isLaunchSiteSlug', () => {
	it('tells a launch range from every other collection', () => {
		expect(isLaunchSiteSlug('site-vostochny')).toBe(true);
		expect(isLaunchSiteSlug('lv-falcon-9')).toBe(false);
		expect(isLaunchSiteSlug(null)).toBe(false);
	});
});
