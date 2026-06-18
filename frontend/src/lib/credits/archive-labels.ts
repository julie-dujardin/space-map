/**
 * Localized labels for the archive ids in `global.ephemeris_source` and
 * `credits.ephemeris_archives`. Mirror of `EPHEMERIS_ARCHIVES` in
 * `data/src/space_map_data/export/ephemeris.py`.
 */
import * as m from '$lib/paraglide/messages.js';

const ARCHIVE_LABEL: Record<string, () => string> = {
	horizons: m.source_horizons_name,
	sbdb: m.source_sbdb_name,
	celestrak: m.source_celestrak_name,
	spacetrack: m.source_spacetrack_name,
	naif: m.source_spice_ephemeris_name,
	esa: m.source_archive_esa,
	'naif-pds3': m.source_archive_naif_pds3,
	'naif-pds4': m.source_archive_naif_pds4,
	'jaxa-darts': m.source_archive_jaxa_darts
};

export function archiveLabel(id: string | undefined | null): string | null {
	if (!id) return null;
	return ARCHIVE_LABEL[id]?.() ?? null;
}
