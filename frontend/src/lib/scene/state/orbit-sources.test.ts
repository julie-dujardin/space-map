import { describe, it, expect } from 'vitest';
import { OrbitalSource } from '$lib/fetch/position/format';
import { archiveLabel, archiveUrl } from '$lib/credits/archive-labels';
import { ORBIT_SOURCE_ORDER, ORBIT_SOURCES } from './orbit-sources';

describe('the orbit source table', () => {
	it('covers every source but the no-provenance sentinel', () => {
		const named = Object.values(OrbitalSource).filter(
			(v): v is OrbitalSource => typeof v === 'number' && v !== OrbitalSource.UNKNOWN
		);
		expect(new Set(ORBIT_SOURCE_ORDER)).toEqual(new Set(named));
		expect(ORBIT_SOURCE_ORDER.length).toBe(Object.keys(ORBIT_SOURCES).length);
	});

	// Attribution is the one thing that may not silently go missing: a source
	// whose archive does not resolve credits nobody in the popover.
	it('cites every source by an archive that has a name and a home page', () => {
		for (const source of ORBIT_SOURCE_ORDER) {
			const { archive, label } = ORBIT_SOURCES[source];
			expect(archiveLabel(archive), `${OrbitalSource[source]} archive ${archive}`).toBeTruthy();
			expect(archiveUrl(archive), `${OrbitalSource[source]} archive ${archive}`).toBeTruthy();
			expect(label).toBeTruthy();
		}
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
