/**
 * Who to credit for a position, declared once. The attribution bar, its
 * popover, the Orbital detail section and the SDK control all key off this
 * table, so a new `OrbitalSource` needs an entry here rather than a line in
 * four unrelated files — each of which used to carry its own partial copy.
 *
 * Core-side, so the labels here are the untranslated fallback; the app passes
 * its own through `attributionChips`.
 */
import { OrbitalSource } from '$lib/fetch/position/format';

/** Every source but the sentinel for files that predate the provenance byte. */
export type NamedOrbitSource = Exclude<OrbitalSource, OrbitalSource.UNKNOWN>;

export interface OrbitSourceInfo {
	/** Archive id carrying the citation's name and home page. */
	archive: string;
	/** Organisation as it is cited. NASA-produced sources share one chip. */
	label: string;
	/** Only Earth satellites come from it, so it stays out of the bar elsewhere. */
	earthSatOnly?: boolean;
}

/** `Record` rather than a lookup: a new source fails to compile until it says
 *  who produced it and where the data came from. */
export const ORBIT_SOURCES: Record<NamedOrbitSource, OrbitSourceInfo> = {
	[OrbitalSource.HORIZONS]: { archive: 'horizons', label: 'NASA' },
	[OrbitalSource.SBDB]: { archive: 'sbdb', label: 'NASA' },
	[OrbitalSource.SPICE]: { archive: 'naif', label: 'NASA' },
	[OrbitalSource.SBDB_MOON]: { archive: 'sbdb', label: 'NASA' },
	[OrbitalSource.ASTERSAT]: { archive: 'nsdb', label: 'Natural Satellites Data Base' },
	[OrbitalSource.SPICE_PROBE]: { archive: 'naif', label: 'NASA' },
	[OrbitalSource.CELESTRAK]: { archive: 'celestrak', label: 'CelesTrak', earthSatOnly: true },
	[OrbitalSource.SPACETRACK]: {
		archive: 'spacetrack',
		label: 'Space-Track.org',
		earthSatOnly: true
	}
};

/** Display order wherever sources are listed together. Explicit because the
 *  enum is numeric, and object key order would sort by ordinal instead. */
export const ORBIT_SOURCE_ORDER: readonly NamedOrbitSource[] = [
	OrbitalSource.HORIZONS,
	OrbitalSource.SBDB,
	OrbitalSource.SPICE,
	OrbitalSource.SBDB_MOON,
	OrbitalSource.ASTERSAT,
	OrbitalSource.SPICE_PROBE,
	OrbitalSource.CELESTRAK,
	OrbitalSource.SPACETRACK
];

export function orbitSourceInfo(source: OrbitalSource): OrbitSourceInfo | undefined {
	return ORBIT_SOURCES[source as NamedOrbitSource];
}
