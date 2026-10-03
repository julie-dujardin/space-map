/**
 * A planetary system as a system map: moons on a domain in primary radii that
 * follows the system, sized so the largest moon reads at TOP_MOON_R — which
 * keeps moon-against-moon true, the comparison the map is about.
 */

import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
import type { PlanetarySystemsMapEntry } from '$lib/fetch/groups/planetary-systems-map';
import type { MapBand, MapCloud, MapLink, MapText, SystemMapModel } from './model';

export interface SystemMoon {
	id: string;
	name: string;
	/** Orbit semi-major axis in primary equatorial radii — the map's x axis. */
	aRp: number;
	/** Orbit tilt to the *primary's equator* [deg]; > 90° is retrograde about the
	 *  primary. The exported elements are ecliptic, which would read the primary's
	 *  own obliquity as inclination and lay the whole regular system off-axis. */
	tiltDeg: number;
	radiusKm: number;
	color: string;
}

export interface SystemRings {
	/** Ring span in primary equatorial radii, across every ring bundle. */
	innerRp: number;
	outerRp: number;
}

/** What the system map draws — built from the live scene on a system page,
 *  or from the export's baked maps anywhere the scene is not. */
export interface PlanetarySystemMapData {
	planetId: string;
	planetName: string;
	planetRadiusKm: number;
	planetColor: string;
	moons: SystemMoon[];
	rings: SystemRings | null;
	/** Moons the catalogue knows about, which is more than the scene loads. */
	moonCount: number;
}

/** A baked map entry as the system map draws it. */
export function systemFromMapEntry(
	entry: PlanetarySystemsMapEntry,
	name: string
): PlanetarySystemMapData {
	return {
		planetId: entry.primary.id,
		planetName: name,
		planetRadiusKm: entry.primary.radius_km,
		planetColor: BODY_COLORS[entry.primary.id] ?? DEFAULT_BODY_COLOR,
		moons: entry.moons.map((mn) => ({
			id: mn.id,
			name: mn.id,
			aRp: mn.a_rp,
			tiltDeg: mn.tilt_deg,
			radiusKm: mn.radius_km,
			color: BODY_COLORS[mn.id] ?? mn.color ?? DEFAULT_BODY_COLOR
		})),
		rings: entry.rings ? { innerRp: entry.rings.inner_rp, outerRp: entry.rings.outer_rp } : null,
		moonCount: entry.moon_count
	};
}

const TOP_MOON_R = 14;
/** Below this, in primary radii, a band's inner edge *is* the limb. */
const AT_SURFACE = 1.001;
const PX_PER_DEG = 0.62;
/** Axis ticks, in primary radii — the decade ladder, trimmed to the domain. */
const TICK_LADDER = [1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500, 1000, 2000, 5000];
// Tile crop: the primary's limb and the moons nearest it, framed so the
// baseline rides in the upper third — a caption takes the lower half, and
// moons drawn behind the text read as dirt on the picture.
const BG_VIEW = '0 96 320 144';
/** A full-width tile has room for the whole axis, shown whole and centred. */
const BG_VIEW_WIDE = '0 96 720 144';
/** What a system with nothing on its axis is framed on. */
const EMPTY_DOMAIN: [number, number] = [1, 100];

export interface PlanetaryParts {
	text: MapText;
	axisLabel: string;
	bands: MapBand[];
	cloud?: MapCloud;
	primaryLink?: MapLink;
	moonLink?: (moon: SystemMoon) => MapLink | undefined;
	/** Background on a tile spanning the row: the whole axis fits. */
	wide?: boolean;
}

/** Log domain over the moons and bands actually present, padded a little
 *  either side so nothing sits on an edge. A band that reaches the datum keeps
 *  the low end unpadded instead: the primary's limb is drawn at the axis
 *  origin, and padding below 1 would open a gap between the limb and the
 *  lowest orbit above it. */
function domainOf(system: PlanetarySystemMapData, bands: MapBand[]): [number, number] {
	let lo = Math.min(...system.moons.map((mn) => mn.aRp));
	let hi = Math.max(...system.moons.map((mn) => mn.aRp));
	for (const b of bands) {
		lo = Math.min(lo, b.innerKm / system.planetRadiusKm);
		hi = Math.max(hi, b.outerKm / system.planetRadiusKm);
	}
	if (!Number.isFinite(lo) || !Number.isFinite(hi)) return EMPTY_DOMAIN;
	if (hi <= lo) {
		// A lone moon has no span of its own; give it one centred on itself.
		lo /= 2;
		hi *= 2;
	}
	// Snapped, because a band drawn from the datum misses 1 R_p by under a
	// metre — the altitudes are measured from the reference ellipsoid, the
	// axis from the export's triaxial radius.
	lo = lo <= AT_SURFACE ? 1 : lo;
	return [lo > 1 ? 10 ** (Math.log10(lo) - 0.12) : 1, 10 ** (Math.log10(hi) + 0.12)];
}

export function planetarySystemModel(
	system: PlanetarySystemMapData,
	parts: PlanetaryParts
): SystemMapModel {
	const rKm = system.planetRadiusKm;
	const domain = domainOf(system, parts.bands);
	return {
		primary: {
			id: system.planetId,
			name: system.planetName,
			radiusKm: rKm,
			color: system.planetColor,
			link: parts.primaryLink
		},
		bodies: system.moons.map((mn) => ({
			id: mn.id,
			name: mn.name,
			aKm: mn.aRp * rKm,
			tiltDeg: mn.tiltDeg,
			radiusKm: mn.radiusKm,
			color: mn.color,
			link: parts.moonLink?.(mn)
		})),
		bands: parts.bands,
		cloud: parts.cloud,
		unitKm: rKm,
		domain,
		ticks: TICK_LADDER.filter((t) => t >= domain[0] && t <= domain[1]),
		axisLabel: parts.axisLabel,
		// Sized off the largest *measured* moon: most of a giant's swarm is
		// designation-only with no radius at all, and one of those in the max
		// would take the whole scale to NaN.
		pxPerKm:
			TOP_MOON_R / Math.max(...system.moons.map((mn) => mn.radiusKm).filter((r) => r > 0), 1),
		pxPerDeg: PX_PER_DEG,
		text: parts.text,
		backgroundView: parts.wide ? BG_VIEW_WIDE : BG_VIEW,
		backgroundFit: parts.wide ? 'fit' : 'slice'
	};
}
