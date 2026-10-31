/**
 * Cross-navigation for surface features: a feature climbs to its type's
 * collection page (host body is a cross-ref tile instead), and a type page
 * climbs to the Surface Features category.
 */

import { afterEach, describe, expect, it } from 'vitest';
import { configureHost } from '$lib/host';
import { PROPERTY_COLLECTION_SLUGS } from './category-config';
import { parentCrumb } from './breadcrumb';
import {
	CAT_DWARF_PLANETS,
	CAT_PLANETS,
	CAT_SATELLITE_SYSTEMS,
	CAT_PLANETARY_SYSTEMS,
	CAT_SOLAR_SYSTEM,
	CAT_STAR_SYSTEMS,
	CAT_SURFACE_FEATURES
} from '$lib/fetch/groups/registry';
import { ObjectType } from '$lib/types/objects';
import type { Focusable } from './focusable';
import { ALPHA_CEN } from '$lib/scene/exoplanets/__fixtures__/system';

const MOON = { data: { id: 'naif-301', name: 'Moon' } } as never;

afterEach(() => configureHost({}));

function featureFocusable(): Focusable {
	return { kind: 'feature', body: MOON, feature: { featureId: 1 } as never };
}

describe('parentCrumb: surface features', () => {
	it('climbs from a feature to its type page', () => {
		const crumb = parentCrumb(featureFocusable(), undefined, null, null, {
			slug: 'ft-mons',
			label: 'Mons'
		});
		expect(crumb).toEqual({
			label: 'Mons',
			target: { kind: 'group', slug: 'ft-mons', name: 'Mons' }
		});
	});

	it('falls back to the host body while the type slug is still resolving', () => {
		const crumb = parentCrumb(featureFocusable(), undefined, null, null, null);
		expect(crumb?.target).toEqual({ kind: 'focus', id: 'naif-301', name: 'Moon' });
	});

	it('climbs from a type page to the Surface Features category', () => {
		const crumb = parentCrumb({ kind: 'group', slug: 'ft-mons' }, undefined, null, null);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: CAT_SURFACE_FEATURES });
	});

	it('climbs from the Surface Features category to the Solar System root', () => {
		const crumb = parentCrumb({ kind: 'group', slug: CAT_SURFACE_FEATURES }, undefined, null, null);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'cat-solar-system' });
	});

	it('climbs from every property collection to Structure & Activity, not the root', () => {
		// Iterated rather than listed: the hand-written list here had gone stale
		// against the config table twice, and each page it missed breadcrumbed
		// past its own parent to the root.
		expect(PROPERTY_COLLECTION_SLUGS.length).toBeGreaterThan(6);
		for (const slug of PROPERTY_COLLECTION_SLUGS) {
			const crumb = parentCrumb({ kind: 'group', slug }, undefined, null, null);
			expect(crumb?.target, slug).toMatchObject({
				kind: 'group',
				slug: 'cat-structure-activity'
			});
		}
	});
});

describe('parentCrumb: star families', () => {
	const family = (parents?: string[]) =>
		({ slug: 'star-red-dwarf', type: 'star_family', parent_families: parents }) as never;

	it('climbs to the first family that contains it', () => {
		const crumb = parentCrumb(
			{ kind: 'group', slug: 'star-rr-lyrae-variable' },
			undefined,
			null,
			family(['star-horizontal-branch', 'star-variable-star'])
		);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'star-horizontal-branch' });
	});

	it('climbs from a top family to the Stars page', () => {
		const crumb = parentCrumb(
			{ kind: 'group', slug: 'star-giant' },
			undefined,
			null,
			family(['cat-stars'])
		);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'cat-stars' });
	});

	it('has no crumb for the Stars page', () => {
		expect(parentCrumb({ kind: 'group', slug: 'cat-stars' }, undefined, null, null)).toBeNull();
	});
});

describe('parentCrumb: sky pages', () => {
	it('climbs from a figure to its culture, by the name of the culture', () => {
		const crumb = parentCrumb(
			{ kind: 'group', slug: 'culture-modern_iau', figure: 'Ori' },
			undefined,
			null,
			{ parent_group: 'culture-modern_iau' } as never,
			null,
			null,
			'Moderne (UAI)'
		);
		expect(crumb).toEqual({
			label: 'Moderne (UAI)',
			target: { kind: 'group', slug: 'culture-modern_iau', name: 'Moderne (UAI)' }
		});
	});

	it('climbs from a culture to the Constellations page, and on to Stars', () => {
		const crumb = parentCrumb({ kind: 'group', slug: 'culture-aztec' }, undefined, null, {
			slug: 'culture-aztec',
			parent_group: 'cat-constellations'
		} as never);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'cat-constellations' });
		const up = parentCrumb({ kind: 'group', slug: 'cat-constellations' }, undefined, null, null);
		expect(up?.target).toMatchObject({ kind: 'group', slug: 'cat-stars' });
	});
});

