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

import { applyFocus, applyNav, applyTab, isBodyId, serializeUrl } from './url';
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
	navToFeature: null
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

	it('frames the departure when there is nowhere to go yet', () => {
		expect(applyNav(baseView, 'naif-499').id).toBe('naif-499');
	});

	// A surface feature rides in the query block, not the path: the trajectory is
	// priced against the body, and only the touchdown point is the feature.
	it('keeps the body in the path when an end is a place on it', () => {
		const url = serializeUrl(applyNav(baseView, 'naif-399', { id: 'naif-499', featureId: 15057 }));
		expect(url.startsWith('/nav/naif-399/naif-499?at=')).toBe(true);
		expect(url).toContain('&tf=15057');
		expect(url).not.toContain('ff=');
	});

	it('carries a feature at the departure end too', () => {
		const url = serializeUrl(applyNav(baseView, { id: 'naif-399', featureId: 14940 }, 'naif-499'));
		expect(url).toContain('&ff=14940');
	});

	// The destination's feature belongs to a destination; without one it would
	// name a place on nothing.
	it('drops a destination feature when there is no destination', () => {
		const url = serializeUrl({
			...applyNav(baseView, 'naif-399'),
			navToFeature: 15057
		});
		expect(url).not.toContain('tf=');
	});
});
