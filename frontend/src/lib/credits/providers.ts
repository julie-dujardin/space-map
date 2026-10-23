/**
 * The catalogues and databases that the object panel and the data page credit
 * by key.
 */
import * as m from '$lib/paraglide/messages.js';

export interface Provider {
	/** The provider's general link. A page that knows a more exact one — an
	 *  object's own catalogue entry — passes it to `addProvider` instead. */
	url?: string;
	name: () => string;
	/** What this provider contributed. Not derivable from the key: the
	 *  surface colour is credited for the colour, not for the tool. */
	role: () => string;
}

export type ProviderKey =
	| 'celestrak'
	| 'iau-naming'
	| 'johnston'
	| 'jonathan'
	| 'jpl-satellite-discovery'
	| 'mpc'
	| 'sbdb'
	| 'truecolortools'
	| 'wikidata';

export const PROVIDERS: Record<ProviderKey, Provider> = {
	wikidata: {
		url: 'https://www.wikidata.org/',
		name: m.source_wikidata_name,
		role: m.source_wikidata_role
	},
	sbdb: {
		url: 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html',
		name: m.source_sbdb_name,
		role: m.source_sbdb_role
	},
	truecolortools: {
		url: 'https://github.com/Askaniy/TrueColorTools',
		name: m.source_truecolortools_name,
		role: m.source_surface_colour_role
	},
	'jpl-satellite-discovery': {
		url: 'https://ssd.jpl.nasa.gov/sats/discovery.html',
		name: m.source_jpl_satellite_discovery_name,
		role: m.source_jpl_satellite_discovery_role
	},
	johnston: {
		url: 'https://www.johnstonsarchive.net/astro/asteroidmoons.html',
		name: m.source_johnston_name,
		role: m.source_johnston_role
	},
	// The link is built from the designation, so there is no index to fall
	// back to.
	mpc: { name: m.source_mpc_name, role: m.source_mpc_role },
	'iau-naming': {
		url: 'https://planetarynames.wr.usgs.gov/',
		name: m.source_iau_naming_name,
		role: m.source_iau_naming_role
	},
	celestrak: {
		url: 'https://celestrak.org/satcat/',
		name: m.source_celestrak_name,
		role: m.source_celestrak_role
	},
	jonathan: {
		url: 'https://planet4589.org/space/',
		name: m.source_jonathan_space_report_name,
		role: m.source_jonathan_space_report_role
	}
};
