/**
 * A star's place, magnitude and colour from its Point source row, by the
 * rules the render tree is built with (`docs/export-format/extrasolar.md`,
 * "Milky Way render tree"). So the star a page focuses is the one the tree
 * draws, at the record's full precision. `orbit` is the star's astrometric
 * table-2 row, which gives the distance where it has one.
 */

import { starDistance, type TableRow } from '$lib/fetch/extrasolar/lookup';
import { icrsToTree, treeToScene, type Vec3 } from './tree';

/** Epoch of the render tree's positions (Julian year). */
export const RENDER_EPOCH = 2016.0;
/** Magnitudes in the tree are multiples of this. */
const MAG_STEP = 1 / 1024;
const SOLAR_RADIUS_KM = 695_700;

export function positiveNumber(row: TableRow, name: string): number | null {
	const value = row.number(name);
	return value !== null && Number.isFinite(value) && value > 0 ? value : null;
}

/** In nominal solar radii. FLAME's radius comes first: for most stars it
 *  rests on the parallax, where GSP-Phot's always rests on its own
 *  photometric distance. */
export function starRadiusSolar(row: TableRow): number | null {
	return positiveNumber(row, 'radius_flame') ?? positiveNumber(row, 'radius_gspphot');
}

export function starRadiusKm(row: TableRow): number | null {
	const radius = starRadiusSolar(row);
	return radius === null ? null : radius * SOLAR_RADIUS_KM;
}

/** G − V from B − V, ascending powers (Gaia DR2 documentation §5.3.7). */
const G_MINUS_V = [-0.02907, -0.02385, -0.2297, -0.001768];
const B_V_RANGE: [number, number] = [-0.3, 2.4];
const G_MINUS_HP = -0.28;
/** BP − RP from V − I, ascending powers (Riello et al. 2021, Table C.2). */
const BP_RP_FROM_V_I = [-0.01612, 1.274, -0.08143];
const V_I_RANGE: [number, number] = [-0.5, 3.5];

const MAS_PER_RAD = (180 / Math.PI) * 3.6e6;

export interface StarPlace {
	/** ICRS at the render epoch, degrees. */
	ra: number;
	dec: number;
	distancePc: number;
	/** In the tree's frame, pc. */
	tree: Vec3;
	/** In the scene, barycentre origin, scene units. */
	scene: Vec3;
}

function clamp(x: number, [lo, hi]: [number, number]): number {
	return Math.min(Math.max(x, lo), hi);
}

function poly(x: number, coefficients: readonly number[]): number {
	let out = 0;
	for (let i = coefficients.length - 1; i >= 0; i--) out = out * x + coefficients[i];
	return out;
}

/**
 * A position moved by its proper motion over `years`, in a straight line at
 * constant speed with no radial velocity. `pmra` is on ra·cos dec, mas/yr.
 */
export function propagate(
	raDeg: number,
	decDeg: number,
	pmra: number,
	pmdec: number,
	years: number
): [number, number] {
	const ra = (raDeg * Math.PI) / 180;
	const dec = (decDeg * Math.PI) / 180;
	const rate = years / MAS_PER_RAD;
	const [cr, sr, cd, sd] = [Math.cos(ra), Math.sin(ra), Math.cos(dec), Math.sin(dec)];
	const x = cd * cr + rate * (pmra * -sr + pmdec * -sd * cr);
	const y = cd * sr + rate * (pmra * cr + pmdec * -sd * sr);
	const z = sd + rate * (pmdec * cd);
	const n = Math.hypot(x, y, z);
	const raOut = ((((Math.atan2(y / n, x / n) * 180) / Math.PI) % 360) + 360) % 360;
	const decOut = (Math.asin(Math.min(Math.max(z / n, -1), 1)) * 180) / Math.PI;
	return [raOut, decOut];
}

/** Where the star is drawn; null when it has no distance. */
export function starPlace(row: TableRow, orbit: TableRow | null): StarPlace | null {
	const distancePc = starDistance(row, orbit)?.pc ?? null;
	let ra = row.number('ra');
	let dec = row.number('dec');
	if (distancePc === null || ra === null || dec === null) return null;
	const years = RENDER_EPOCH - (row.number('epoch') ?? RENDER_EPOCH);
	const pmra = row.number('pmra');
	if (years !== 0 && pmra !== null) {
		[ra, dec] = propagate(ra, dec, pmra, row.number('pmdec') ?? 0, years);
	}
	const tree = icrsToTree(ra, dec, distancePc);
	const s = treeToScene(tree[0], tree[1], tree[2], { x: 0, y: 0, z: 0 });
	return { ra, dec, distancePc, tree, scene: [s.x, s.y, s.z] };
}

/** Gaia G from Johnson V and B − V, else from Hp; null where neither. */
export function gEstimate(v: number | null, bv: number | null, hp: number | null): number | null {
	if (v !== null && bv !== null) return v + poly(clamp(bv, B_V_RANGE), G_MINUS_V);
	return hp === null ? null : hp + G_MINUS_HP;
}

/** Apparent G: Gaia's, then SIMBAD's, then the estimate from Hipparcos, then
 *  the estimate from SIMBAD's V and B − V, then a planet host's G or V from
 *  its exoplanet catalogue. */
export function apparentG(row: TableRow): number | null {
	const simbadV = row.number('simbad_v_mag');
	const simbadB = row.number('simbad_b_mag');
	return (
		row.number('phot_g_mean_mag') ??
		row.number('simbad_g_mag') ??
		gEstimate(row.number('v_mag'), row.number('b_v'), row.number('hp_mag')) ??
		gEstimate(simbadV, simbadV !== null && simbadB !== null ? simbadB - simbadV : null, null) ??
		row.number('host_g_mag') ??
		row.number('host_v_mag')
	);
}

/** Absolute G at the star's distance, with no extinction, as the tree rounds it. */
export function absoluteG(row: TableRow, orbit: TableRow | null): number | null {
	const g = apparentG(row);
	const distance = starDistance(row, orbit);
	if (g === null || distance === null) return null;
	return Math.round((g - 5 * Math.log10(distance.pc) + 5) / MAG_STEP) * MAG_STEP;
}

/** Absolute G of a planet host with no magnitude: faint, so the host draws
 *  only near its system. */
const HOST_PLACEHOLDER_ABS_MAG = 15;

/** Absolute G as the tree draws the star: a placed planet host with no
 *  magnitude takes HOST_PLACEHOLDER_ABS_MAG. */
export function drawnAbsoluteG(row: TableRow, orbit: TableRow | null): number | null {
	const absolute = absoluteG(row, orbit);
	if (absolute !== null || row.text('host_star_source') === null) return absolute;
	return starDistance(row, orbit) === null ? null : HOST_PLACEHOLDER_ABS_MAG;
}

/** Gaia BP − RP, else from the Hipparcos V − I; null where neither. */
export function colourBpRp(row: TableRow): number | null {
	const bp = row.number('phot_bp_mean_mag');
	const rp = row.number('phot_rp_mean_mag');
	if (bp !== null && rp !== null) return bp - rp;
	const vi = row.number('v_i');
	return vi === null ? null : poly(clamp(vi, V_I_RANGE), BP_RP_FROM_V_I);
}
