/**
 * Orbit-class zone polygons for the small-body scatter plot.
 *
 * Asteroids plot on (a, q) — semi-major axis vs perihelion. Comets plot on
 * (e, q) because hyperbolic/parabolic comets have undefined or negative a.
 * Polygons approximate SBDB membership rules; tooltip carries the precise
 * definition (esp. for resonance- or Tisserand-based classes where the
 * a-q/q-e projection is a simplification).
 */

import * as m from '$lib/paraglide/messages.js';

export type PlotType = 'a-q' | 'q-e' | 'peri-apo';

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
	'q-e': '#88d4a8'
};

const AJ = 5.2038; // Jupiter semi-major axis [AU], standard Tisserand reference

/**
 * Tisserand parameter (i=0 projection).
 * T_J = a_J/a + 2*sqrt((a/a_J)(1-e²))
 */
function tisserand(a: number, e: number): number {
	if (a <= 0) return Infinity;
	return AJ / a + 2 * Math.sqrt((a / AJ) * (1 - e * e));
}

/**
 * Solve T_J(a, e) = target for e given a. Bisection on e ∈ [0, 1].
 * Returns null if no crossing in the bracket.
 */
function tisserandSolveEAt(a: number, target: number): number | null {
	const f = (e: number) => tisserand(a, e) - target;
	let lo = 0;
	let hi = 0.999;
	const fLo = f(lo);
	const fHi = f(hi);
	if (fLo * fHi > 0) return null;
	for (let i = 0; i < 50; i++) {
		const mid = (lo + hi) / 2;
		const fMid = f(mid);
		if (fMid === 0) return mid;
		if (fLo * fMid < 0) hi = mid;
		else lo = mid;
	}
	return (lo + hi) / 2;
}

/**
 * Sample the T_J = target curve as (e, q) polyline over the given a range.
 * Returns points in increasing-a order (which is decreasing-e order for the
 * usual comet brackets).
 */
function tisserandCurve(target: number, aMin: number, aMax: number, steps = 40): ZonePoint[] {
	const out: ZonePoint[] = [];
	for (let i = 0; i <= steps; i++) {
		const a = aMin + (aMax - aMin) * (i / steps);
		const e = tisserandSolveEAt(a, target);
		if (e == null) continue;
		const q = a * (1 - e);
		out.push({ x: e, y: q });
	}
	return out;
}

/** Band between T_J=lower (outer) and T_J=upper (inner) over an a range. */
function tisserandBand(lower: number, upper: number, aMin: number, aMax: number): ZonePoint[] {
	const top = tisserandCurve(upper, aMin, aMax);
	const bot = tisserandCurve(lower, aMin, aMax).reverse();
	return [...top, ...bot];
}

/** Region with T_J ≥ target, closed against the e=0 and q=0 axes (Encke side). */
function highTisserandArea(target: number, aMin: number, aMax: number): ZonePoint[] {
	const curve = tisserandCurve(target, aMin, aMax);
	if (curve.length === 0) return [];
	return [
		{ x: 0, y: 0 },
		{ x: curve[0].x, y: 0 },
		...curve,
		{ x: 0, y: curve[curve.length - 1].y }
	];
}

/** Region with T_J ≤ target, closed against e=eMax (Halley side). */
function lowTisserandArea(target: number, aMin: number, aMax: number, eMax: number): ZonePoint[] {
	const curve = tisserandCurve(target, aMin, aMax);
	if (curve.length === 0) return [];
	return [...curve, { x: eMax, y: curve[curve.length - 1].y }, { x: eMax, y: curve[0].y }];
}

/**
 * Map of every plottable orbit class. The shared `__orbit_samples__.json`
 * exporter (`build_orbit_class_samples`) emits one zone per OrbitClass enum
 * member that has rows; missing keys here mean "no clickable polygon"
 * (samples are still drawn as background dots when another zone is focused).
 */
