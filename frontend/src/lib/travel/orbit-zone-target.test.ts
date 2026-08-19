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
		customApoAltKm: target.apoAltKm,
		incDeg: target.incDeg ?? null,
		argPeriDeg: target.argPeriDeg ?? null
	}).find((c) => c.kind === target.mode);
	if (choice?.periAltKm === undefined || choice.apoAltKm === undefined) return [];
	// The plane read off the orbit rather than off the target: a named orbit can
	// carry one the page never asked for.
	return classifyEarthOrbit(choice.periAltKm, choice.apoAltKm, choice.orbit?.incDeg ?? null);
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
				classifyEarthOrbit(choice.periAltKm, choice.apoAltKm, choice.orbit?.incDeg ?? null)[0]
			);
		}
	});

	// One orbit, three zones: the plane is the whole of what tells them apart. The
	// named orbit is the equatorial one, so it takes GEO, and the two the page
	// leaves open go to the custom orbit.
	it('separates the three zones of the stationary belt by plane alone', () => {
		expect(zonesOf(ZONE_TARGETS.GSO)).toEqual(['GSO']);
		expect(zonesOf(ZONE_TARGETS.GEO)).toEqual(['GEO']);
		expect(zonesOf(ZONE_TARGETS.IGSO)).toEqual(['IGSO']);
		expect(ZONE_TARGETS.GSO.incDeg).toBeUndefined();
	});

	// The three eccentric zones are the custom orbit's, and are told apart from
	// each other by plane as much as by shape — a Molniya flown level is an
	// ordinary highly elliptical orbit.
	it('separates the eccentric zones', () => {
		expect(zonesOf(ZONE_TARGETS.HEO)).toEqual(['HEO']);
		expect(zonesOf(ZONE_TARGETS.MOL)).toEqual(['MOL']);
		expect(zonesOf(ZONE_TARGETS.TUN)).toEqual(['TUN']);
		expect(ZONE_TARGETS.HEO.incDeg).toBeUndefined();
	});

	// Left out for a reason rather than overlooked: an apogee past the third of
	// the Hill radius Earth holds an orbit within, and two points that are not
	// orbits about Earth at all.
	it('leaves out the zones no offered orbit reaches', () => {
		for (const className of ['VHEO', 'EL1', 'EL2']) {
			expect(orbitZoneTarget(`${CLASS_SLUG_PREFIX}${className}`), className).toBeNull();
		}
	});

	it('reads a zone page slug, and no other collection', () => {
		expect(orbitZoneTarget(`${CLASS_SLUG_PREFIX}MEO`)).toEqual({ mode: 'semi-sync' });
		expect(orbitZoneTarget('const-starlink')).toBeNull();
	});
});
