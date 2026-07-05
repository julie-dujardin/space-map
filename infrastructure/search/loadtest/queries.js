// Query pools mirroring the frontend's two request shapes (client.ts).

const INDEX = 'catalog';
// DROP_GROUPS_FACET=1 drops the ~1000-value object.groups facet, which dominates
// faceted cost, to measure its weight.
const FACETS = [
	'kind',
	'object.type',
	'object.groups',
	'object.neo',
	'object.pha',
	'group.type',
	'feature.type'
].filter((f) => !(__ENV.DROP_GROUPS_FACET === '1' && f === 'object.groups'));

// Popular terms at varied prefix lengths (Meili prefix-matches the last word, so
// partial typing is the common case) plus real designations. Varied to avoid
// measuring a hot single-query path.
export const AUTOCOMPLETE_TERMS = [
	'm', 'ma', 'mar', 'mars', 'j', 'ju', 'jup', 'jupi', 'jupiter',
	's', 'sa', 'sat', 'satu', 'saturn', 'ne', 'nep', 'neptune',
	'star', 'starl', 'starli', 'starlink', 'sta',
	'iss', 'inter', 'international space',
	'hub', 'hubb', 'hubble', 'voy', 'voya', 'voyager', 'voyager 1',
	'ceres', 'cer', 'vesta', 'pluto', 'plut', 'charon',
	'moon', 'luna', 'europa', 'eur', 'io', 'gany', 'ganymede',
	'titan', 'tit', 'ence', 'enceladus', 'triton',
	'apollo', 'apoll', 'gemini', 'cassini', 'cass', 'juno',
	'gps', 'oneweb', 'cosmos', 'cz-6', 'sl-4', 'usa 489',
	'bennu', 'ryugu', 'eros', 'itokawa', 'halley', 'hale',
	'crater', 'mons', 'planitia', 'olympus', 'tycho',
	'2001', '1999 tu', 'p/linear', 'c/1846', 'starlink-35',
	'earth', 'ear', 'venus', 'ven', 'mercury', 'merc', 'uranus', 'ura',
	'webb', 'james webb', 'new horizons', 'perseverance', 'curiosity',
	'phobos', 'deimos', 'mimas', 'rhea', 'dione', 'iapetus', 'phoebe'
];

export function autocompleteBody(term, locale) {
	return JSON.stringify({ q: term, limit: 8, locales: [locale] });
}

// Representative multi-search variants: open catalog, text query, and filtered
// browses with the disjunctive recount fan-out (the extra limit:0 sub-query).
const FACETED_VARIANTS = [
	(loc) => ({
		queries: [
			{ indexUid: INDEX, q: '', facets: FACETS, offset: 0, limit: 30, locales: [loc] }
		]
	}),
	(loc) => ({
		queries: [
			{ indexUid: INDEX, q: 'star', facets: FACETS, offset: 0, limit: 30, locales: [loc] }
		]
	}),
	(loc) => ({
		queries: [
			{
				indexUid: INDEX,
				q: '',
				filter: '(kind = "object")',
				facets: FACETS,
				offset: 0,
				limit: 30,
				locales: [loc]
			},
			// Disjunctive recount for the selected `kind` facet (own clause dropped).
			{ indexUid: INDEX, q: '', facets: ['kind'], limit: 0, locales: [loc] }
		]
	}),
	(loc) => ({
		queries: [
			{
				indexUid: INDEX,
				q: '',
				filter: '(object.type = "asteroid") AND object.neo = true',
				sort: ['diameter_km:desc'],
				facets: FACETS,
				offset: 0,
				limit: 30,
				locales: [loc]
			},
			{
				indexUid: INDEX,
				q: '',
				filter: 'object.neo = true',
				facets: ['object.type'],
				limit: 0,
				locales: [loc]
			}
		]
	})
];

export function facetedBody(i, locale) {
	return JSON.stringify(FACETED_VARIANTS[i % FACETED_VARIANTS.length](locale));
}

export const FACETED_COUNT = FACETED_VARIANTS.length;

export const LOCALES = ['en', 'fr', 'ja', 'zh', 'de'];
