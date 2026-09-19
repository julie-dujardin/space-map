/**
 * What the comparison row needs to draw one object, whatever it is: a planet,
 * a moon, a small body or a spacecraft.
 *
 * A size arrives in two steps. The search hit carries a diameter, so a body
 * enters the row the moment it is picked; its own bundle then supplies the
 * measured shape, the pole it tilts on, and the mesh and surface map the scene
 * would draw, and the row redraws on that. A spacecraft has no radius at all,
 * so its size comes from the model index instead.
 */

import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { fetchModelIndex, type ModelIndexEntry } from '$lib/fetch/models';
import type { LineupBody } from '../../components/detail/charts/BodyLineup.svelte';
import { RENDER_HINTS } from '../../components/detail/charts/lineup';
import { BODY_COLORS } from '$lib/constants';

/** An object the reader has put in the comparison. */
export interface CompareObject {
	id: string;
	name: string;
	/** Object type string (`planet`, `moon`, `asteroid_main_belt`, …), for the
	 *  line under the name. Absent on an object reached by id alone. */
	type?: string;
	/** Equatorial radius in km, or half a craft's body span. */
	radiusKm: number;
	/** The rest of what the row draws: tilt, mesh, surface map, tint. */
	geometry: Omit<LineupBody, 'id' | 'name' | 'radiusKm'>;
}

/** The row's body for one object. */
export function lineupBody(object: CompareObject): LineupBody {
	return { id: object.id, name: object.name, radiusKm: object.radiusKm, ...object.geometry };
}

/** A craft is its mesh: the manifest span is the only size it has. A craft
 *  reached by id alone has no search hit behind it, so the name comes off the
 *  bundle's own attachment. */
function craftObject(id: string, name: string, entry: ModelIndexEntry): CompareObject | null {
	if (!entry.scale_meters) return null;
	const body = entry.scale_meters * (entry.body_span_ratio ?? 1);
	return {
		id,
		name: name || entry.objects.find((o) => o.id === id)?.name || id,
		type: 'spacecraft',
		radiusKm: body / 2000,
		geometry: { model: entry.slug, craft: true, meshSpanRatio: entry.scale_meters / body }
	};
}

/** The craft bundle attached to an object, if the mesh *is* that object. */
async function craftBundleFor(id: string): Promise<ModelIndexEntry | null> {
	const index = await fetchModelIndex().catch(() => null);
	if (!index) return null;
	return index.find((e) => e.kind !== 'shape_model' && e.objects.some((o) => o.id === id)) ?? null;
}

/**
 * Everything known about one object's size and appearance. `seed` is what the
 * search hit already said, so a picked object can be drawn before its bundle
 * lands; `null` when nothing gives it a size, which is the row's filter.
 */
export async function resolveObject(
	id: string,
	seed: { name: string; type?: string; diameter_km?: number }
): Promise<CompareObject | null> {
	const craft = await craftBundleFor(id);
	if (craft) return craftObject(id, seed.name, craft);

	const detail = await fetchObjectDetail(id, false).catch(() => null);
	const global = detail?.global;
	const name = seed.name || global?.name || id;
	const type = seed.type ?? global?.type;

	// The measured ellipsoid wins, then the SBDB diameter, then whatever the
	// search index resolved. A body with none of the three cannot be drawn.
	let radiusKm = 0;
	let polarRatio: number | undefined;
	if (global?.radii) {
		const { a, b, c } = global.radii;
		radiusKm = Math.max(a, b, c);
		polarRatio = c / radiusKm;
	} else if (global?.sbdb?.diameter) {
		radiusKm = global.sbdb.diameter / 2;
	} else if (seed.diameter_km) {
		radiusKm = seed.diameter_km / 2;
	}
	if (!(radiusKm > 0)) return null;

	const geometry: CompareObject['geometry'] = { polarRatio };
	const pole = global?.orientation;
	if (pole) {
		geometry.poleRa = pole.pole_ra_0;
		geometry.poleDec = pole.pole_dec_0;
	}
	if (global?.model_name) geometry.model = global.model_name;
	if (global?.displacement) geometry.displacement = global.displacement;
	geometry.texture = global?.map_texture_available ?? false;
	// The same surface colour the scene tints an untextured body with: small
	// bodies carry it under `sbdb`, moons top-level. Curated bodies keep their
	// own constant, which the row falls back to on its own.
	geometry.color = BODY_COLORS[id] ? undefined : (global?.sbdb?.color ?? global?.color);

	return { id, name, type, radiusKm, geometry: { ...geometry, ...RENDER_HINTS[id] } };
}
