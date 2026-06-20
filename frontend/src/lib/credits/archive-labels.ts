/**
 * Localized labels and home pages for the archive ids in
 * `global.ephemeris_source` and `credits.ephemeris_archives`. Mirror of
 * `EPHEMERIS_ARCHIVES` in `data/src/space_map_data/export/ephemeris.py`.
 */
import * as m from '$lib/paraglide/messages.js';

interface Archive {
	label: () => string;
	url: string;
	role: () => string;
}

const ARCHIVES: Record<string, Archive> = {
	horizons: {
		label: m.source_horizons_name,
		url: 'https://ssd.jpl.nasa.gov/horizons/',
		role: m.archive_role_horizons
	},
	sbdb: {
		label: m.source_sbdb_name,
		url: 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html',
		role: m.archive_role_sbdb
	},
	celestrak: {
		label: m.source_celestrak_name,
		url: 'https://celestrak.org/',
		role: m.archive_role_celestrak
	},
	spacetrack: {
		label: m.source_spacetrack_name,
		url: 'https://www.space-track.org/',
		role: m.archive_role_spacetrack
	},
	naif: {
		label: m.source_spice_ephemeris_name,
		url: 'https://naif.jpl.nasa.gov/naif/',
		role: m.archive_role_naif
	},
	esa: {
		label: m.source_archive_esa,
		url: 'https://www.cosmos.esa.int/web/spice',
		role: m.archive_role_esa
	},
	'naif-pds3': {
		label: m.source_archive_naif_pds3,
		url: 'https://pds.nasa.gov/',
		role: m.archive_role_naif_pds3
	},
	'naif-pds4': {
		label: m.source_archive_naif_pds4,
		url: 'https://pds.nasa.gov/',
		role: m.archive_role_naif_pds4
	},
	'jaxa-darts': {
		label: m.source_archive_jaxa_darts,
		url: 'https://darts.isas.jaxa.jp/',
		role: m.archive_role_jaxa_darts
	}
};

export function archiveLabel(id: string | undefined | null): string | null {
	if (!id) return null;
	return ARCHIVES[id]?.label() ?? null;
}

export function archiveUrl(id: string | undefined | null): string | null {
	if (!id) return null;
	return ARCHIVES[id]?.url ?? null;
}

export function archiveRole(id: string | undefined | null): string | null {
	if (!id) return null;
	return ARCHIVES[id]?.role() ?? null;
}
