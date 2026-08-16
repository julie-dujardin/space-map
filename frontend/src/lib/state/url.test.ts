import { describe, it, expect, vi } from 'vitest';

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string | undefined>) =>
		route
			.replace('[type]', params.type ?? '')
			.replace('[id]', params.id ?? '')
			.replace('[featureId]', params.featureId ?? '')
			.replace('/[[from]]', params.from ? `/${params.from}` : '')
			.replace('/[[to]]', params.to ? `/${params.to}` : '')
			.replace('/[[name]]', params.name ? `/${params.name}` : '')
}));

// `parseUrl` reads `$app/state.page` reactively. We don't exercise it here —
// these tests cover `serializeUrl`, which is pure-ish (only depends on `resolve`).
vi.mock('$app/state', () => ({
	page: { params: {}, route: { id: null }, url: new URL('http://x/') }
}));

import {
	applyFocus,
	applyNav,
	applyTab,
	formatNavEnd,
	isBodyId,
	parseNavEnd,
	serializeUrl
} from './url';
import { DEFAULT_TRIP } from '$lib/travel/trip';
import type { MapViewState } from './view';

const baseView: MapViewState = {
	type: 'b',
	id: 'naif-10',
	name: 'Sun',
	date: new Date('2026-01-15T12:00:00Z'),
	isNow: false,
	latitude: 45,
	longitude: 0,
	zoom: 42.43,
	imageIndex: null,
	gallery: null,
	featureId: null,
	groupSlug: null,
	tab: null,
	memberPage: null,
	quad: null,
	featureType: null,
	ring: null,
	navFrom: null,
	navTo: null,
	navFromFeature: null,
	navToFeature: null,
	navFromPlace: null,
	navToPlace: null,
	trip: DEFAULT_TRIP
};