describe('parentCrumb: planet families', () => {
	it('climbs to the first family that contains it', () => {
		const crumb = parentCrumb({ kind: 'group', slug: 'planet-jupiter-analogue' }, undefined, null, {
			slug: 'planet-jupiter-analogue',
			parent_families: ['planet-cold-jupiter']
		} as never);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'planet-cold-jupiter' });
	});

	it('climbs from a top family to the Planets page, named as the category', () => {
		const crumb = parentCrumb({ kind: 'group', slug: 'planet-giant-planet' }, undefined, null, {
			slug: 'planet-giant-planet',
			parent_families: [CAT_PLANETS]
		} as never);
		expect(crumb).toEqual({
			label: 'Planets',
			target: { kind: 'group', slug: CAT_PLANETS, name: 'Planets' }
		});
	});

	it('climbs from the Planets page to the root, Planetary Systems', () => {
		const crumb = parentCrumb({ kind: 'group', slug: CAT_PLANETS }, undefined, null, null);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: CAT_PLANETARY_SYSTEMS });
		for (const slug of [CAT_PLANETARY_SYSTEMS, CAT_STAR_SYSTEMS]) {
			expect(parentCrumb({ kind: 'group', slug }, undefined, null, null)).toBeNull();
		}
	});
});

describe('parentCrumb: the planets of the Solar System', () => {
	it('climbs from a planet to the Solar System page', () => {
		const jupiter = {
			kind: 'body',
			body: { data: { id: 'naif-599', name: 'Jupiter', objectType: ObjectType.PLANET } }
		} as never;
		expect(parentCrumb(jupiter, undefined, null, null)?.target).toEqual({
			kind: 'group',
			slug: CAT_SOLAR_SYSTEM,
			name: 'Solar System'
		});
	});

	it('climbs from the Sun to the Solar System page', () => {
		const sun = {
			kind: 'body',
			body: { data: { id: 'naif-10', name: 'Sun', objectType: ObjectType.STAR } }
		} as never;
		expect(parentCrumb(sun, undefined, null, null)?.target).toMatchObject({
			slug: CAT_SOLAR_SYSTEM
		});
	});

	it('keeps a dwarf planet on its category', () => {
		const pluto = {
			kind: 'body',
			body: { data: { id: 'naif-999', name: 'Pluto', objectType: ObjectType.DWARF_PLANET } }
		} as never;
		expect(parentCrumb(pluto, undefined, null, null)?.target).toMatchObject({
			slug: CAT_DWARF_PLANETS
		});
	});
});

describe('parentCrumb: the stars of a star system', () => {
	const toliman = { kind: 'star', record: { id: 564339647 } } as never;

	it('climbs from a star to the root of its system', () => {
		const crumb = parentCrumb(toliman, undefined, null, null, null, {
			id: 597894079,
			name: 'Alpha Centauri'
		});
		expect(crumb).toEqual({
			label: 'Alpha Centauri',
			target: { kind: 'focus', id: 'x-597894079', name: 'Alpha Centauri' }
		});
	});

	it('has no crumb for a star in no system with no planets', () => {
		expect(parentCrumb(toliman, undefined, null, null)).toBeNull();
	});

	it('climbs from a root to its category', () => {
		const crumb = parentCrumb(
			toliman,
			undefined,
			null,
			null,
			null,
			null,
			undefined,
			CAT_STAR_SYSTEMS
		);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: CAT_STAR_SYSTEMS });
	});

	it('keeps a star in a system on its system, over any category', () => {
		const crumb = parentCrumb(
			toliman,
			undefined,
			null,
			null,
			null,
			{ id: 5, name: 'Alpha Centauri' },
			undefined,
			CAT_PLANETARY_SYSTEMS
		);
		expect(crumb?.target).toMatchObject({ kind: 'focus', name: 'Alpha Centauri' });
	});
});

