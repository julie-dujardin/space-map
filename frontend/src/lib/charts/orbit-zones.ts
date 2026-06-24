/**
 * Orbit-class zone polygons for the small-body scatter plot.
 *
 * Asteroids plot on (a, q) — semi-major axis vs perihelion. Comets get two
 * switchable plots: bound families on (a, T_J) where each SBDB class is a
 * rectangle, and unbound/unclassified trajectories on (e, q) since
 * hyperbolic/parabolic comets have undefined or negative a.
 *
 * The (a, T_J) family rectangles tile without overlap, matching how SBDB
 * assigns exactly one class per object: the Tisserand families (JFc/ETc/CTc)
 * take priority over the classical period families (JFC/HTC), so JFC/HTC are
 * clipped to the T_J < 2 strip they actually occupy in the catalog.
 */

import * as m from '$lib/paraglide/messages.js';
import { CAT_ASTEROIDS, CAT_COMETS, CAT_SATELLITES } from '$lib/fetch/groups/registry';

export type PlotType = 'a-q' | 'q-e' | 'a-T' | 'peri-apo';

/** Polygon vertex (x, y); units are AU for a-q/q-e, km for peri-apo. */
export type ZonePoint = { x: number; y: number };

/** Mirrors the OrbitClassSample shape in
 *  `data/src/space_map_data/export/groups/small_body.py`. */
export interface OrbitSample {
	slug: string;
	name: string;
	a: number | null;
	e: number;
	q: number;
	i: number | null;
	neo: boolean;
	pha: boolean;
}

/** Mirrors EarthOrbitSample in the export; `classes` lists every zone hit. */
export interface EarthOrbitSample {
	slug: string;
	name: string;
	perigee_km: number;
	apogee_km: number;
	inclination_deg: number | null;
	classes: string[];
}

export interface OrbitZone {
	className: string;
	plotType: PlotType;
	/** Closed polygon vertices; empty = inc-only zone, no peri-apo footprint. */
	polygon: ZonePoint[];
	tooltipDefinition: () => string;
}

/** Focused-zone colors keyed close to the matching point-cloud hue:
 *  Earth sat cloud is `#bed4ec`, asteroid `#ccb49a`, comet `#d8ffe8`. */
export const FOCUS_COLORS: Record<PlotType, string> = {
	'peri-apo': '#7fb3e6',
	'a-q': '#d4a373',
	'q-e': '#88d4a8',
	'a-T': '#88d4a8'
};

export const AJ = 5.2038; // Jupiter semi-major axis [AU], standard Tisserand reference

/** Period cuts as semi-major axes (P² = a³): P < 20 y and P < 200 y. */
export const A_P20 = Math.pow(20, 2 / 3); // ≈ 7.37 AU
export const A_P200 = Math.pow(200, 2 / 3); // ≈ 34.2 AU

/** Chart bounds for the comet plots; zone rectangles are cut to these. */
export const AT_DOMAIN = { x: [1, 60] as [number, number], y: [-2, 4] as [number, number] };
export const QE_DOMAIN = { x: [0.9, 1.3] as [number, number], y: [0, 12] as [number, number] };

/**
 * Tisserand parameter w.r.t. Jupiter:
 * T_J = a_J/a + 2·cos(i)·√((a/a_J)(1−e²)). Null for unbound orbits.
 */
export function tisserand(a: number, e: number, iDeg: number): number | null {
	if (a <= 0 || e >= 1) return null;
	const cosI = Math.cos((iDeg * Math.PI) / 180);
	return AJ / a + 2 * cosI * Math.sqrt((a / AJ) * (1 - e * e));
}

function rect(x1: number, x2: number, y1: number, y2: number): ZonePoint[] {
	return [
		{ x: x1, y: y1 },
		{ x: x2, y: y1 },
		{ x: x2, y: y2 },
		{ x: x1, y: y2 }
	];
}

