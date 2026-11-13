import { SUN_ID, SUN_TEFF } from '$lib/constants';
import { isExtrasolarObjectId, isStarObjectId, planetOfObjectId } from '$lib/fetch/extrasolar/ids';
import type { NotableMemberEntry } from '$lib/fetch/groups/details';
import { lunarWeightScaleOf } from '$lib/scene/exoplanets/photometry';
import { teffFromBpRp } from '$lib/scene/starfield/colour';
import type { LineupBody } from './BodyLineup.svelte';

/** The body-class-specific part of a LineupBody: geometry plus optional flat
 *  colour / render hints. The routing id, localized name and hover description
 *  are filled in by `buildLineup`. */
export type LineupGeometry = Omit<LineupBody, 'id' | 'name' | 'description'>;

/** Per-body render hints that aren't physical data, so they don't ride the
 *  export: the monthly surface frame and which system bundle carries clouds. */
export const RENDER_HINTS: Record<string, Pick<LineupGeometry, 'surfaceFrame' | 'cloudSystem'>> = {
	'naif-299': { cloudSystem: 'naif-2' }, // Venus
	'naif-399': { surfaceFrame: '06', cloudSystem: 'naif-3' } // Earth
};

/** The lineup geometry of a member. The size and flattening come from
 *  `radii`, else the SBDB diameter, else an exoplanet's estimated diameter,
 *  as the scene draws it. The tilt comes
 *  from the IAU `pole`. It also carries the render hints, the measured colour
 *  and albedo, and the law of the ground. `null` for a member with no size or
 *  for a star of another system, so it also filters what the row can draw. A
 *  planet of another star must pass the rule of `drawnPlanetIds` first. */
export function geometryFromMember(m: NotableMemberEntry & { id: string }): LineupGeometry | null {
	// A surface feature isn't a body — its `id` is the host it sits on, so it
	// would draw (and key) as a duplicate of that host's sphere.
	if (m.feature_id != null) return null;
	// A row of stars draws a star of another system (`starGeometryFromMember`).
	if (isStarObjectId(m.id)) return null;
	const geom: LineupGeometry = { radiusKm: 0 };
	if (m.radii) {
		const eq = Math.max(m.radii.a, m.radii.b, m.radii.c);
		geom.radiusKm = eq;
		geom.polarRatio = m.radii.c / eq;
		if (m.radii.nominal) geom.sizeEstimated = true;
	} else if (m.diameter_km != null) {
		geom.radiusKm = m.diameter_km / 2;
	} else if (m.estimated_diameter_km != null) {
		geom.radiusKm = m.estimated_diameter_km / 2;
		geom.sizeEstimated = true;
	} else {
		return null;
	}
	if (m.pole) {
		geom.poleRa = m.pole.ra;
		geom.poleDec = m.pole.dec;
	}
	if (m.displacement) geom.displacement = m.displacement;
	if (m.model) geom.model = m.model;
	// Explicit false only — absent means a pre-flag export, which still probes.
	// A planet of another star that passed the rule has a map.
	geom.texture = planetOfObjectId(m.id) ? true : m.texture;
	if (m.id === SUN_ID) geom.photosphere = { teff: SUN_TEFF };
	return {
		...geom,
		...RENDER_HINTS[m.id],
		color: m.color,
		geometricAlbedo: m.geometric_albedo,
		lunarWeightScale: lunarWeightScaleOf(m.id, m.lunar_weight_scale)
	};
}

/** A star's lineup geometry: the Sun as any other row draws it, a catalogue
 *  star from the size and colour the export gives it. `null` with neither. */
export function starGeometryFromMember(
	m: NotableMemberEntry & { id: string }
): LineupGeometry | null {
	if (!isExtrasolarObjectId(m.id)) return m.id === SUN_ID ? geometryFromMember(m) : null;
	const teff = m.teff ?? (m.bp_rp != null ? teffFromBpRp(m.bp_rp) : null);
	if (!m.radii || teff === null) return null;
	return { radiusKm: m.radii.a, texture: false, photosphere: { teff } };
}

/** A spacecraft member's lineup geometry. The mesh *is* the craft — there is no
 *  sphere to fall back to — so its size comes from the bundle, halved into km so
 *  one scale serves bodies and craft alike (the convention the main scene sizes
 *  a craft by). The craft is placed on its body and drawn on its full span, so
 *  a boom overhangs its slot rather than shrinking the craft to fit. `null` when
 *  either is missing. */
export function craftGeometryFromMember(
	m: NotableMemberEntry & { id: string }
): LineupGeometry | null {
	if (!m.model || m.length_m == null) return null;
	const body = m.body_length_m ?? m.length_m;
	return {
		radiusKm: body / 2000,
		meshSpanRatio: m.length_m / body,
		model: m.model,
		craft: true
	};
}

/** Members renderable in a lineup: have an id and a resolvable size. Colour
 *  always resolves, so size is the binding requirement; callers gate on this. */
export function renderableCount(
	members: NotableMemberEntry[] | undefined,
	resolve: (m: NotableMemberEntry & { id: string }) => LineupGeometry | null = geometryFromMember
): number {
	if (!members) return 0;
	return members.filter((m) => m.id && resolve(m as NotableMemberEntry & { id: string })).length;
}

export interface LineupLocalization {
	/** member id → localized name, overriding the entry's English label. */
	names?: Record<string, string>;
	/** member id → localized Wikidata short description, for the hover tooltip. */
	descriptions?: Record<string, string>;
}

/** Assemble a lineup's `LineupBody[]` from notable members: `resolve` supplies
 *  each body's geometry (`null` drops it), localized name/description apply by
 *  id. Shared so every `*Lineup` wrapper reduces to just its geometry source. */
export function buildLineup(
	members: NotableMemberEntry[],
	resolve: (m: NotableMemberEntry & { id: string }) => LineupGeometry | null,
	localized?: LineupLocalization
): LineupBody[] {
	const out: LineupBody[] = [];
	for (const m of members) {
		if (!m.id) continue;
		const geom = resolve(m as NotableMemberEntry & { id: string });
		if (!geom) continue;
		out.push({
			id: m.id,
			name: localized?.names?.[m.id] ?? m.name,
			description: localized?.descriptions?.[m.id],
			...geom
		});
	}
	return out;
}
