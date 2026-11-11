/**
 * Who to credit for a position, declared once. The attribution bar, its
 * popover, the Orbital detail section and the SDK control all key off these
 * tables, so a new `OrbitalSource` or archive needs an entry here rather than
 * a line in four unrelated files.
 *
 * Core-side, so the names here are the untranslated fallback; the app passes
 * its own through `attributionChips`.
 */
import { OrbitalSource, type OrbitArchive } from '$lib/fetch/position/format';

/** Every source but the sentinel for files that predate the provenance byte. */
export type NamedOrbitSource = Exclude<OrbitalSource, OrbitalSource.UNKNOWN>;

export interface OrbitSourceInfo {
	/** Archive carrying the citation's name and home page. Absent for probes:
	 *  agencies keep their own kernels, so each craft names its archive. */
	archive?: OrbitArchive;
	/** Its bodies hang off one system at a time: Earth's satellites, a binary
	 *  asteroid's moons, a probe in orbit. It is credited only while the camera
	 *  is there. */
	scoped?: boolean;
}

/** `Record` rather than a lookup: a new source fails to compile until it says
 *  where the data came from. */
export const ORBIT_SOURCES: Record<NamedOrbitSource, OrbitSourceInfo> = {
	[OrbitalSource.HORIZONS]: { archive: 'horizons' },
	[OrbitalSource.SBDB]: { archive: 'sbdb' },
	[OrbitalSource.SPICE]: { archive: 'naif' },
	[OrbitalSource.SBDB_MOON]: { archive: 'sbdb', scoped: true },
	[OrbitalSource.ASTERSAT]: { archive: 'nsdb', scoped: true },
	[OrbitalSource.SPICE_PROBE]: { scoped: true },
	[OrbitalSource.CELESTRAK]: { archive: 'celestrak', scoped: true },
	[OrbitalSource.SPACETRACK]: { archive: 'spacetrack', scoped: true }
};

/** Organisation each archive is cited as, in display order. NASA's archives
 *  share one chip. */
export const ORBIT_ARCHIVE_ORGANISATIONS: Record<OrbitArchive, string> = {
	horizons: 'NASA',
	sbdb: 'NASA',
	naif: 'NASA',
	nsdb: 'Natural Satellites Data Base',
	esa: 'ESA',
	'naif-pds3': 'NASA',
	'naif-pds4': 'NASA',
	'm20-map': 'NASA',
	'jaxa-darts': 'JAXA',
	'gcat-deepcat': 'McDowell Deep Space Catalog',
	clpds: 'CNSA',
	celestrak: 'CelesTrak',
	spacetrack: 'Space-Track.org'
};

export const ORBIT_ARCHIVE_ORDER = Object.keys(ORBIT_ARCHIVE_ORGANISATIONS) as OrbitArchive[];

export function orbitSourceInfo(source: OrbitalSource): OrbitSourceInfo | undefined {
	return ORBIT_SOURCES[source as NamedOrbitSource];
}

/** The archive behind a body's position. */
export function orbitArchiveOf(data: {
	orbitalSource: OrbitalSource;
	orbitArchive?: OrbitArchive;
}): OrbitArchive | undefined {
	return orbitSourceInfo(data.orbitalSource)?.archive ?? data.orbitArchive;
}