/**
 * Map of every plottable orbit class. The shared `__orbit_samples__.json`
 * exporter (`build_orbit_class_samples`) emits one zone per OrbitClass enum
 * member that has rows; missing keys here mean "no clickable polygon"
 * (samples are still drawn as background dots when another zone is focused).
 * A class may appear on several plots under distinct keys (e.g. COM/COM_AT);
 * the className-keyed entry decides its default plot.
 */
export const ORBIT_ZONES: Record<string, OrbitZone> = {
	// AST/COM are "no other match" catch-alls. The other classes tile the
	// space, so each catch-all is drawn as the exact gap they leave open
	// (verified against SBDB: every AST object falls in this pocket).
	AST: {
		className: 'AST',
		plotType: 'a-q',
		// Jupiter-region orbits failing TJN's e < 0.3 cut: 4.6 < a < 5.5,
		// q above the Amor cut (1.3) and below the e = 0.3 line (q = 0.7a).
		polygon: [
			{ x: 4.6, y: 1.3 },
			{ x: 5.5, y: 1.3 },
			{ x: 5.5, y: 3.85 },
			{ x: 4.6, y: 3.22 }
		],
		tooltipDefinition: () => m.zone_def_AST()
	},
	COM: {
		className: 'COM',
		plotType: 'q-e',
		// Bound (e < 1) but not in any family — mostly long-period comets.
		polygon: rect(0, 1, QE_DOMAIN.y[0], QE_DOMAIN.y[1]),
		tooltipDefinition: () => m.zone_def_COM()
	},
	IEO: {
		className: 'IEO',
		plotType: 'a-q',
		// Q < 0.983: q > 2a − 0.983. Right boundary hits q=0 at a=0.4915
		// and the q=a apex at a=0.983.
		polygon: [
			{ x: 0, y: 0 },
			{ x: 0.4915, y: 0 },
			{ x: 0.983, y: 0.983 }
		],
		tooltipDefinition: () => m.zone_def_IEO()
	},
	ATE: {
		className: 'ATE',
		plotType: 'a-q',
		// Inner edge is the Q=0.983 line shared with IEO.
		polygon: [
			{ x: 0.4915, y: 0 },
			{ x: 1.0, y: 0 },
			{ x: 1.0, y: 1.0 },
			{ x: 0.983, y: 0.983 }
		],
		tooltipDefinition: () => m.zone_def_ATE()
	},
	APO: {
		className: 'APO',
		plotType: 'a-q',
		polygon: [
			{ x: 1.0, y: 0 },
			{ x: 5.5, y: 0 },
			{ x: 5.5, y: 1.017 },
			{ x: 1.017, y: 1.017 },
			{ x: 1.0, y: 1.0 }
		],
		tooltipDefinition: () => m.zone_def_APO()
	},
	AMO: {
		className: 'AMO',
		plotType: 'a-q',
		polygon: [
			{ x: 1.017, y: 1.017 },
			{ x: 5.5, y: 1.017 },
			{ x: 5.5, y: 1.3 },
			{ x: 1.3, y: 1.3 }
		],
		tooltipDefinition: () => m.zone_def_AMO()
	},
	MCA: {
		className: 'MCA',
		plotType: 'a-q',
		polygon: [
			{ x: 1.3, y: 1.3 },
			{ x: 3.2, y: 1.3 },
			{ x: 3.2, y: 1.666 },
			{ x: 1.666, y: 1.666 }
		],
		tooltipDefinition: () => m.zone_def_MCA()
	},
	IMB: {
		className: 'IMB',
		plotType: 'a-q',
		polygon: [
			{ x: 1.666, y: 1.666 },
			{ x: 2.0, y: 1.666 },
			{ x: 2.0, y: 2.0 }
		],
		tooltipDefinition: () => m.zone_def_IMB()
	},
	MBA: {
		className: 'MBA',
		plotType: 'a-q',
		polygon: [
			{ x: 2.0, y: 1.666 },
			{ x: 3.2, y: 1.666 },
			{ x: 3.2, y: 3.2 },
			{ x: 2.0, y: 2.0 }
		],
		tooltipDefinition: () => m.zone_def_MBA()
	},
	OMB: {
		className: 'OMB',
		plotType: 'a-q',
		// No q > 1.666 floor like MBA — SBDB OMB runs down to the Amor cut
		// (q = 1.3); 1.3 < q < 1.666 only counts as Mars-crossing for a < 3.2.
		polygon: [
			{ x: 3.2, y: 1.3 },
			{ x: 4.6, y: 1.3 },
			{ x: 4.6, y: 4.6 },
			{ x: 3.2, y: 3.2 }
		],
		tooltipDefinition: () => m.zone_def_OMB()
	},
	TJN: {
		className: 'TJN',
		plotType: 'a-q',
		// Thin strip around 5.2 AU. Real definition (1:1 resonance + e<0.3)
		// projects to "a ≈ 5.2, q > 0.7·a" — see tooltip.
		polygon: [
			{ x: 4.6, y: 3.22 },
			{ x: 5.5, y: 3.85 },
			{ x: 5.5, y: 5.5 },
			{ x: 4.6, y: 4.6 }
		],
		tooltipDefinition: () => m.zone_def_TJN()
	},
	CEN: {
		className: 'CEN',
		plotType: 'a-q',
		polygon: [
			{ x: 5.5, y: 0 },
			{ x: 30.1, y: 0 },
			{ x: 30.1, y: 30.1 },
			{ x: 5.5, y: 5.5 }
		],
		tooltipDefinition: () => m.zone_def_CEN()
	},
	TNO: {
		className: 'TNO',
		plotType: 'a-q',
		polygon: [
			{ x: 30.1, y: 0 },
			{ x: 1000, y: 0 },
			{ x: 1000, y: 1000 },
			{ x: 30.1, y: 30.1 }
		],
		tooltipDefinition: () => m.zone_def_TNO()
	},
	// --- Comet families (a-T plot): SBDB rectangles, tiled to match the
	// catalog's one-class-per-object priority (Tisserand families win over the
	// classical period ones). COM catch-all fills the leftover corner: bound,
	// T_J < 2, P > 200 y.
	COM_AT: {
		className: 'COM',
		plotType: 'a-T',
		polygon: rect(A_P200, AT_DOMAIN.x[1], AT_DOMAIN.y[0], 2),
		tooltipDefinition: () => m.zone_def_COM()
	},
	HTC: {
		className: 'HTC',
		plotType: 'a-T',
		// 20 < P < 200 y, T_J < 2; starts at A_P20 where JFC ends.
		polygon: rect(A_P20, A_P200, AT_DOMAIN.y[0], 2),
		tooltipDefinition: () => m.zone_def_HTC()
	},
	JFC: {
		className: 'JFC',
		plotType: 'a-T',
		// Classical P < 20 y; clipped to T_J < 2 since JFc/ETc/CTc rank higher.
		polygon: rect(AT_DOMAIN.x[0], A_P20, AT_DOMAIN.y[0], 2),
		tooltipDefinition: () => m.zone_def_JFC()
	},
	JFc: {
		className: 'JFc',
		plotType: 'a-T',
		polygon: rect(AT_DOMAIN.x[0], AT_DOMAIN.x[1], 2, 3),
		tooltipDefinition: () => m.zone_def_JFc()
	},
	ETc: {
		className: 'ETc',
		plotType: 'a-T',
		polygon: rect(AT_DOMAIN.x[0], AJ, 3, AT_DOMAIN.y[1]),
		tooltipDefinition: () => m.zone_def_ETc()
	},
	CTc: {
		className: 'CTc',
		plotType: 'a-T',
		polygon: rect(AJ, AT_DOMAIN.x[1], 3, AT_DOMAIN.y[1]),
		tooltipDefinition: () => m.zone_def_CTc()
	},
	// --- Unbound trajectories (q-e plot). Asteroid-designated twins (HYA/PAA)
	// sit under their comet counterparts; the thin e=1 bands render on top.
	HYA: {
		className: 'HYA',
		plotType: 'q-e',
		polygon: rect(1, QE_DOMAIN.x[1], QE_DOMAIN.y[0], QE_DOMAIN.y[1]),
		tooltipDefinition: () => m.zone_def_HYA()
	},
	HYP: {
		className: 'HYP',
		plotType: 'q-e',
		polygon: rect(1, QE_DOMAIN.x[1], QE_DOMAIN.y[0], QE_DOMAIN.y[1]),
		tooltipDefinition: () => m.zone_def_HYP()
	},
	PAA: {
		className: 'PAA',
		plotType: 'q-e',
		polygon: rect(0.99, 1.01, QE_DOMAIN.y[0], QE_DOMAIN.y[1]),
		tooltipDefinition: () => m.zone_def_PAA()
	},
	PAR: {
		className: 'PAR',
		plotType: 'q-e',
		// e ≈ 1 — render as a thin band at e = 1
		polygon: rect(0.99, 1.01, QE_DOMAIN.y[0], QE_DOMAIN.y[1]),
		tooltipDefinition: () => m.zone_def_PAR()
	}
};

