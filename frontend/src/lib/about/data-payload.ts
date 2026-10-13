/**
 * Shape of `/v1/about-data.json` and the figures /about/data draws from it.
 * Mirror of `data/src/space_map_data/export/about_data.py`.
 */

import type { LabelMap } from '$lib/fetch/position/labels';

export type MapLayer = 'surface' | 'clouds' | 'night' | 'specular' | 'topography';

/** Where a ring or a model comes from. */
export interface Credit {
	/** The page of the source. A model can have none. */
	source?: string;
	organisation: string;
	attribution?: string;
}

/** Where a map or a patch comes from. */
export interface MapCredit extends Credit {
	source: string;
}

/** A whole-globe image of a map. */
export interface MapTier {
	name: string;
	width: number;
	height: number;
	/** All frames of the map together. */
	size_bytes: number;
	/** Ground size of a pixel at the equator. Absent for a body of unknown size. */
	m_per_px?: number;
}

/** One source of a tile pyramid. `detail` gives a colour map its fine detail. */
export interface MapSource {
	role: 'base' | 'inset' | 'detail';
	/** Pixels around the equator at the pixel size of the source. */
	width: number;
	m_per_px?: number;
	/** South and north edge, for a source that covers a band. */
	lat_range?: [number, number];
}

/** An area where a pyramid goes deeper than its finest level. */
export interface MapPatch extends MapCredit {
	id: string;
	name: string;
	max_level: number;
	m_per_px?: number;
	lat: number;
	lon: number;
	width_km?: number;
	height_km?: number;
	tiles: number;
	size_bytes: number;
}

export interface MapPyramid {
	max_level: number;
	/** Size of the finest level, in pixels. */
	width: number;
	height: number;
	m_per_px?: number;
	/** The map and its two polar caps, without the patches. */
	tiles: number;
	size_bytes: number;
	sources: MapSource[];
	/** Height maps only. */
	height_step_m?: number;
	patches?: MapPatch[];
}

/** Its credit is that of its pyramid, which can have another source than the
 *  whole-globe images. */
export interface WorldMap extends MapCredit {
	id: string;
	layer: MapLayer;
	/** A map ranked below the best map of its body. */
	alternate?: true;
	/** Present for a map of more than one frame. */
	frames?: number;
	/** Coarsest first. */
	tiers: MapTier[];
	/** Height maps only: the step of the whole-globe images. */
	height_step_m?: number;
	tiles?: MapPyramid;
}

export interface World {
	id: string;
	name: string;
	radius_km?: number;
	/** A giant planet: its `surface` map shows its cloud top. */
	no_surface?: true;
	maps: WorldMap[];
}

/** `id` and `name` are null for the bodies that belong to no planetary system. */
export interface DataSystem {
	id: string | null;
	name: string | null;
	/** The planet that the system takes its name from. */
	primary_id?: string;
	worlds: World[];
}

/** One bundle of the rings of a world. */
export interface Ring {
	/** `inner`, `primary` or `outer`. */
	id: string;
	/** From the centre of the body. */
	inner_radius_km: number;
	outer_radius_km: number;
	samples: number;
	/** Radial distance between two samples. */
	km_per_sample: number;
	size_bytes: number;
	sources: Credit[];
}

export interface RingWorld {
	id: string;
	name: string;
	/** Innermost first. */
	rings: Ring[];
}

/** One file of a model. */
export interface ModelTier {
	name: string;
	triangles: number;
	size_bytes: number;
}

export interface Model {
	slug: string;
	/** The low file, then the high one. */
	tiers: ModelTier[];
	/** Longest dimension of the object. Absent for a craft with no measured size. */
	extent_m?: number;
	sources: Credit[];
}

/** The measured shape of a world. */
export interface ShapeModel extends Model {
	provenance: string;
}

export interface ShapeWorld {
	id: string;
	name: string;
	models: ShapeModel[];
}

/** A model of a craft, or of another object that is not a world. */
export interface CraftModel extends Model {
	/** Objects that the map draws with the model. */
	objects: number;
	/** That object, where there is one. */
	object?: { id: string; name: string };
}

export interface CraftGroup {
	kind: string;
	models: CraftModel[];
}

/** The shapes from light curves, as one row. */
export interface LightcurveModels {
	models: number;
	worlds: number;
	triangles: number;
	size_bytes: number;
	sources: Credit[];
}

export interface DataModels {
	worlds: ShapeWorld[];
	craft: CraftGroup[];
	lightcurve?: LightcurveModels;
}

export interface AboutData {
	generated_at: string;
	/** Bodies with a map, a ring or a shape model. */
	worlds: number;
	/** The maps. */
	systems: DataSystem[];
	rings: RingWorld[];
	models: DataModels;
}

/** What the page loads: the report, and the names of its worlds in the
 *  language of the reader. */
