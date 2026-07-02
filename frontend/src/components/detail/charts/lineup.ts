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

/** A member's full lineup geometry from its exported fields: size + oblateness
 *  from PCK `radii`, else SBDB diameter, else Wikidata radius; tilt from the IAU
 *  `pole`; render hints; and the measured tint (`undefined` for curated
 *  BODY_COLORS bodies, which defer to their texture). `null` when sizeless — it
 *  can't be drawn, which doubles as the renderable filter. */
export function geometryFromMember(m: NotableMemberEntry & { id: string }): LineupGeometry | null {
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
	return { ...geom, ...RENDER_HINTS[m.id], color: BODY_COLORS[m.id] ? undefined : m.color };
}

/** Members renderable in a lineup: have an id and a resolvable size. Colour
 *  always resolves, so size is the binding requirement; callers gate on this. */
export function renderableCount(members: NotableMemberEntry[] | undefined): number {
	if (!members) return 0;
	return members.filter((m) => m.id && geometryFromMember(m as NotableMemberEntry & { id: string }))
		.length;
}

export interface LineupLocalization {
	/** member id → localized name, overriding the entry's English label. */
	names?: Record<string, string>;
	/** member id → localized Wikidata short description, for the hover tooltip. */
	descriptions?: Record<string, string>;
}

/** Assemble a lineup's `LineupBody[]` from notable members. `resolve` supplies
 *  each body's geometry (or `null` to drop it — the member filter); localized
 *  name/description overrides are applied by id. Shared by every `*Lineup`
 *  wrapper so they reduce to just their geometry source. */
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
