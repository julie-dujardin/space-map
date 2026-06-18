/**
 * Localized labels and home pages for the archive ids in
 * `global.ephemeris_source` and `credits.ephemeris_archives`. Mirror of
 * `EPHEMERIS_ARCHIVES` in `data/src/space_map_data/export/ephemeris.py`.
 */
import * as m from '$lib/paraglide/messages.js';

interface Archive {
	label: () => string;
	url: string;
}

const ARCHIVES: Record<string, Archive> = {
	horizons: { label: m.source_horizons_name, url: 'https://ssd.jpl.nasa.gov/horizons/' },
	sbdb: { label: m.source_sbdb_name, url: 'https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html' },
	celestrak: { label: m.source_celestrak_name, url: 'https://celestrak.org/' },
	spacetrack: { label: m.source_spacetrack_name, url: 'https://www.space-track.org/' },
	naif: { label: m.source_spice_ephemeris_name, url: 'https://naif.jpl.nasa.gov/naif/' },
	esa: { label: m.source_archive_esa, url: 'https://www.cosmos.esa.int/web/spice' },
	'naif-pds3': { label: m.source_archive_naif_pds3, url: 'https://pds.nasa.gov/' },
	'naif-pds4': { label: m.source_archive_naif_pds4, url: 'https://pds.nasa.gov/' },
	'jaxa-darts': { label: m.source_archive_jaxa_darts, url: 'https://darts.isas.jaxa.jp/' }
};

export function archiveLabel(id: string | undefined | null): string | null {
	if (!id) return null;
	return ARCHIVES[id]?.label() ?? null;
}

export function archiveUrl(id: string | undefined | null): string | null {
	if (!id) return null;
	return ARCHIVES[id]?.url ?? null;
}
