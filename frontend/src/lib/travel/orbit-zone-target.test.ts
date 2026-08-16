import { describe, expect, it } from 'vitest';
import { EARTH } from '$lib/math/travel/test-fixtures';
import { CLASS_SLUG_PREFIX, classifyEarthOrbit } from '$lib/charts/orbit-zones';
import { orbitChoices, type OrbitFacts } from './orbits';
import { ZONE_TARGETS, orbitZoneTarget } from './orbit-zone-target';

/** Earth's sidereal day, hours, and the Hill radius its orbit gives it, km. */
const EARTH_FACTS: OrbitFacts = { rotationHours: 23.9345, hillKm: 1.496e6 };

/** The zone a mode's orbit falls in, by the same rules the pages bucket sats
 *  with. Inclination goes unstated: the model never charges for a plane. */
function zoneOf(target: { mode: string; altKm?: number }): string | undefined {
	const choice = orbitChoices(EARTH, EARTH_FACTS, 'target', {
		hasSurface: true,
		customAltKm: target.altKm ?? 1000
	}).find((c) => c.kind === target.mode);
	if (choice?.periAltKm === undefined || choice.apoAltKm === undefined) return undefined;
	return classifyEarthOrbit(choice.periAltKm, choice.apoAltKm, null)[0];
}

describe('orbit zone targets', () => {
	it('arrives in the zone whose page offered the trip', () => {
		for (const [className, target] of Object.entries(ZONE_TARGETS)) {
			// GEO is GSO's equatorial case, and the plane is the one thing the
			// classifier reads that the planner does not model.
			const expected = className === 'GEO' ? 'GSO' : className;
			expect(zoneOf(target), className).toBe(expected);
		}
	});

	it('offers a page for every orbit an arrival can be made in', () => {
		const zones = new Set(Object.keys(ZONE_TARGETS));
		for (const choice of orbitChoices(EARTH, EARTH_FACTS, 'target', {
			hasSurface: true,
			customAltKm: 1000
		})) {
			if (choice.periAltKm === undefined || choice.apoAltKm === undefined) continue;
			expect(zones, choice.kind).toContain(
				classifyEarthOrbit(choice.periAltKm, choice.apoAltKm, null)[0]
			);
		}
	});

	it('reads a zone page slug, and no other collection', () => {
		expect(orbitZoneTarget(`${CLASS_SLUG_PREFIX}MEO`)).toEqual({ mode: 'semi-sync' });
		expect(orbitZoneTarget(`${CLASS_SLUG_PREFIX}SSO`)).toBeNull();
		expect(orbitZoneTarget('const-starlink')).toBeNull();
	});
});
