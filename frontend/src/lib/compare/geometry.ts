/**
 * What the comparison row needs to draw one object, whatever it is: a planet,
 * a moon, a small body, a spacecraft or a star.
 *
 * A size arrives in two steps. The search hit carries a diameter, so a body
 * enters the row the moment it is picked; its own bundle then supplies the
 * measured shape, the pole it tilts on, and the mesh and surface map the scene
 * would draw, and the row redraws on that. A spacecraft has no radius at all,
 * so its size comes from the model index instead; a rocket is nothing but its
 * bundle, and is named by the row itself. A star of the extrasolar catalogue
 * has no bundle to draw from: its catalogue record gives its size and colour.
 */

import { SUN_ID } from '$lib/constants';
import { extrasolarIdOf, isStarObjectId, planetOfObjectId } from '$lib/fetch/extrasolar/ids';
import { formatSizeKm } from '$lib/format/distance';
import { localName } from '$lib/format/name';
import { drawnPlanet, planetRadiusKm } from '$lib/scene/exoplanets/drawn';
import { lunarWeightScaleOf } from '$lib/scene/exoplanets/photometry';
import {
	extrasolarLookup,
	POINT_SOURCE_SLUG,
	systemPrimary,
	type ExtrasolarRecord
} from '$lib/fetch/extrasolar/lookup';
import { starPageName } from '$lib/fetch/extrasolar/star-name';
import { systemNode } from '$lib/fetch/extrasolar/systems';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { starCssColour, teffFromBpRp } from '$lib/scene/starfield/colour';
import { colourBpRp, starRadiusKm, starTeff } from '$lib/scene/starfield/record';
import { loadSystemsGlobal, nutPrecFor } from '$lib/fetch/systems-global';
import { iauAngles } from '$lib/math/orientation';
import { dateToJD } from '$lib/time/jd';
import { fetchModelIndex, type ModelIndexEntry } from '$lib/fetch/models';
import type { LineupBody } from '../../components/detail/charts/BodyLineup.svelte';
import { craftWidthRatio } from '../../components/detail/charts/lineup-fit';
import { RENDER_HINTS } from '../../components/detail/charts/lineup';
import { SUN_TEFF } from '../../components/detail/charts/lineup-star';
import { groupHref } from '$lib/state/page-href';
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

/** The object's size for the list, the labels and the fit. A craft is quoted
 *  across its whole mesh. */
export function sizeText(object: CompareObject): string {
	const { meshSpanRatio, sizeEstimated } = object.geometry;
	return formatSizeKm(object.radiusKm * 2 * (meshSpanRatio ?? 1), sizeEstimated);
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

/** A star's radius is known to a few percent at best. */
const RADIUS_DIGITS = 3;

async function liveRecord(id: number): Promise<ExtrasolarRecord | null> {
	const found = await extrasolarLookup.live(id);
	return found.kind === 'live' ? found.record : null;
}

/** The record with the radius that a star is drawn at: its own, a resolved
 *  system's primary's, or for a point of several stars, its first member's
 *  when that member dominates the point's light. */
async function sizedRecord(record: ExtrasolarRecord): Promise<ExtrasolarRecord | null> {
	if (record.metadata.radius) return record;
	const primary = systemPrimary(record);
	if (primary === null) return null;
	if (primary !== record.id) {
		const found = await liveRecord(primary);
		return found && sizedRecord(found);
	}
	const first = systemNode(record)?.members[0]?.id ?? null;
	const member = first === null ? null : await liveRecord(first);
	return member && systemNode(member)?.star?.dominant ? member : null;
}

/** A star's temperature: its Point source row's, else a held star's. */
function teffOf(record: ExtrasolarRecord): number | null {
	const row = record.rows.get(POINT_SOURCE_SLUG);
	if (!row) return systemNode(record)?.star?.teff ?? null;
	const colour = colourBpRp(row);
	return starTeff(row) ?? (colour === null ? null : teffFromBpRp(colour));
}

/** A star of the extrasolar catalogue, sized and coloured as a row of stars is.
 *  A star system stands for its main star, and a point of several stars for
 *  its dominant member. */
async function starObject(id: string, seed: { name: string }): Promise<CompareObject | null> {
	const star = extrasolarIdOf(id);
	const found = star === null ? null : await extrasolarLookup.live(star);
	if (found?.kind !== 'live') return null;
	const record = await sizedRecord(found.record);
	const radiusKm = record && starRadiusKm(record.metadata);
	const teff = record && (teffOf(record) ?? teffOf(found.record));
	if (!radiusKm || !teff) return null;
	return {
		id,
		name: seed.name || (await starPageName(found.record)) || id,
		type: 'star',
		radiusKm: Number(radiusKm.toPrecision(RADIUS_DIGITS)),
		geometry: {
			texture: false,
			photosphere: { teff },
			color: starCssColour(teff, null)
		}
	};
}

/** A planet of another star, drawn as in the scene at the archive's radius.
 *  The row marks an estimated radius. Null for a planet that does not draw. */
async function drawnPlanetObject(
	id: string,
	seed: { name: string; type?: string }
): Promise<CompareObject | null> {
	const planet = await drawnPlanet(id);
	if (!planet) return null;
	return {
		id,
		name: seed.name || localName(planet),
		type: seed.type,
		radiusKm: Number(planetRadiusKm(planet).toPrecision(RADIUS_DIGITS)),
		geometry: {
			texture: true,
			lunarWeightScale: lunarWeightScaleOf(id),
			sizeEstimated: planet.estimated.includes('radius')
		}
	};
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
	if (isStarObjectId(id)) return starObject(id, seed);
	// A planet of another star has no bundle. Its system file has its size and maps.
	if (planetOfObjectId(id)) return drawnPlanetObject(id, seed);
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
	if (global?.orientation) {
		// Today's pole, with the nutation terms: Triton's leans 20° off its mean.
		// Without the angles it falls back to the mean pole.
		if (global.nut_prec) await loadSystemsGlobal().catch(() => {});
		const nutPrec = nutPrecFor(id, global.nut_prec);
		const pole = iauAngles(global.orientation, dateToJD(new Date()), nutPrec);
		geometry.poleRa = pole.ra;
		geometry.poleDec = pole.dec;
	}
	if (global?.model_name) geometry.model = global.model_name;
	if (global?.displacement) geometry.displacement = global.displacement;
	geometry.texture = global?.map_texture_available ?? false;
	// The measured colour the scene uses. Small bodies carry it under `sbdb`.
	geometry.color = global?.sbdb?.color ?? global?.color;
	geometry.geometricAlbedo = global?.sbdb?.geometric_albedo ?? global?.geometric_albedo;
	geometry.lunarWeightScale = global?.lunar_weight_scale;
	if (id === SUN_ID) geometry.photosphere = { teff: SUN_TEFF };

	return { id, name, type, radiusKm, geometry: { ...geometry, ...RENDER_HINTS[id] } };
}