/** Geostationary altitude (km above Earth surface). */
export const GEO_ALT_KM = 35786;

export const R_EARTH_KM = 6378.137;

/**
 * Earth-orbit zones for a sat given perigee/apogee/inclination.
 * Mirror of `classify_earth_orbit` in the data tier — kept in sync by hand.
 * Returns one shape class plus at most one inclination band.
 */
export function classifyEarthOrbit(
	perigeeKm: number | null | undefined,
	apogeeKm: number | null | undefined,
	inclinationDeg: number | null | undefined
): string[] {
	if (perigeeKm == null || apogeeKm == null) return [];
	const classes = [shapeClass(perigeeKm, apogeeKm, inclinationDeg)];
	if (apogeeKm < 2000 && inclinationDeg != null) {
		const band = inclinationBand(inclinationDeg);
		if (band != null) classes.push(band);
	}
	return classes;
}

function shapeClass(peri: number, apo: number, inc: number | null | undefined): string {
	if (apo < 600) return 'VLEO';
	if (apo < 2000) return 'LEO';
	const inGsoBand = Math.abs(peri - GEO_ALT_KM) < 2000 && Math.abs(apo - GEO_ALT_KM) < 2000;
	if (inGsoBand) {
		// Graveyard sats sit in the GSO band but are no longer station-kept,
		// so geometry trumps inclination. IGSO has no inclination cap
		// (BeiDou/QZSS fly at 43-55 deg).
		if (peri >= GEO_ALT_KM + 200) return 'GRA';
		if (inc == null) return 'GSO';
		return inc < 3 ? 'GEO' : 'IGSO';
	}
	if (apo < 50000) {
		// Eccentric near-sync (perigee in the band, apogee out).
		if (Math.abs(peri - GEO_ALT_KM) < 2000) return peri >= GEO_ALT_KM + 200 ? 'GRA' : 'GSO';
		if (peri > GEO_ALT_KM + 2000) return 'HIGH';
		if (peri < 2000 && apo >= 35000 && apo <= 45000 && inc != null && inc >= 62 && inc <= 64)
			return 'MOL';
		if (
			peri >= 20000 &&
			peri < GEO_ALT_KM - 2000 &&
			apo >= 35000 &&
			inc != null &&
			Math.abs(inc - 63.4) <= 5
		)
			return 'TUN';
		if (peri < 2000 && apo >= 30000 && apo <= 40000) return 'GTO';
		return eccentricity(peri, apo) >= 0.5 ? 'HEO' : 'MEO';
	}
	if (apo < 500000) return peri > GEO_ALT_KM + 2000 ? 'HIGH' : 'CIS';
	return 'VHEO';
}

