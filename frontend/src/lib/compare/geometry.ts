/**
 * What the comparison row needs to draw one object, whatever it is: a planet,
 * a moon, a small body or a spacecraft.
 *
 * A size arrives in two steps. The search hit carries a diameter, so a body
 * enters the row the moment it is picked; its own bundle then supplies the
 * measured shape, the pole it tilts on, and the mesh and surface map the scene
 * would draw, and the row redraws on that. A spacecraft has no radius at all,
 * so its size comes from the model index instead; a rocket is nothing but its
 * bundle, and is named by the row itself.
 */

import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { fetchModelIndex, type ModelIndexEntry } from '$lib/fetch/models';
import type { LineupBody } from '../../components/detail/charts/BodyLineup.svelte';
import { craftWidthRatio } from '../../components/detail/charts/lineup-fit';
import { RENDER_HINTS } from '../../components/detail/charts/lineup';
import { BODY_COLORS } from '$lib/constants';
import { groupHref } from '$lib/state/url';
import { rocketBodies, rocketBySlug } from './rockets';

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

/** What the row draws for a bundle that *is* the object: the mesh alone, no
 *  sphere under it, and the shape of the box it needs. The size it is drawn at
 *  is the caller's, since a craft takes it from the manifest and an object
 *  carrying its own radius keeps that. */
function craftGeometry(entry: ModelIndexEntry): CompareObject['geometry'] {
	return {
		model: entry.slug,
		craft: true,
		meshSpanRatio: 1 / (entry.body_span_ratio ?? 1),
		aspect: entry.span_ratios ? craftWidthRatio(entry.span_ratios) || undefined : undefined
	};
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
		geometry: craftGeometry(entry)
	};
}

/** The bundle whose mesh *is* the object: a rocket's own, reached by slug and
 *  linking to its family's page, or the craft bundle attached to a catalogue
 *  Object. */
async function craftBundleFor(id: string): Promise<CompareObject | null> {
	const rocket = rocketBySlug(id);
	if (rocket) {
		const [body] = await rocketBodies([rocket], (r) =>
			r.group ? groupHref(r.group, r.label()) : null
		);
		if (!body) return null;
		const { model, craft, aspect, href } = body;
		return {
			id,
			name: body.name,
			type: 'rocket',
			radiusKm: body.radiusKm,
			geometry: { model, craft, aspect, href }
		};
	}
	const index = await fetchModelIndex().catch(() => null);
	const attached = index?.find(
		(e) => e.kind !== 'shape_model' && e.objects.some((o) => o.id === id)
	);
	return attached ? craftObject(id, '', attached) : null;
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
	if (craft) return { ...craft, name: seed.name || craft.name };

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

	// A bundle that is not a shape model is the object itself, so it is drawn
	// the way a craft is rather than draped over a sphere. Reached by anything
	// whose bundle the model index cannot attach to it — an object with no
	// catalogue row of its own carries the slug and nothing else does.
	if (global?.model_name) {
		const index = await fetchModelIndex().catch(() => null);
		const entry = index?.find((e) => e.slug === global.model_name);
		if (entry && entry.kind !== 'shape_model') {
			return { id, name, type, radiusKm, geometry: craftGeometry(entry) };
		}
	}

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
