/** Planet files for tests, as `docs/export-format/extrasolar.md` gives them. */

import type {
	Planet,
	PlanetElements,
	PlanetHost,
	PlanetIndexFile,
	PlanetSystem
} from '$lib/fetch/extrasolar/planets';

export function host(id: number, planets: number[]): PlanetHost {
	return {
		id,
		name: `Star ${id}`,
		name_source: null,
		class: 'star',
		cross_ids: [],
		planets,
		placement: 'parallax',
		position: [1, 2, 3],
		distance: 3.74,
		ra: 0,
		dec: 0,
		epoch: 2016,
		teff: 5000,
		teff_source: null,
		radius: 1,
		radius_source: null,
		mass: 1,
		metallicity: null,
		spectral_type: null,
		bp_rp: null,
		catalogue: null,
		catalogue_name: null
	};
}

export function elements(a: number, extra: Partial<PlanetElements> = {}): PlanetElements {
	return {
		a,
		e: 0.1,
		i: 30,
		om: 40,
		w: 50,
		ma: 60,
		n: 1,
		epoch: 2457000,
		phase: 'transit',
		...extra
	};
}

export function planet(
	hostId: number,
	n: number,
	el: PlanetElements | null,
	values: Planet['values'] = {}
): Planet {
	return {
		host: hostId,
		number: n,
		object: false,
		name: `Planet ${hostId} ${n}`,
		name_source: null,
		designation: null,
		letter: null,
		aliases: [],
		cross_ids: [],
		class: 'planet',
		class_basis: null,
		mass_ratio: null,
		status: 'confirmed',
		elements: el,
		values,
		sources: {},
		assumed: [],
		estimated: [],
		computed: [],
		limits: []
	};
}

/** α Cen in one file: Proxima with two planets, Toliman with one that has no orbit. */
export const ALPHA_CEN: PlanetSystem = {
	token: '0000000000000000',
	system: 27424668,
	hosts: [host(27424668, [1, 2]), host(564339647, [1])],
	planets: [
		planet(27424668, 1, elements(0.0485, { phase: 'transit' }), { radius: 0.0913 }),
		planet(27424668, 2, elements(1.5, { i: 100, om: 200, phase: 'assumed' })),
		planet(564339647, 1, null)
	]
};

/** A star ID that merged into Proxima. */
export const MERGED_HOST = 2 ** 24 + 999;

/** The index of {@link ALPHA_CEN} and of a host with no place, with an alias
 *  on its own host and one from the merged host. */
export const INDEX: PlanetIndexFile = {
	token: '0000000000000000',
	hosts: [
		{
			id: 27424668,
			system: 27424668,
			planets: [1, 2],
			position: [-0.47, -0.36, -1.16],
			outer_orbit: 1.5
		},
		{
			id: 564339647,
			system: 27424668,
			planets: [1],
			position: [-0.47, -0.39, -1.1],
			outer_orbit: null
		},
		{
			id: 1091633172,
			system: 1091633172,
			planets: [1, 2],
			position: null,
			outer_orbit: 2.9
		}
	],
	aliases: {
		'1091633172/3': [1091633172, 2],
		// A host that merged into Proxima: it has no live planet left.
		[`${MERGED_HOST}/1`]: [27424668, 2]
	}
};
