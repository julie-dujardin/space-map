/**
 * A trip end outside the solar system: a star or a planet of the extrasolar
 * catalogue. A star system is not an end. A trip to a star system goes to its
 * primary star. An end is made from the bodies that the scene's own loaders
 * make (`makeStarBody`, `makePlanetBodies`), so the planner puts an end where
 * the map draws it.
 *
 * Positions are in km on the ecliptic and equinox of J2000, with the origin at
 * the solar-system barycentre. This is the frame of `eclipticToScene`. Stars
 * do not move.
 *
 * A planet has the mass and the radius of its catalogue. When the catalogue
 * gives one of the two, the other comes from the mass–radius relation of Chen
 * & Kipping (2017, ApJ 834, 17). A planet with neither has no size.
 */

import {
	EXTRASOLAR_PREFIX,
	extrasolarObjectId,
	planetObjectId,
	planetOfObjectId
} from '$lib/fetch/extrasolar/ids';
import { extrasolarLookup, homeRow, systemPrimary } from '$lib/fetch/extrasolar/lookup';
import { planetCatalogue, type Planet } from '$lib/fetch/extrasolar/planets';
import { GM_SUN_KM3_S2, type TravelBody, type Vec3 } from '$lib/math/travel';
import { JUPITER_RADIUS_KM, SOLAR_RADIUS_KM } from '$lib/math/units';
import { sceneToEcliptic } from '$lib/scene/extensions/camera';
import { hostScene, makePlanetBodies } from '$lib/scene/exoplanets/bodies';
import { makeStarBody } from '$lib/scene/focus/star-focus';
import { starMass, type StarMass } from '$lib/scene/starfield/record';
import type {
	BodyData,
	OrbitalElements,
	PlanetAnchor,
	PositionedBody,
	StarAnchor
} from '$lib/types/objects';
import { hillRadiusAboutKm, systemOf } from './travel-body';

/** How a mass or a radius is known. `minimum` is the mass times the sine of the
 *  orbit's inclination. `estimated` is the estimate of a catalogue. `forecast`
 *  comes from the other value by the mass–radius relation. */
export type ValueBasis = 'measured' | 'minimum' | 'estimated' | 'forecast';

/** The star of an end: the end itself, or the host of a planet. */
export interface ExtrasolarStar {
	/** Scene id. */
	id: string;
	/** Where the map draws it, km. */
	positionKm: Vec3;
	/** km³/s², from the mass; null when the mass is unknown. */
	muKm3S2: number | null;
	/** Null when unknown. */
	radiusKm: number | null;
	/** The Metadata class: `star`, `white dwarf`, `brown dwarf`, `pulsar`,
	 *  `binary star` or `multiple star`. */
	class: string | null;
}

export interface PlanetSize {
	/** km³/s², from the mass. */
	muKm3S2: number;
	massBasis: ValueBasis;
	radiusKm: number;
	radiusBasis: ValueBasis;
}

export interface ExtrasolarPlanet {
	/** The orbit about the host star: AU, degrees, degrees per day and JD TDB.
	 *  A planet with no published orbit has the fixed place that the map gives it. */
	elements: OrbitalElements;
	/** False when the catalogue gives no semi-major axis. */
	orbitKnown: boolean;
	/** Null when the catalogue gives neither a mass nor a radius. */
	size: PlanetSize | null;
	/** The IAU class: `planet`, `brown dwarf` or `sub-brown dwarf`. */
	class: string | null;
	/** What the class rests on: `true mass`, `minimum mass`, `estimated mass` or `no mass`. */
	classBasis: string | null;
	/** True when the planet is small enough to be rock. See {@link ROCKY_RADIUS_EARTH}. */
	rocky: boolean;
}

export interface ExtrasolarEnd {
	/** The scene row of the end. */
	body: BodyData;
	/** The system of the end. See `systemOf`. */
	systemId: string;
	star: ExtrasolarStar;
	/** Null for a star. */
	planet: ExtrasolarPlanet | null;
}

/** IAU 2015 nominal values, km³/s² and km. */
const GM_EARTH_KM3_S2 = 3.986004e5;
const GM_JUPITER_KM3_S2 = 1.2668653e8;
const EARTH_RADIUS_KM = 6378.1;

/** Most planets above this radius, in Earth radii, have a thick envelope and
 *  are not rock (Rogers 2015, ApJ 801, 41). */
const ROCKY_RADIUS_EARTH = 1.6;

/** The mass–radius relation of Chen & Kipping (2017), Table 1: R = scale · M^slope
 *  in Earth radii and Earth masses on the Terran branch, then continuous across
 *  the Neptunian branch from 2.04 Earth masses and the Jovian branch from 0.414
 *  Jupiter masses. */