describe('parentCrumb: planetary systems', () => {
	function barycenter(id: string): Focusable {
		return {
			kind: 'body',
			body: { data: { id, name: id, objectType: ObjectType.BARYCENTER } }
		} as never;
	}

	it('climbs from a planetary system to the Planetary Systems collection', () => {
		const crumb = parentCrumb(barycenter('naif-5'), undefined, null, null);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: CAT_SATELLITE_SYSTEMS });
	});

	it('climbs from the Solar System barycenter to the root', () => {
		const crumb = parentCrumb(barycenter('naif-0'), undefined, null, null);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'cat-solar-system' });
	});

	it('climbs from the Planetary Systems collection to the root', () => {
		const crumb = parentCrumb(
			{ kind: 'group', slug: CAT_SATELLITE_SYSTEMS },
			undefined,
			null,
			null
		);
		expect(crumb?.target).toMatchObject({ kind: 'group', slug: 'cat-solar-system' });
	});
});

describe('parentCrumb: planets of other stars', () => {
	it('climbs from a planet to the star it orbits', () => {
		const p = ALPHA_CEN.planets[2];
		const anchor = {
			host: p.host,
			number: p.number,
			system: ALPHA_CEN.system,
			planet: p,
			hostRecord: ALPHA_CEN.hosts[1]
		};
		const crumb = parentCrumb({ kind: 'planet', body: MOON, anchor }, undefined, null, null);
		expect(crumb).toEqual({
			label: 'Star 564339647',
			target: { kind: 'focus', id: 'x-564339647', name: 'Star 564339647' }
		});
	});

	it("names the star as its system file does in the reader's language", () => {
		configureHost({ locale: () => 'ru' });
		const p = ALPHA_CEN.planets[0];
		const anchor = {
			host: p.host,
			number: p.number,
			system: ALPHA_CEN.system,
			planet: p,
			hostRecord: { ...ALPHA_CEN.hosts[0], names: { ru: 'Проксима Центавра' } }
		};
		const crumb = parentCrumb({ kind: 'planet', body: MOON, anchor }, undefined, null, null);
		expect(crumb?.label).toBe('Проксима Центавра');
	});
});

describe('parentCrumb: the pages a body links to', () => {
	function body(id: string, objectType: ObjectType, parentId = ''): Focusable {
		return { kind: 'body', body: { data: { id, name: id, objectType, parentId } } } as never;
	}

	it('climbs from a moon to the planet its bundle names, past the barycenter', () => {
		const detail = {
			global: { id: 'naif-501', name: 'Io', type: 'moon', parent_name: 'Jupiter' },
			localized: { parent_name: 'Юпитер' }
		} as never;
		const crumb = parentCrumb(body('naif-501', ObjectType.MOON, 'naif-5'), undefined, detail, null);
		expect(crumb).toEqual({
			label: 'Юпитер',
			target: { kind: 'focus', id: 'naif-599', name: 'Юпитер', tab: 'members' }
		});
	});

	it('names the moon host by the body it links to while the bundle loads', () => {
		const bodies: Record<string, { data: { id: string; name: string } }> = {
			'naif-5': { data: { id: 'naif-5', name: 'Jupiter system' } },
			'naif-599': { data: { id: 'naif-599', name: 'Jupiter' } }
		};
		const ctx = (ids: string[]) =>
			({ getBody: (id: string) => (ids.includes(id) ? bodies[id] : undefined) }) as never;
		const io = body('naif-501', ObjectType.MOON, 'naif-5');
		expect(parentCrumb(io, ctx(['naif-5', 'naif-599']), null, null)?.target).toEqual({
			kind: 'focus',
			id: 'naif-599',
			name: 'Jupiter',
			tab: 'members'
		});
		// The planet is culled: the barycenter's name would label a link to the
		// planet, so the crumb waits for the bundle.
		expect(parentCrumb(io, ctx(['naif-5']), null, null)).toBeNull();
	});

	it('names a mission and a carrier by the names of their pages in the language', () => {
		const mission = {
			name: 'Cassini–Huygens',
			primary_type: 'group',
			primary_id: 'mission-cassini'
		};
		const carrier = { name: 'Cassini', primary_type: 'object', primary_id: 'probe-82' };
		const probe = body('probe-150', ObjectType.SPACECRAFT);
		const localized = { link_names: { 'mission-cassini': 'Кассини — Гюйгенс' } };
		const inMission = parentCrumb(
			probe,
			undefined,
			{ global: { part_of_mission: mission }, localized } as never,
			null
		);
		expect(inMission?.label).toBe('Кассини — Гюйгенс');
		const carried = parentCrumb(
			probe,
			undefined,
			{ global: { carried_by: carrier, part_of_mission: mission }, localized } as never,
			null
		);
		// No name of its own in the language: the global name of the link.
		expect(carried?.label).toBe('Cassini');
	});
});