/** GCAT's MEO/HEO boundary sits at eccentricity 0.5. */
function eccentricity(peri: number, apo: number): number {
	const rPeri = peri + R_EARTH_KM;
	const rApo = apo + R_EARTH_KM;
	return (rApo - rPeri) / (rApo + rPeri);
}

function inclinationBand(inc: number): string | null {
	if (inc >= 95 && inc <= 104) return 'SSO';
	if (inc >= 85 && inc <= 95) return 'POL';
	// GCAT: retrograde band starts where sun-sync ends.
	if (inc > 104) return 'RET';
	if (inc < 25) return 'EQU';
	return null;
}

/** Ecc-0.5 MEO/HEO boundary: r_apo = 3·r_peri ⇒ apo = 3·peri + 2·R⊕. */
function heoFloor(peri: number): ZonePoint {
	return { x: peri, y: 3 * peri + 2 * R_EARTH_KM };
}

/** Sampled perigees approximating the ecc-0.5 curve on the log-log chart. */
const HEO_FLOOR_PERIS = [100, 500, 1000, 2000, 4000, 8000];

/** Perigee where the ecc-0.5 floor meets the HEO apogee ceiling (50000 km). */
const HEO_PERI_MAX = (50000 - 2 * R_EARTH_KM) / 3;