export interface DataPage {
	data: AboutData;
	labels: LabelMap;
}

/** What the row of a map states. Patches are rows of their own. */
export interface MapFigures {
	m_per_px?: number;
	width?: number;
	height?: number;
	/** Absent for a map with no pyramid. */
	tiles?: number;
	size_bytes: number;
	height_step_m?: number;
}

/** The pyramid of a map where it has one, else its finest whole-globe image.
 *  The size counts both: the images stay as the fallback of the tiles. */
export function mapFigures(map: WorldMap): MapFigures {
	const tierBytes = map.tiers.reduce((sum, tier) => sum + tier.size_bytes, 0);
	const pyramid = map.tiles;
	if (pyramid) {
		return {
			m_per_px: pyramid.m_per_px,
			width: pyramid.width,
			height: pyramid.height,
			tiles: pyramid.tiles,
			size_bytes: pyramid.size_bytes + tierBytes,
			height_step_m: pyramid.height_step_m
		};
	}
	const finest = map.tiers.at(-1);
	return {
		m_per_px: finest?.m_per_px,
		width: finest?.width,
		height: finest?.height,
		size_bytes: tierBytes,
		height_step_m: map.height_step_m
	};
}

/** What the row of a model states. */
export interface ModelFigures {
	triangles: number;
	/** Present where the low file has another count. */
	low_triangles?: number;
	size_bytes: number;
}

/** The high file gives the triangles. The size counts each file. */
export function modelFigures(model: Model): ModelFigures {
	const triangles = model.tiers.at(-1)?.triangles ?? 0;
	const low = model.tiers[0]?.triangles;
	return {
		triangles,
		low_triangles: low === triangles ? undefined : low,
		size_bytes: model.tiers.reduce((sum, tier) => sum + tier.size_bytes, 0)
	};
}

/** Latitude bands joined where they touch, south to north. */
function mergedBands(bands: [number, number][]): [number, number][] {
	const out: [number, number][] = [];
	for (const [south, north] of [...bands].sort((a, b) => a[0] - b[0])) {
		const last = out.at(-1);
		if (last && south <= last[1]) last[1] = Math.max(last[1], north);
		else out.push([south, north]);
	}
	return out;
}

/**
 * The sources of a pyramid that a reader can tell apart: one entry for each
 * role and pixel size. Empty for a pyramid of one source, which its own row
 * already states. Sources that cover the body between them carry no band.
 */
export function listedSources(pyramid: MapPyramid): MapSource[] {
	const groups = new Map<string, MapSource[]>();
	for (const source of pyramid.sources) {
		const key = `${source.role}:${source.width}`;
		groups.set(key, [...(groups.get(key) ?? []), source]);
	}
	if (groups.size < 2) return [];
	return [...groups.values()].map((sources) => {
		const { role, width, m_per_px } = sources[0];
		const listed: MapSource = { role, width, m_per_px };
		const ranges = sources.flatMap((source) => (source.lat_range ? [source.lat_range] : []));
		if (ranges.length < sources.length) return listed;
		const bands = mergedBands(ranges.map(([south, north]) => [south, north]));
		const south = bands[0][0];
		const north = bands[bands.length - 1][1];
		// Bands with a gap between them are stated by their outer edges.
		return south <= -90 && north >= 90 && bands.length === 1
			? listed
			: { ...listed, lat_range: [south, north] };
	});
}

export interface DataTotals {
	worlds: number;
	maps: number;
	patches: number;
	tiles: number;
	rings: number;
	models: number;
	size_bytes: number;
}

export function totals(data: AboutData): DataTotals {
	const sum: DataTotals = {
		worlds: data.worlds,
		maps: 0,
		patches: 0,
		tiles: 0,
		rings: 0,
		models: 0,
		size_bytes: 0
	};
	for (const system of data.systems) {
		for (const world of system.worlds) {
			for (const map of world.maps) {
				const figures = mapFigures(map);
				sum.maps += 1;
				sum.tiles += figures.tiles ?? 0;
				sum.size_bytes += figures.size_bytes;
				for (const patch of map.tiles?.patches ?? []) {
					sum.patches += 1;
					sum.tiles += patch.tiles;
					sum.size_bytes += patch.size_bytes;
				}
			}
		}
	}
	for (const ring of data.rings.flatMap((world) => world.rings)) {
		sum.rings += 1;
		sum.size_bytes += ring.size_bytes;
	}
	const listed: Model[] = [
		...data.models.worlds.flatMap((world) => world.models),
		...data.models.craft.flatMap((group) => group.models)
	];
	for (const model of listed) {
		sum.models += 1;
		sum.size_bytes += modelFigures(model).size_bytes;
	}
	sum.models += data.models.lightcurve?.models ?? 0;
	sum.size_bytes += data.models.lightcurve?.size_bytes ?? 0;
	return sum;
}