const TERRAN = { scale: 10 ** 0.00346, slope: 0.279 };
const NEPTUNIAN = { from: 2.04, slope: 0.589 };
const JOVIAN = { from: 131.6, slope: -0.044 };

export function radiusFromMassEarth(massEarth: number): number {
	const terran = (m: number) => TERRAN.scale * m ** TERRAN.slope;
	if (massEarth < NEPTUNIAN.from) return terran(massEarth);
	const neptunian = (m: number) => terran(NEPTUNIAN.from) * (m / NEPTUNIAN.from) ** NEPTUNIAN.slope;
	if (massEarth < JOVIAN.from) return neptunian(massEarth);
	return neptunian(JOVIAN.from) * (massEarth / JOVIAN.from) ** JOVIAN.slope;
}

/** The inverse of {@link radiusFromMassEarth}. A radius above the Neptunian
 *  branch gives no mass on the Jovian branch, so it takes the mass at the
 *  start of that branch. */
export function massFromRadiusEarth(radiusEarth: number): number {
	const neptunianFrom = radiusFromMassEarth(NEPTUNIAN.from);
	if (radiusEarth < neptunianFrom) return (radiusEarth / TERRAN.scale) ** (1 / TERRAN.slope);
	const radius = Math.min(radiusEarth, radiusFromMassEarth(JOVIAN.from));
	return NEPTUNIAN.from * (radius / neptunianFrom) ** (1 / NEPTUNIAN.slope);
}