describe('serializeUrl', () => {
	it('drops the name segment when name is empty', () => {
		expect(serializeUrl({ ...baseView, name: '' })).toBe(
			'/b/10?at=2026-01-15T12:00:00.000Z,45.00000,0.00000,42.430'
		);
	});

	it('writes "now" instead of an ISO date when isNow is true', () => {
		const url = serializeUrl({ ...baseView, isNow: true });
		expect(url).toContain('?at=now,');
	});

	it('uses the spkid- URL prefix for small bodies', () => {
		const url = serializeUrl({ ...baseView, type: 's', id: 'spkid-20134340', name: 'Bennu' });
		expect(url.startsWith('/s/20134340/Bennu?at=')).toBe(true);
	});

	it('uses the norad_satcat- URL prefix for satellites', () => {
		const url = serializeUrl({ ...baseView, type: 'e', id: 'norad_satcat-25544', name: 'ISS' });
		expect(url.startsWith('/e/25544/ISS?at=')).toBe(true);
	});

	it('nests features under the body route with the body type segment', () => {
		const url = serializeUrl({
			...baseView,
			type: 'f',
			id: 'naif-301',
			featureId: 14940,
			name: 'Tycho'
		});
		expect(url.startsWith('/b/301/f/14940/Tycho?at=')).toBe(true);
	});

	it('uses the s/ type segment for features on small bodies', () => {
		const url = serializeUrl({
			...baseView,
			type: 'f',
			id: 'spkid-20000004',
			featureId: 14940,
			name: 'Licinia'
		});
		expect(url.startsWith('/s/20000004/f/14940/Licinia?at=')).toBe(true);
	});

	describe('imageIndex serialization', () => {
		it('omits img= when imageIndex is null', () => {
			expect(serializeUrl({ ...baseView, imageIndex: null })).not.toContain('img=');
		});

		it('emits img=0 when imageIndex is 0', () => {
			expect(serializeUrl({ ...baseView, imageIndex: 0 })).toContain('&img=0');
		});

		it('emits img=N for any non-negative integer', () => {
			expect(serializeUrl({ ...baseView, imageIndex: 7 })).toContain('&img=7');
		});

		// Regression: an earlier `state.imageIndex !== null` check let undefined
		// slip through and produced literal "&img=undefined" in the URL.
		it('omits img= when imageIndex is undefined', () => {
			const view = { ...baseView, imageIndex: undefined as unknown as null };
			expect(serializeUrl(view)).not.toContain('img=');
		});

		it('omits img= when imageIndex is NaN', () => {
			const view = { ...baseView, imageIndex: NaN as unknown as number };
			expect(serializeUrl(view)).not.toContain('img=');
		});

		it('omits img= when imageIndex is a non-integer number', () => {
			const view = { ...baseView, imageIndex: 1.5 };
			expect(serializeUrl(view)).not.toContain('img=');
		});

		it('emits img= on group routes too', () => {
			const url = serializeUrl({
				...baseView,
				type: 'g',
				groupSlug: 'cat-moons',
				name: 'Moons',
				imageIndex: 2
			});
			expect(url.startsWith('/g/cat-moons/Moons?at=')).toBe(true);
			expect(url).toContain('&img=2');
		});
	});

	describe('tab serialization', () => {
		it('omits tab= for the default overview tab (null)', () => {
			expect(serializeUrl({ ...baseView, tab: null })).not.toContain('tab=');
		});

		it('emits &tab=members for the members tab', () => {
			expect(serializeUrl({ ...baseView, tab: 'members' })).toContain('&tab=members');
		});

		it('emits &tab=images for the images tab', () => {
			expect(serializeUrl({ ...baseView, tab: 'images' })).toContain('&tab=images');
		});

		it('serializes the tab on group routes too', () => {
			const url = serializeUrl({
				...baseView,
				type: 'g',
				groupSlug: 'cat-moons',
				name: 'Moons',
				tab: 'members'
			});
			expect(url.startsWith('/g/cat-moons/Moons?at=')).toBe(true);
			expect(url).toContain('&tab=members');
		});
	});

	describe('member-page (mp) serialization', () => {
		it('emits &mp=N under the members tab', () => {
			const url = serializeUrl({ ...baseView, tab: 'members', memberPage: 3 });
			expect(url).toContain('&mp=3');
		});

		it('omits mp= for page 1 (the implicit default)', () => {
			expect(serializeUrl({ ...baseView, tab: 'members', memberPage: 1 })).not.toContain('mp=');
		});

		it('omits mp= when memberPage is null', () => {
			expect(serializeUrl({ ...baseView, tab: 'members', memberPage: null })).not.toContain('mp=');
		});

		// mp is meaningless outside the one paginated list — never leak it onto
		// other tabs even if the field is stale.
		it('omits mp= when the active tab is not members', () => {
			expect(serializeUrl({ ...baseView, tab: 'images', memberPage: 5 })).not.toContain('mp=');
		});
	});

	// A feature's own pictures are a gallery like any other; its route just has
	// fewer query blocks to carry.
	describe('feature query block', () => {
		const feature = { ...baseView, type: 'f', id: 'naif-499', featureId: 1000, name: 'Candor' };

		it('carries the tab and the open image', () => {
			const url = serializeUrl({ ...feature, tab: 'images', imageIndex: 2 });
			expect(url).toContain('/b/499/f/1000/Candor?at=');
			expect(url).toContain('&img=2');
			expect(url).toContain('&tab=images');
		});

		it('omits the blocks a feature has no lists for', () => {
			const url = serializeUrl({ ...feature, tab: 'images', memberPage: 3, ring: 'c-ring' });
			expect(url).not.toContain('mp=');
			expect(url).not.toContain('ring=');
		});
	});

	describe('gallery serialization', () => {
		it('emits &gal= under the images tab', () => {
			const url = serializeUrl({ ...baseView, tab: 'images', gallery: 'moons' });
			expect(url).toContain('&tab=images&gal=moons');
		});

		it('omits gal= at the shelf index', () => {
			expect(serializeUrl({ ...baseView, tab: 'images', gallery: null })).not.toContain('gal=');
		});

		// A collection's shelves key by member id, which carries a prefix separator.
		it('encodes the gallery key', () => {
			const url = serializeUrl({ ...baseView, tab: 'images', gallery: 'naif-599' });
			expect(url).toContain('&gal=naif-599');
		});

		// The open shelf belongs to the images panel alone; a stale key must not
		// ride along on another tab's link.
		it('omits gal= when the active tab is not images', () => {
			expect(serializeUrl({ ...baseView, tab: 'rings', gallery: 'moons' })).not.toContain('gal=');
		});
	});

	describe('ring serialization', () => {
		it('emits &ring= under the rings tab', () => {
			const url = serializeUrl({ ...baseView, tab: 'rings', ring: 'cassini-division' });
			expect(url).toContain('&tab=rings&ring=cassini-division');
		});

		it('omits ring= at the top of the catalogue', () => {
			expect(serializeUrl({ ...baseView, tab: 'rings', ring: null })).not.toContain('ring=');
		});

		// The drill path belongs to the rings panel alone; a stale slug must not
		// ride along on another tab's link.
		it('omits ring= when the active tab is not rings', () => {
			expect(serializeUrl({ ...baseView, tab: 'images', ring: 'c-ring' })).not.toContain('ring=');
		});
	});
});

describe('applyTab', () => {
	it('clears the depth reached inside the tab being left', () => {
		const next = applyTab(
			{ ...baseView, tab: 'features', memberPage: 3, quad: 'H-5', featureType: 'AA', ring: 'c' },
			'members'
		);
		expect(next).toMatchObject({
			tab: 'members',
			memberPage: null,
			quad: null,
			featureType: null,
			ring: null
		});
	});

	// The viewer counts into the open shelf; carried across a tab switch it
	// silently re-points at whichever shelf leads instead.
	it('closes an open picture along with its shelf', () => {
		const next = applyTab(
			{ ...baseView, tab: 'images', gallery: 'rings', imageIndex: 2 },
			'images'
		);
		expect(next.gallery).toBeNull();
		expect(next.imageIndex).toBeNull();
	});
});

