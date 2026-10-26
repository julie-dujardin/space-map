/**
 * The bodies of a planetary system file. A planet orbits the body of its
 * host star (`x-<host>`) by the elements of the file, which are already in
 * the scene's frame. Each planet orbits its own host, so the two stars of a
 * binary each carry their own planets.
 */

import { OrbitalSource } from '$lib/fetch/position/format';
import { extrasolarObjectId, planetObjectId } from '$lib/fetch/extrasolar/ids';
import type { Planet, PlanetElements, PlanetSystem } from '$lib/fetch/extrasolar/planets';
import { J2000_JD } from '$lib/time/jd';
import { ObjectType, type BodyData, type PositionedBody } from '$lib/types/objects';

const JUPITER_RADIUS_KM = 71_492;
/** The span (AU) of a host none of whose planets has a semi-major axis. */
export const NO_ORBIT_AU = 1;
/** A planet with no orbit sits still this many outer orbits from its host. */
export const NO_ORBIT_FACTOR = 1.5;

/** The largest semi-major axis (AU) of `planets`, or null when none has one. */
export function outerOrbitAU(planets: readonly Planet[]): number | null {
	return outermostElements(planets)?.a ?? null;
}

/** The planet with the largest orbit: its plane is the system's plane. */
export function outermostElements(planets: readonly Planet[]): PlanetElements | null {
	let out: PlanetElements | null = null;
	for (const p of planets) {
		if (p.elements && (out === null || p.elements.a > out.a)) out = p.elements;
	}
	return out;
}

/**
 * The bodies of every planet in `file`. A planet with no elements has a
 * fixed place: {@link NO_ORBIT_FACTOR} outer orbits from its host, in the
 * plane of the host's outermost orbit (the ecliptic when there is none), the
 * k-th of m such planets of one host at mean anomaly 360·k/m.
 */
export function makePlanetBodies(file: PlanetSystem): PositionedBody[] {
	const out: PositionedBody[] = [];
	for (const hostRecord of file.hosts) {
		const planets = file.planets.filter((p) => p.host === hostRecord.id);
		const plane = outermostElements(planets);
		const fixedA = NO_ORBIT_FACTOR * (outerOrbitAU(planets) ?? NO_ORBIT_AU);
		const fixed = planets.filter((p) => !p.elements);
		for (const planet of planets) {
			const elements: PlanetElements = planet.elements ?? {
				a: fixedA,
				e: 0,
				i: plane?.i ?? 0,
				om: plane?.om ?? 0,
				w: 0,
				ma: (360 * fixed.indexOf(planet)) / fixed.length,
				n: 0,
				epoch: J2000_JD,
				phase: 'assumed'
			};
			out.push(planetBody(planet, elements, planet.elements !== null, file, hostRecord));
		}
	}
	return out;
}

function planetBody(
	planet: Planet,
	elements: PlanetElements,
	orbit: boolean,
	file: PlanetSystem,
	hostRecord: PlanetSystem['hosts'][number]
): PositionedBody {
	const radiusRj = planet.values.radius;
	const parentId = extrasolarObjectId(planet.host);
	const data: BodyData = {
		id: planetObjectId(planet.host, planet.number),
		name: planet.name,
		objectType: ObjectType.EXOPLANET,
		parentId,
		radiusKm: typeof radiusRj === 'number' && radiusRj > 0 ? radiusRj * JUPITER_RADIUS_KM : NaN,
		hasLocalized: false,
		a: elements.a,
		e: elements.e,
		i: elements.i,
		om: elements.om,
		w: elements.w,
		ma: elements.ma,
		n: elements.n,
		epoch: elements.epoch,
		validityStart: -Infinity,
		validityEnd: Infinity,
		orbitalSource: OrbitalSource.UNKNOWN
	};
	return {
		data,
		position: null,
		// No orbit line for a planet with no orbit.
		...(orbit ? { orbitElements: data, orbitCenterId: parentId } : {}),
		exoplanet: {
			host: planet.host,
			number: planet.number,
			system: file.system,
			planet,
			hostRecord
		}
	};
}