function positive(value: unknown): number | null {
	return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

function massBasis(planet: Planet): ValueBasis {
	const kind = planet.values.mass_kind;
	if (kind === 'estimate' || planet.estimated.includes('mass')) return 'estimated';
	return kind === 'minimum' ? 'minimum' : 'measured';
}

function planetSize(planet: Planet): PlanetSize | null {
	const massJupiter = positive(planet.values.mass);
	const radiusJupiter = positive(planet.values.radius);
	if (massJupiter === null && radiusJupiter === null) return null;
	const muKm3S2 =
		massJupiter !== null
			? massJupiter * GM_JUPITER_KM3_S2
			: massFromRadiusEarth((radiusJupiter! * JUPITER_RADIUS_KM) / EARTH_RADIUS_KM) *
				GM_EARTH_KM3_S2;
	const radiusKm =
		radiusJupiter !== null
			? radiusJupiter * JUPITER_RADIUS_KM
			: radiusFromMassEarth(muKm3S2 / GM_EARTH_KM3_S2) * EARTH_RADIUS_KM;
	return {
		muKm3S2,
		massBasis: massJupiter === null ? 'forecast' : massBasis(planet),
		radiusKm,
		radiusBasis:
			radiusJupiter === null
				? 'forecast'
				: planet.estimated.includes('radius')
					? 'estimated'
					: 'measured'
	};
}

function elementsOf(body: BodyData): OrbitalElements {
	const { a, e, i, om, w, ma, n, epoch } = body;
	return { a, e, i, om, w, ma, n, epoch };
}

function muOf(mass: StarMass | null): number | null {
	return mass && mass.solar * GM_SUN_KM3_S2;
}

function starEnd(body: PositionedBody, star: StarAnchor): ExtrasolarEnd | null {
	if (!star.scene) return null;
	return {
		body: body.data,
		systemId: systemOf(body.data.id),
		star: {
			id: body.data.id,
			positionKm: sceneToEcliptic(star.scene),
			muKm3S2: muOf(starMass(homeRow(star.record))),
			radiusKm: star.radiusKm,
			class: star.record.metadata.class
		},
		planet: null
	};
}

/** A planet end. Its star has the values of the star end of `host`, the
 *  scene's anchor of the host. The fits of the planet fill a value that the
 *  host lacks. Without `host`, the star is where the system file puts it. */
function planetEnd(
	body: PositionedBody,
	anchor: PlanetAnchor,
	host: StarAnchor | null
): ExtrasolarEnd | null {
	const { planet, hostRecord } = anchor;
	const at = host?.scene ?? hostScene(hostRecord);
	if (!at) return null;
	const fitRadius = positive(planet.values.star_radius);
	const size = planetSize(planet);
	return {
		body: body.data,
		systemId: systemOf(body.data.id),
		star: {
			id: extrasolarObjectId(anchor.host),
			positionKm: sceneToEcliptic(at),
			muKm3S2: muOf(starMass(host && homeRow(host.record), planet)),
			radiusKm: host?.radiusKm ?? (fitRadius && fitRadius * SOLAR_RADIUS_KM),
			class: hostRecord.class
		},
		planet: {
			elements: elementsOf(body.data),
			orbitKnown: planet.elements !== null,
			size,
			class: planet.class,
			classBasis: planet.class_basis,
			rocky:
				planet.class === 'planet' &&
				size !== null &&
				size.radiusKm <= ROCKY_RADIUS_EARTH * EARTH_RADIUS_KM
		}
	};
}

/** The end that a body of the scene is. `host` is the scene's body of a
 *  planet's host star. Null for a body of the solar system, and for a star or a
 *  planet that the map does not place. */
export function extrasolarEndOf(
	body: PositionedBody,
	host: PositionedBody | null = null
): ExtrasolarEnd | null {
	if (body.exoplanet) return planetEnd(body, body.exoplanet, host?.extrasolar ?? null);
	if (body.extrasolar) return starEnd(body, body.extrasolar);
	return null;
}

/** A star or a star system, placed as the scene places it. A host with no
 *  distance of its own takes the place that the planet index gives it. */
async function starBody(objectId: string): Promise<PositionedBody | null> {
	const found = await extrasolarLookup.live(objectId.slice(EXTRASOLAR_PREFIX.length));
	if (found.kind !== 'live') return null;
	const body = makeStarBody(found.record);
	const star = body.extrasolar!;
	star.scene ??= hostScene((await planetCatalogue.index())?.host(found.record.id));
	return body;
}

/** The star that a trip to a star or a star system goes to. A system's primary
 *  is a point, so one step reaches a star. */
async function tripStarBody(objectId: string): Promise<PositionedBody | null> {
	const body = await starBody(objectId);
	const star = body?.extrasolar;
	const primary = star ? systemPrimary(star.record) : null;
	return primary === null || primary === star!.id ? body : starBody(extrasolarObjectId(primary));
}

/** The live planet that a planet's page leads to, maybe through an alias. */
async function planetBody(host: number, n: number): Promise<PositionedBody | null> {
	const found = await planetCatalogue.planet(host, n);
	if (!found) return null;
	const id = planetObjectId(found.planet.host, found.planet.number);
	return makePlanetBodies(found.system).find((b) => b.data.id === id) ?? null;
}

/** The host star of a planet, as the scene draws it. A host that does not load
 *  leaves the planet's star where the system file puts it. */
function hostBody(planet: PositionedBody): Promise<PositionedBody | null> {
	return starBody(extrasolarObjectId(planet.exoplanet!.host)).catch((e) => {
		console.warn(`[travel] no record of the host of ${planet.data.id}:`, e);
		return null;
	});
}

/** The end that a scene id names, read from the extrasolar export. The end of
 *  an alias is its live object, and the end of a star system is its primary
 *  star. Null when the export has no such object, when the map does not place
 *  it, or when a file does not load. */
export async function resolveExtrasolarEnd(objectId: string): Promise<ExtrasolarEnd | null> {
	try {
		const planet = planetOfObjectId(objectId);
		const body = planet ? await planetBody(planet.host, planet.n) : await tripStarBody(objectId);
		const host = body?.exoplanet ? await hostBody(body) : null;
		const end = body && extrasolarEndOf(body, host);
		if (!end) {
			console.debug(`[travel] ${objectId} has no place in the extrasolar export.`);
			return null;
		}
		return end;
	} catch (e) {
		console.warn(`[travel] could not read ${objectId} from the extrasolar export:`, e);
		return null;
	}
}

/** The kernel's view of an end; null for a planet with no size. A star is met
 *  or passed, so no price reads its μ. */
export function extrasolarTravelBody(end: ExtrasolarEnd): TravelBody | null {
	const { body, star, planet } = end;
	if (!planet) {
		return {
			id: body.id,
			mu: star.muKm3S2 ?? 0,
			muEstimated: true,
			radiusKm: star.radiusKm ?? 1,
			elements: elementsOf(body)
		};
	}
	const size = planet.size;
	if (!size) return null;
	return {
		id: body.id,
		mu: size.muKm3S2,
		muEstimated: size.massBasis !== 'measured',
		radiusKm: size.radiusKm,
		elements: planet.elements,
		// A planet that is not rock has an envelope and no ground under it.
		hasAtmosphere: planet.rocky ? undefined : true,
		hillKm: planet.orbitKnown
			? hillRadiusAboutKm(planet.elements, size.muKm3S2, star.muKm3S2 ?? undefined)
			: undefined,
		parentId: star.id
	};
}