describe('isBodyId', () => {
	it('accepts every prefix the app addresses a body by', () => {
		expect(isBodyId('naif-499')).toBe(true);
		expect(isBodyId('spkid-20134340')).toBe(true);
		expect(isBodyId('norad_satcat-25544')).toBe(true);
		expect(isBodyId('probe-7')).toBe(true);
		expect(isBodyId('extra-1')).toBe(true);
	});

	it('rejects an unknown prefix or a non-numeric tail', () => {
		expect(isBodyId('cat-solar-system')).toBe(false);
		expect(isBodyId('naif-mars')).toBe(false);
		expect(isBodyId('499')).toBe(false);
		expect(isBodyId('')).toBe(false);
	});
});

describe('parseNavEnd', () => {
	it('round-trips every shape of an end', () => {
		expect(parseNavEnd(formatNavEnd('naif-499', null))).toEqual({
			bodyId: 'naif-499',
			featureId: null,
			place: null
		});
		expect(parseNavEnd(formatNavEnd('naif-499', 15057))).toEqual({
			bodyId: 'naif-499',
			featureId: 15057,
			place: null
		});
		// A pad: no id anywhere names it, so the coordinates are the end. The
		// collection they came from rides the query, not this token.
		const pad = { latDeg: 51.88449, lonDeg: 128.33383, siteSlug: 'site-vostochny' };
		expect(parseNavEnd(formatNavEnd('naif-399', null, pad))).toEqual({
			bodyId: 'naif-399',
			featureId: null,
			place: { latDeg: 51.88449, lonDeg: 128.33383 }
		});
	});

	it('keeps a point to about a metre and no further', () => {
		expect(formatNavEnd('naif-399', null, { latDeg: 28.6083892, lonDeg: -80.6041482 })).toBe(
			'naif-399-at-28.60839,-80.60415'
		);
		// Trailing zeros are noise on a coordinate, not precision.
		expect(formatNavEnd('naif-399', null, { latDeg: 5.2, lonDeg: -52.75 })).toBe(
			'naif-399-at-5.2,-52.75'
		);
	});

	// A negative NAIF id already carries a dash, so the split has to key on the
	// infix rather than on dash counting.
	it('splits a body id that has dashes of its own', () => {
		expect(parseNavEnd('naif--164-f-3537')).toEqual({
			bodyId: 'naif--164',
			featureId: 3537,
			place: null
		});
	});

	it('rejects a malformed end', () => {
		expect(parseNavEnd('naif-499-f-')).toBeNull();
		expect(parseNavEnd('naif-499-f-crater')).toBeNull();
		expect(parseNavEnd('naif-499-f-0')).toBeNull();
		expect(parseNavEnd('cat-surface-features-f-1')).toBeNull();
	});

	it('rejects a point that is not one, or is not on a globe', () => {
		expect(parseNavEnd('naif-399-at-')).toBeNull();
		expect(parseNavEnd('naif-399-at-51.88')).toBeNull();
		expect(parseNavEnd('naif-399-at-north,east')).toBeNull();
		expect(parseNavEnd('naif-399-at-51.88,128.33,0')).toBeNull();
		// Nothing sits at 91 degrees of latitude.
		expect(parseNavEnd('naif-399-at-91,0')).toBeNull();
	});
});

describe('applyNav', () => {
	it('frames the destination and keeps both ends', () => {
		const next = applyNav(baseView, 'naif-399', 'naif-499');
		expect(next).toMatchObject({
			type: 'nav',
			id: 'naif-499',
			navFrom: 'naif-399',
			navTo: 'naif-499'
		});
	});

	// A body's own planner opens this way: you are looking at where you want to
	// end up, and where you would set out from is the question.
	it('takes a destination with no departure', () => {
		const next = applyNav(baseView, null, 'naif-499');
		expect(next).toMatchObject({ id: 'naif-499', navFrom: null, navTo: 'naif-499' });
	});

	it('tears down the drawer depth of the page it left', () => {
		const next = applyNav(
			{ ...baseView, tab: 'images', gallery: 'rings', imageIndex: 2, groupSlug: 'cat-oceans' },
			'naif-399',
			'naif-499'
		);
		expect(next).toMatchObject({
			tab: null,
			gallery: null,
			imageIndex: null,
			groupSlug: null
		});
	});

	// Leaving a trip for a body must not leave the trip in the URL, or the nav
	// branch of serializeUrl keeps winning.
	it('is cleared by focusing a body', () => {
		const trip = applyNav(baseView, 'naif-399', 'naif-499');
		const next = applyFocus(trip, { type: 'b', id: 'naif-599', name: 'Jupiter' });
		expect(next.navFrom).toBeNull();
		expect(next.navTo).toBeNull();
		expect(serializeUrl(next).startsWith('/b/599/Jupiter?at=')).toBe(true);
	});
});

