import type { NotableMemberEntry } from '$lib/fetch/groups/details';
import { BODY_COLORS } from '$lib/constants';
import type { LineupBody } from './BodyLineup.svelte';

/** The body-class-specific part of a LineupBody: geometry plus optional flat
 *  colour / render hints. The routing id, localized name and hover description
 *  are filled in by `buildLineup`. */
export type LineupGeometry = Omit<LineupBody, 'id' | 'name' | 'description'>;

/** Per-body render hints that aren't physical data, so they don't ride the
 *  export: the monthly surface frame and which system bundle carries clouds. */
const RENDER_HINTS: Record<string, Pick<LineupGeometry, 'surfaceFrame' | 'cloudSystem'>> = {
	'naif-299': { cloudSystem: 'naif-2' }, // Venus
	'naif-399': { surfaceFrame: '06', cloudSystem: 'naif-3' } // Earth
};

/** A member's full lineup geometry: size + oblateness from PCK `radii`, else
 *  SBDB diameter, else Wikidata radius; tilt from the IAU `pole`; render hints;
 *  tint (`undefined` for curated BODY_COLORS bodies, which defer to texture).
 *  `null` when sizeless, which doubles as the renderable filter. */
export function geometryFromMember(m: NotableMemberEntry & { id: string }): LineupGeometry | null {
	// A surface feature isn't a body — its `id` is the host it sits on, so it
	// would draw (and key) as a duplicate of that host's sphere.
	if (m.feature_id != null) return null;
	const geom: LineupGeometry = { radiusKm: 0 };
	if (m.radii) {
		const eq = Math.max(m.radii.a, m.radii.b, m.radii.c);
		geom.radiusKm = eq;
		geom.polarRatio = m.radii.c / eq;
	} else if (m.diameter_km != null) {
		geom.radiusKm = m.diameter_km / 2;
	} else if (m.radius_km != null) {
		geom.radiusKm = m.radius_km;
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
	geom.texture = m.texture;
	return { ...geom, ...RENDER_HINTS[m.id], color: BODY_COLORS[m.id] ? undefined : m.color };
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
