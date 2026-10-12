import { describe, it, expect } from 'vitest';
import { OrbitalSource } from '$lib/fetch/position/format';
import { archiveLabel, archiveUrl } from '$lib/credits/archive-labels';
import { ORBIT_ARCHIVE_ORGANISATIONS, ORBIT_SOURCE_ORDER, ORBIT_SOURCES } from './orbit-sources';

describe('the orbit source table', () => {
	it('covers every source but the no-provenance sentinel', () => {
		const named = Object.values(OrbitalSource).filter(
			(v): v is OrbitalSource => typeof v === 'number' && v !== OrbitalSource.UNKNOWN
		);
		expect(new Set(ORBIT_SOURCE_ORDER)).toEqual(new Set(named));
		expect(ORBIT_SOURCE_ORDER.length).toBe(Object.keys(ORBIT_SOURCES).length);
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
		const unnamed = ORBIT_SOURCE_ORDER.filter((s) => !ORBIT_SOURCES[s].archive);
		expect(unnamed).toEqual([OrbitalSource.SPICE_PROBE]);
	});

	it('scopes the satellite providers to the system they feed', () => {
		const scoped = ORBIT_SOURCE_ORDER.filter((s) => ORBIT_SOURCES[s].scoped);
		expect(scoped).toEqual([
			OrbitalSource.SBDB_MOON,
			OrbitalSource.ASTERSAT,
			OrbitalSource.CELESTRAK,
			OrbitalSource.SPACETRACK
		]);
	});
});