export const ORBIT_ZONES: Record<string, OrbitZone> = {
	// AST/COM are catch-all "unclassified" zones that fill the chart
	// background. Listed first so the specific classes render on top; only
	// the leftover gaps show as AST/COM. The asteroid q > a half-plane is
	// physically empty and intentionally not covered.
	AST: {
		className: 'AST',
		plotType: 'a-q',
		polygon: [
			{ x: 0, y: 0 },
			{ x: 100, y: 0 },
			{ x: 100, y: 100 }
		],
		tooltipDefinition: () => m.zone_def_AST()
	},
	COM: {
		className: 'COM',
		plotType: 'q-e',
		polygon: [
			{ x: 0, y: 0 },
			{ x: 3, y: 0 },
			{ x: 3, y: 20 },
			{ x: 0, y: 20 }
		],
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
		polygon: [
			{ x: 3.2, y: 1.666 },
			{ x: 4.6, y: 1.666 },
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
	// --- Comets (q-e plot) ---
	JFc: {
		className: 'JFc',
		plotType: 'q-e',
		polygon: tisserandBand(2, 3, 0.5, AJ),
		tooltipDefinition: () => m.zone_def_JFc()
	},
	JFC: {
		className: 'JFC',
		plotType: 'q-e',
		// Period-based; treat as nested inside JFc with tighter q (P < 20y → a < 7.4)
		polygon: tisserandBand(2, 3, 0.5, 4.0),
		tooltipDefinition: () => m.zone_def_JFC()
	},
	HTC: {
		className: 'HTC',
		plotType: 'q-e',
		// T_J < 2 (Halley side of the JFc band), out to a ≈ 30 (200y).
		polygon: lowTisserandArea(2, 3, 30, 0.999),
		tooltipDefinition: () => m.zone_def_HTC()
	},
	ETc: {
		className: 'ETc',
		plotType: 'q-e',
		// T_J > 3 (Encke side of the JFc band), a < a_J.
		polygon: highTisserandArea(3, 1.5, AJ),
		tooltipDefinition: () => m.zone_def_ETc()
	},
	CTc: {
		className: 'CTc',
		plotType: 'q-e',
		// T_J > 3, a > a_J: Centaur-like comets with q > 5
		polygon: [
			{ x: 0.0, y: 5.5 },
			{ x: 0.7, y: 5.5 },
			{ x: 0.7, y: 20 },
			{ x: 0.0, y: 20 }
		],
		tooltipDefinition: () => m.zone_def_CTc()
	},
	PAR: {
		className: 'PAR',
		plotType: 'q-e',
		// e ≈ 1 — render as a thin band at e = 1
		polygon: [
			{ x: 0.99, y: 0.1 },
			{ x: 1.01, y: 0.1 },
			{ x: 1.01, y: 20 },
			{ x: 0.99, y: 20 }
		],
		tooltipDefinition: () => m.zone_def_PAR()
	},
	HYP: {
		className: 'HYP',
		plotType: 'q-e',
		polygon: [
			{ x: 1.0, y: 0.1 },
			{ x: 3.0, y: 0.1 },
			{ x: 3.0, y: 20 },
			{ x: 1.0, y: 20 }
		],
		tooltipDefinition: () => m.zone_def_HYP()
	},
	HYA: {
		// Hyperbolic asteroid — share the HYP region on the q-e plot.
		className: 'HYA',
		plotType: 'q-e',
		polygon: [
			{ x: 1.0, y: 0.1 },
			{ x: 3.0, y: 0.1 },
			{ x: 3.0, y: 20 },
			{ x: 1.0, y: 20 }
		],
		tooltipDefinition: () => m.zone_def_HYA()
	}
};

/** Geostationary altitude (km above Earth surface). */
export const GEO_ALT_KM = 35786;

/**
 * Earth-orbit zones for a sat given perigee/apogee/inclination.
 * Mirror of `classify_earth_orbit` in the data tier — kept in sync by hand.
 */
export function classifyEarthOrbit(
	perigeeKm: number | null | undefined,
	apogeeKm: number | null | undefined,
	inclinationDeg: number | null | undefined
): string[] {
	if (perigeeKm == null || apogeeKm == null) return [];
	const peri = perigeeKm;
	const apo = apogeeKm;
	const classes: string[] = [];

	if (apo < 2000) classes.push('LEO');
	else if (apo < 35000) classes.push(peri >= 2000 ? 'MEO' : 'HEO');
	else if (apo < 50000) classes.push(Math.abs(peri - GEO_ALT_KM) < 2000 ? 'GSO' : 'HEO');
	else if (apo < 500000) classes.push('CIS');
	else classes.push('VHEO');

	if (peri < 2000 && apo >= 30000 && apo <= 40000) classes.push('GTO');

	if (inclinationDeg == null) return classes;
	const inc = inclinationDeg;

	if (Math.abs(peri - GEO_ALT_KM) < 2000 && Math.abs(apo - GEO_ALT_KM) < 2000 && inc < 1)
		classes.push('GEO');
	if (peri < 2000 && apo >= 35000 && apo <= 45000 && Math.abs(inc - 63.4) <= 3) classes.push('MOL');
	if (peri >= 20000 && peri <= 50000 && apo >= 35000 && apo <= 50000 && Math.abs(inc - 63.4) <= 5)
		classes.push('TUN');

	const isSso = inc >= 96 && inc <= 100 && apo < 2000;
	if (isSso) classes.push('SSO');
	if (inc >= 80 && inc <= 100) classes.push('POL');
	if (inc > 90 && !isSso) classes.push('RET');
	if (inc < 10) classes.push('EQU');

	return classes;
}

/**
 * Earth-sat orbit zones on the perigee × apogee plane (km, log-log).
 * Inc-only overlays (SSO/POL/RET/EQU/MOL/TUN/GEO) carry empty polygons
 * and rely on per-sample `classes` highlighting.
 */
export const SAT_ORBIT_ZONES: Record<string, OrbitZone> = {
	LEO: {
		className: 'LEO',
		plotType: 'peri-apo',
		polygon: [
			{ x: 100, y: 100 },
			{ x: 2000, y: 2000 },
			{ x: 100, y: 2000 }
		],
		tooltipDefinition: () => m.zone_def_LEO()
	},
	MEO: {
		className: 'MEO',
		plotType: 'peri-apo',
		polygon: [
			{ x: 2000, y: 2000 },
			{ x: 35000, y: 35000 },
			{ x: 2000, y: 35000 }
		],
		tooltipDefinition: () => m.zone_def_MEO()
	},
	HEO: {
		className: 'HEO',
		plotType: 'peri-apo',
		polygon: [
			{ x: 100, y: 2000 },
			{ x: 2000, y: 2000 },
			{ x: 2000, y: 50000 },
			{ x: 100, y: 50000 }
		],
		tooltipDefinition: () => m.zone_def_HEO()
	},
	GSO: {
		className: 'GSO',
		plotType: 'peri-apo',
		polygon: [
			{ x: GEO_ALT_KM - 2000, y: GEO_ALT_KM - 2000 },
			{ x: GEO_ALT_KM + 2000, y: GEO_ALT_KM + 2000 },
			{ x: GEO_ALT_KM - 2000, y: GEO_ALT_KM + 2000 }
		],
		tooltipDefinition: () => m.zone_def_GSO()
	},
	CIS: {
		className: 'CIS',
		plotType: 'peri-apo',
		// Bottom edge tracks the peri=apo diagonal up to apo=50k.
		polygon: [
			{ x: 100, y: 50000 },
			{ x: 50000, y: 50000 },
			{ x: 500000, y: 500000 },
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
	MOL: {
		className: 'MOL',
		plotType: 'peri-apo',
		polygon: [],
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

/** Resolve `orbit_class_<NAME>` to its localized label; unknown → raw id. */
export function orbitClassLabel(className: string): string {
	const fn = (m as Record<string, unknown>)[`orbit_class_${className}`];
	return typeof fn === 'function' ? (fn as () => string)() : className;
}

/** Pick the chart's plot type for a group slug; null hides the chart. */
export function plotTypeForSlug(slug: string): PlotType | null {
	if (slug === `${FLAG_SLUG_PREFIX}neo` || slug === `${FLAG_SLUG_PREFIX}pha`) return 'a-q';
	const cls = classNameFromSlug(slug);
	if (cls == null) return null;
	return ORBIT_ZONES[cls]?.plotType ?? SAT_ORBIT_ZONES[cls]?.plotType ?? null;
}