/**
 * Earth-sat orbit zones on the perigee × apogee plane (km, log-log).
 * Inc-only overlays (SSO/POL/RET/EQU/TUN/GEO) carry empty polygons
 * and rely on per-sample `classes` highlighting.
 */
export const SAT_ORBIT_ZONES: Record<string, OrbitZone> = {
	VLEO: {
		className: 'VLEO',
		plotType: 'peri-apo',
		polygon: [
			{ x: 100, y: 100 },
			{ x: 600, y: 600 },
			{ x: 100, y: 600 }
		],
		tooltipDefinition: () => m.zone_def_VLEO()
	},
	LEO: {
		className: 'LEO',
		plotType: 'peri-apo',
		polygon: [
			{ x: 600, y: 600 },
			{ x: 2000, y: 2000 },
			{ x: 100, y: 2000 },
			{ x: 100, y: 600 }
		],
		tooltipDefinition: () => m.zone_def_LEO()
	},
	// Low-eccentricity (< 0.5) catch-all between LEO and the sync band; the
	// top-left edge follows the ecc-0.5 curve shared with HEO.
	MEO: {
		className: 'MEO',
		plotType: 'peri-apo',
		polygon: [
			{ x: 100, y: 2000 },
			{ x: 2000, y: 2000 },
			{ x: GEO_ALT_KM - 2000, y: GEO_ALT_KM - 2000 },
			{ x: GEO_ALT_KM - 2000, y: 50000 },
			{ x: HEO_PERI_MAX, y: 50000 },
			...HEO_FLOOR_PERIS.map(heoFloor).reverse()
		],
		tooltipDefinition: () => m.zone_def_MEO()
	},
	// Above the ecc-0.5 curve, below the 50000 km apogee ceiling.
	HEO: {
		className: 'HEO',
		plotType: 'peri-apo',
		polygon: [
			...HEO_FLOOR_PERIS.map(heoFloor),
			{ x: HEO_PERI_MAX, y: 50000 },
			{ x: 100, y: 50000 }
		],
		tooltipDefinition: () => m.zone_def_HEO()
	},
	// Sync band square plus the perigee-in-band strip (apogee out, below the
	// graveyard floor).
	GSO: {
		className: 'GSO',
		plotType: 'peri-apo',
		polygon: [
			{ x: GEO_ALT_KM - 2000, y: GEO_ALT_KM - 2000 },
			{ x: GEO_ALT_KM + 2000, y: GEO_ALT_KM + 2000 },
			{ x: GEO_ALT_KM + 200, y: GEO_ALT_KM + 2000 },
			{ x: GEO_ALT_KM + 200, y: 50000 },
			{ x: GEO_ALT_KM - 2000, y: 50000 }
		],
		tooltipDefinition: () => m.zone_def_GSO()
	},
	// Listed after GSO so the smaller zone stays hover/clickable on top.
	GRA: {
		className: 'GRA',
		plotType: 'peri-apo',
		polygon: [
			{ x: GEO_ALT_KM + 200, y: GEO_ALT_KM + 200 },
			{ x: GEO_ALT_KM + 2000, y: GEO_ALT_KM + 2000 },
			{ x: GEO_ALT_KM + 2000, y: 50000 },
			{ x: GEO_ALT_KM + 200, y: 50000 }
		],
		tooltipDefinition: () => m.zone_def_GRA()
	},
	// Perigee entirely above the sync band, apogee below the cislunar cut.
	HIGH: {
		className: 'HIGH',
		plotType: 'peri-apo',
		polygon: [
			{ x: GEO_ALT_KM + 2000, y: GEO_ALT_KM + 2000 },
			{ x: 500000, y: 500000 },
			{ x: GEO_ALT_KM + 2000, y: 500000 }
		],
		tooltipDefinition: () => m.zone_def_HIGH()
	},
	CIS: {
		className: 'CIS',
		plotType: 'peri-apo',
		polygon: [
			{ x: 100, y: 50000 },
			{ x: GEO_ALT_KM + 2000, y: 50000 },
			{ x: GEO_ALT_KM + 2000, y: 500000 },
			{ x: 100, y: 500000 }
		],
		tooltipDefinition: () => m.zone_def_CIS()
	},
	VHEO: {
		className: 'VHEO',
		plotType: 'peri-apo',
		polygon: [
			{ x: 100, y: 500000 },
			{ x: 500000, y: 500000 },
			{ x: 2000000, y: 2000000 },
			{ x: 100, y: 2000000 }
		],
		tooltipDefinition: () => m.zone_def_VHEO()
	},
	GTO: {
		className: 'GTO',
		plotType: 'peri-apo',
		polygon: [
			{ x: 100, y: 30000 },
			{ x: 2000, y: 30000 },
			{ x: 2000, y: 40000 },
			{ x: 100, y: 40000 }
		],
		tooltipDefinition: () => m.zone_def_GTO()
	},
	GEO: {
		className: 'GEO',
		plotType: 'peri-apo',
		polygon: [],
		tooltipDefinition: () => m.zone_def_GEO()
	},
	IGSO: {
		className: 'IGSO',
		plotType: 'peri-apo',
		polygon: [],
		tooltipDefinition: () => m.zone_def_IGSO()
	},
	// Overlaps GTO on 35-40k; listed after it so it stays clickable on top.
	// Membership is inclination-gated (62-64 deg), the polygon is just the
	// peri-apo footprint.
	MOL: {
		className: 'MOL',
		plotType: 'peri-apo',
		polygon: [
			{ x: 100, y: 35000 },
			{ x: 2000, y: 35000 },
			{ x: 2000, y: 45000 },
			{ x: 100, y: 45000 }
		],
		tooltipDefinition: () => m.zone_def_MOL()
	},
	TUN: {
		className: 'TUN',
		plotType: 'peri-apo',
		polygon: [],
		tooltipDefinition: () => m.zone_def_TUN()
	},
	SSO: {
		className: 'SSO',
		plotType: 'peri-apo',
		polygon: [],
		tooltipDefinition: () => m.zone_def_SSO()
	},
	POL: {
		className: 'POL',
		plotType: 'peri-apo',
		polygon: [],
		tooltipDefinition: () => m.zone_def_POL()
	},
	RET: {
		className: 'RET',
		plotType: 'peri-apo',
		polygon: [],
		tooltipDefinition: () => m.zone_def_RET()
	},
	EQU: {
		className: 'EQU',
		plotType: 'peri-apo',
		polygon: [],
		tooltipDefinition: () => m.zone_def_EQU()
	}
};

