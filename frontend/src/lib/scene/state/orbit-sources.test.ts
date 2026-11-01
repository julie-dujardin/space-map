import { describe, it, expect } from 'vitest';
import { OrbitalSource } from '$lib/fetch/position/format';
import { archiveLabel, archiveUrl } from '$lib/credits/archive-labels';
import { ORBIT_ARCHIVE_ORGANISATIONS, ORBIT_SOURCES, type NamedOrbitSource } from './orbit-sources';

const SOURCES = Object.keys(ORBIT_SOURCES).map(Number) as NamedOrbitSource[];

describe('the orbit source table', () => {
	it('covers every source but the no-provenance sentinel', () => {
		const named = Object.values(OrbitalSource).filter(
			(v): v is OrbitalSource => typeof v === 'number' && v !== OrbitalSource.UNKNOWN
		);
		expect(new Set(SOURCES)).toEqual(new Set(named));
	});

	// Attribution is the one thing that may not silently go missing: an
	// archive that does not resolve credits nobody in the popover.
	it('cites every archive by a name, a home page and an organisation', () => {
		for (const [archive, organisation] of Object.entries(ORBIT_ARCHIVE_ORGANISATIONS)) {
			expect(archiveLabel(archive), archive).toBeTruthy();
			expect(archiveUrl(archive), archive).toBeTruthy();
			expect(organisation, archive).toBeTruthy();
		}
	});

	it('leaves only the probes to name their own archive', () => {
		const unnamed = SOURCES.filter((s) => !ORBIT_SOURCES[s].archive);
		expect(unnamed).toEqual([OrbitalSource.SPICE_PROBE]);
	});

	it('scopes the satellite and probe providers to the system they feed', () => {
		const scoped = SOURCES.filter((s) => ORBIT_SOURCES[s].scoped);
		expect(new Set(scoped)).toEqual(
			new Set([
				OrbitalSource.SBDB_MOON,
				OrbitalSource.ASTERSAT,
				OrbitalSource.SPICE_PROBE,
				OrbitalSource.CELESTRAK,
				OrbitalSource.SPACETRACK
			])
		);
	});
});
