import { describe, expect, it } from 'vitest';
import { EARTH } from '$lib/math/travel/test-fixtures';
import { CLASS_SLUG_PREFIX, classifyEarthOrbit } from '$lib/charts/orbit-zones';
import { orbitChoices, type OrbitFacts } from './orbits';
import { ZONE_TARGETS, orbitZoneTarget, type OrbitZoneTarget } from './orbit-zone-target';

/** Earth's sidereal day, hours, and the Hill radius its orbit gives it, km. */
const EARTH_FACTS: OrbitFacts = { rotationHours: 23.9345, hillKm: 1.496e6 };

/** Every zone the orbit a target names falls in — its shape, and the band its
 *  plane puts it in where it has one. */
function zonesOf(target: OrbitZoneTarget): string[] {
	const choice = orbitChoices(EARTH, EARTH_FACTS, 'target', {
		hasSurface: true,
		customAltKm: target.altKm ?? 1000,
		incDeg: target.incDeg ?? null
	}).find((c) => c.kind === target.mode);
	if (choice?.periAltKm === undefined || choice.apoAltKm === undefined) return [];
	return classifyEarthOrbit(choice.periAltKm, choice.apoAltKm, target.incDeg ?? null);
}

describe('orbit zone targets', () => {
	it('arrives in the zone whose page offered the trip', () => {
		for (const [className, target] of Object.entries(ZONE_TARGETS)) {
			expect(zonesOf(target), className).toContain(className);
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

	// One orbit, three zones: the plane is the whole of what tells them apart, and
	// only the custom orbit has one, so the named orbit keeps the plane-free zone.
	it('separates the three zones of the stationary belt by plane alone', () => {
		expect(zonesOf(ZONE_TARGETS.GSO)).toEqual(['GSO']);
		expect(zonesOf(ZONE_TARGETS.GEO)).toEqual(['GEO']);
		expect(zonesOf(ZONE_TARGETS.IGSO)).toEqual(['IGSO']);
		expect(ZONE_TARGETS.GSO.incDeg).toBeUndefined();
	});

	// Left out for a reason rather than overlooked: an orbit with its two ends set
	// apart, which no offered shape and no custom orbit has, and an apogee past
	// the third of the Hill radius Earth holds an orbit within.
	it('leaves out the zones no offered orbit reaches', () => {
		for (const className of ['HEO', 'TUN', 'MOL', 'VHEO', 'EL1', 'EL2']) {
			expect(orbitZoneTarget(`${CLASS_SLUG_PREFIX}${className}`), className).toBeNull();
		}
	});

	it('reads a zone page slug, and no other collection', () => {
		expect(orbitZoneTarget(`${CLASS_SLUG_PREFIX}MEO`)).toEqual({ mode: 'semi-sync' });
		expect(orbitZoneTarget('const-starlink')).toBeNull();
	});
});