/** Planet semi-major axes (AU) used as a-axis reference lines on a-q plots. */
export const PLANET_A_REFS: { name: string; a: number }[] = [
	{ name: 'Mercury', a: 0.387 },
	{ name: 'Venus', a: 0.723 },
	{ name: 'Earth', a: 1.0 },
	{ name: 'Mars', a: 1.524 },
	{ name: 'Jupiter', a: 5.204 },
	{ name: 'Saturn', a: 9.583 },
	{ name: 'Neptune', a: 30.07 }
];

/** Slug ↔ classname helpers. Slug shape: `class-MBA`, `flag-neo`. */
export const CLASS_SLUG_PREFIX = 'class-';
export const FLAG_SLUG_PREFIX = 'flag-';

export function classNameFromSlug(slug: string): string | null {
	if (!slug.startsWith(CLASS_SLUG_PREFIX)) return null;
	return slug.slice(CLASS_SLUG_PREFIX.length);
}

/** NEO is a meta-zone (Atira ∪ Aten ∪ Apollo ∪ Amor); PHA is a styling overlay only. */
export const NEO_CLASSES = ['IEO', 'ATE', 'APO', 'AMO'] as const;

/** The two switchable comet plots. */
export const COMET_PLOT_TYPES: PlotType[] = ['a-T', 'q-e'];