describe('serializeUrl on a trip', () => {
	it('writes /nav/<from>/<to> with the camera block', () => {
		const url = serializeUrl(applyNav(baseView, 'naif-399', 'naif-499'));
		expect(url).toBe('/nav/naif-399/naif-499?at=2026-01-15T12:00:00.000Z,45.00000,0.00000,42.430');
	});

	// Both ends carry their prefix: a trip can join two id spaces, and the path
	// has no type segment to tell them apart.
	it('keeps full prefixed ids across id spaces', () => {
		const url = serializeUrl(applyNav(baseView, 'probe-7', 'spkid-20134340'));
		expect(url.startsWith('/nav/probe-7/spkid-20134340?at=')).toBe(true);
	});

	// The empty form is a real, shareable URL, and the departure segment stays on
	// it — dropping it would make /nav/<x> ambiguous between the two ends.
	it('drops only the destination segment when there is no destination', () => {
		const url = serializeUrl(applyNav(baseView, 'naif-399'));
		expect(url.startsWith('/nav/naif-399?at=')).toBe(true);
	});

	// The other way round the slot cannot be dropped, for the same reason: a
	// marker holds the departure's place so the destination stays second.
	it('marks the departure slot when there is nowhere to set out from', () => {
		const url = serializeUrl(applyNav(baseView, null, 'naif-499'));
		expect(url.startsWith('/nav/-/naif-499?at=')).toBe(true);
	});

	it('frames the departure when there is nowhere to go yet', () => {
		expect(applyNav(baseView, 'naif-499').id).toBe('naif-499');
	});

	// A departure's feature names a place on a body that is no longer an end.
	it('drops a departure feature when there is no departure', () => {
		const url = serializeUrl({
			...applyNav(baseView, null, 'naif-499'),
			navFromFeature: 14940
		});
		expect(url.startsWith('/nav/-/naif-499?at=')).toBe(true);
		expect(url).not.toContain('14940');
	});

	// The pair is one key, so it stays in one segment: splitting it across the
	// path and the query left half an end's identity in a query param.
	it('writes an end that is a place on a body as one segment', () => {
		const url = serializeUrl(applyNav(baseView, 'naif-399', { id: 'naif-499', featureId: 15057 }));
		expect(url.startsWith('/nav/naif-399/naif-499-f-15057?at=')).toBe(true);
		expect(url).not.toContain('tf=');
	});

	it('carries a feature at the departure end too', () => {
		const url = serializeUrl(applyNav(baseView, { id: 'naif-399', featureId: 14940 }, 'naif-499'));
		expect(url.startsWith('/nav/naif-399-f-14940/naif-499?at=')).toBe(true);
	});

	// The destination's feature belongs to a destination; without one it would
	// name a place on nothing.
	it('drops a destination feature when there is no destination', () => {
		const url = serializeUrl({
			...applyNav(baseView, 'naif-399'),
			navToFeature: 15057
		});
		expect(url.startsWith('/nav/naif-399?at=')).toBe(true);
		expect(url).not.toContain('15057');
	});

	it('carries the terms the trip is flown on', () => {
		const url = serializeUrl({
			...applyNav(baseView, 'naif-399', 'naif-499'),
			trip: { ...DEFAULT_TRIP, targetMode: 'flyby', vehicleId: 'starship', passengers: 6 }
		});
		expect(url).toContain('&tm=flyby');
		expect(url).toContain('&craft=starship');
		expect(url).toContain('&crew=6');
	});

	// The terms describe the planner, not the pair — moving an end keeps the same
	// craft loaded the same way.
	it('keeps the terms when an end moves', () => {
		const trip = { ...DEFAULT_TRIP, vehicleId: 'starship', payloadKg: 100 };
		const moved = applyNav(
			{ ...applyNav(baseView, 'naif-399', 'naif-499'), trip },
			'naif-399',
			'naif-599'
		);
		expect(moved.trip).toEqual(trip);
	});

	// Off /nav there is no trip, and a stale craft would reappear on the next one.
	it('drops the terms when a body is focused', () => {
		const trip = { ...DEFAULT_TRIP, vehicleId: 'starship' };
		const next = applyFocus(
			{ ...applyNav(baseView, 'naif-399', 'naif-499'), trip },
			{
				type: 'b',
				id: 'naif-599',
				name: 'Jupiter'
			}
		);
		expect(next.trip).toEqual(DEFAULT_TRIP);
	});
});