/** Slugs whose samples are drawn on the comet plots (a-T and q-e). */
export const COMET_PLOT_CLASSES = new Set(
	['ETc', 'JFc', 'JFC', 'CTc', 'HTC', 'COM', 'PAR', 'HYP', 'PAA', 'HYA'].map(
		(c) => `${CLASS_SLUG_PREFIX}${c}`
	)
);

/** Resolve `orbit_class_<NAME>` to its localized label; unknown → raw id. */
export function orbitClassLabel(className: string): string {
	const fn = (m as Record<string, unknown>)[`orbit_class_${className}`];
	return typeof fn === 'function' ? (fn as () => string)() : className;
}

/** Localized class name with the redundant "orbit" word dropped (e.g.
 *  "Geostationary" not "Geostationary Orbit"); full label when no short key. */
export function orbitClassShortLabel(className: string): string {
	const fn = (m as Record<string, unknown>)[`orbit_class_short_${className}`];
	return typeof fn === 'function' ? (fn as () => string)() : orbitClassLabel(className);
}

/** Default scatter plot for an orbit-grouping category page. */
export function categoryPlotType(slug: string): PlotType | null {
	if (slug === CAT_ASTEROIDS) return 'a-q';
	if (slug === CAT_COMETS) return 'a-T';
	if (slug === CAT_SATELLITES) return 'peri-apo';
	return null;
}

/** `class-<NAME>` slugs with a clickable zone polygon on `plotType`'s scatter. */
export function scatterClickableSlugs(plotType: PlotType): Set<string> {
	const out = new Set<string>();
	for (const z of zonesOnPlot(plotType)) {
		if (z.polygon.length > 0) out.add(`${CLASS_SLUG_PREFIX}${z.className}`);
	}
	return out;
}

/** Zone slugs with no clickable polygon — inc-only sat classes, folded into the
 *  orbit map as chips. Asteroid/comet plots have none. */
export function scatterIncOnlySlugs(plotType: PlotType): string[] {
	const out: string[] = [];
	for (const z of zonesOnPlot(plotType)) {
		if (z.polygon.length === 0) out.push(`${CLASS_SLUG_PREFIX}${z.className}`);
	}
	return out;
}

/** Every zone slug on `plotType`'s orbit map — clickable plus inc-only chips. */
export function scatterZoneSlugs(plotType: PlotType): Set<string> {
	const out = scatterClickableSlugs(plotType);
	for (const slug of scatterIncOnlySlugs(plotType)) out.add(slug);
	return out;
}

/** Zones drawn on `plotType` (comet plots span both a-T and q-e). */
function zonesOnPlot(plotType: PlotType): OrbitZone[] {
	if (plotType === 'peri-apo') return Object.values(SAT_ORBIT_ZONES);
	const plots = COMET_PLOT_TYPES.includes(plotType) ? COMET_PLOT_TYPES : [plotType];
	return Object.values(ORBIT_ZONES).filter((z) => plots.includes(z.plotType));
}

/** Pick the chart's plot type for a group slug; null hides the chart. */
export function plotTypeForSlug(slug: string): PlotType | null {
	if (slug === `${FLAG_SLUG_PREFIX}neo` || slug === `${FLAG_SLUG_PREFIX}pha`) return 'a-q';
	const cls = classNameFromSlug(slug);
	if (cls == null) return null;
	return ORBIT_ZONES[cls]?.plotType ?? SAT_ORBIT_ZONES[cls]?.plotType ?? null;
}
