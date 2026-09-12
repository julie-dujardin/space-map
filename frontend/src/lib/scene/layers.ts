/**
 * What the map draws, as a set of switchable layers. A layer is either a kind
 * of object — planets, moons, asteroids — or a piece of scene chrome, like the
 * orbit lines or the sky behind everything.
 *
 * Two questions are asked of the set, and they are not the same question. A
 * layer switched off before the map opens is never fetched, so an embed that
 * wants Mars alone downloads Mars alone; that answer is frozen at
 * {@link LayerSet.skipped} and read by the loader. A layer switched off later
 * is only hidden, so a switch costs a frame and never a request; that answer
 * lives in {@link LayerSet.hidden} and is read per frame. Switching a skipped
 * layer back on therefore shows nothing: its data was never downloaded.
 */

import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { EARTH_ID } from '$lib/constants';

/** Every layer, in the order a switcher should offer them: the objects first,
 *  then the chrome drawn around them. */
export const MAP_LAYERS = [
	'planets',
	'dwarfPlanets',
	'moons',
	'asteroids',
	'comets',
	'spacecraft',
	'satellites',
	'debris',
	'orbits',
	'labels',
	'nomenclature',
	'stars'
] as const;

export type MapLayerId = (typeof MAP_LAYERS)[number];

const LAYER_IDS: ReadonlySet<string> = new Set(MAP_LAYERS);

/** Object types that answer to a layer. A star, a barycentre and a Lagrange
 *  point answer to none: the Sun lights the scene whatever is hidden, and the
 *  other two are navigational marks rather than objects. */
const LAYER_BY_TYPE: Partial<Record<ObjectType, MapLayerId>> = {
	[ObjectType.PLANET]: 'planets',
	[ObjectType.DWARF_PLANET]: 'dwarfPlanets',
	[ObjectType.MOON]: 'moons',
	[ObjectType.ASTEROID]: 'asteroids',
	[ObjectType.ASTEROID_INNER]: 'asteroids',
	[ObjectType.ASTEROID_MAIN_BELT]: 'asteroids',
	[ObjectType.ASTEROID_TROJAN]: 'asteroids',
	[ObjectType.ASTEROID_CENTAUR]: 'asteroids',
	[ObjectType.ASTEROID_TNO]: 'asteroids',
	[ObjectType.COMET]: 'comets',
	[ObjectType.DEBRIS]: 'debris'
};

const SMALL_BODY_ZONE_PREFIX = 'small_bodies/';

/** Orbit-class zones the export writes comets into. Spelled from the ingest's
 *  own class table rather than the app's `smallBodyCategory`, which reads
 *  Encke-type comets as comets while the export types their records as
 *  trans-Neptunian: a layer has to agree with the record, or a promoted body
 *  and the point cloud it came from would answer to different switches. */
const COMET_ZONE_CLASSES: ReadonlySet<string> = new Set([
	'COM',
	'PAR',
	'HYP',
	'HYA',
	'JFC',
	'JFc',
	'HTC',
	'CTc'
]);

/**
 * The layer a zone of the export belongs to, or null for one that answers to
 * none. `major` and `major_asteroids` are null: they carry the Sun, the
 * planets and the dwarf planets in one file, so nothing is saved by leaving a
 * part of it out. `earth` is null too — Earth satellites and debris share it,
 * and {@link LayerSet.skipsZone} takes both layers into account.
 */
export function zoneLayer(zone: string): MapLayerId | null {
	if (zone === 'moons' || zone.startsWith('moons/') || zone === 'small_body_moons') return 'moons';
	if (zone.startsWith('probes/')) return 'spacecraft';
	if (zone.startsWith(SMALL_BODY_ZONE_PREFIX)) {
		return COMET_ZONE_CLASSES.has(zone.slice(SMALL_BODY_ZONE_PREFIX.length))
			? 'comets'
			: 'asteroids';
	}
	return null;
}

/** The layer an object answers to. Spacecraft split on what they orbit: the
 *  ones round Earth are the satellite population, the rest are the probes. */
export function bodyLayer(objectType: ObjectType, parentId: string): MapLayerId | null {
	if (objectType === ObjectType.SPACECRAFT) {
		return parentId === EARTH_ID ? 'satellites' : 'spacecraft';
	}
	return LAYER_BY_TYPE[objectType] ?? null;
}

/** Which layers a map draws, and which it never downloaded. */
export class LayerSet {
	/** Switched off before the map opened: their data is not fetched, so they
	 *  stay empty even when switched back on. */
	readonly skipped: ReadonlySet<MapLayerId>;
	private readonly hiddenIds: Set<MapLayerId>;
	/** Called after a switch, so the scene can repack what it draws. */
	onChange: (() => void) | null = null;

	constructor(options: Partial<Record<MapLayerId, boolean>> = {}) {
		const off = new Set<MapLayerId>();
		for (const id of MAP_LAYERS) if (options[id] === false) off.add(id);
		this.skipped = off;
		this.hiddenIds = new Set(off);
	}

	isVisible(id: MapLayerId): boolean {
		return !this.hiddenIds.has(id);
	}

	setVisible(id: MapLayerId, visible: boolean): void {
		if (visible === this.isVisible(id)) return;
		if (visible) this.hiddenIds.delete(id);
		else this.hiddenIds.add(id);
		this.onChange?.();
	}

	/** True for an id this map knows. A host reading ids back off
	 *  {@link MAP_LAYERS} never sees false; one spelling its own does. */
	static has(id: string): id is MapLayerId {
		return LAYER_IDS.has(id);
	}

	/** True when the zone's data is not to be fetched at all. The Earth zone
	 *  carries the satellites and the debris together, so it is only skipped
	 *  when neither is wanted. */
	skipsZone(zone: string): boolean {
		if (zone === 'earth') return this.skipped.has('satellites') && this.skipped.has('debris');
		const layer = zoneLayer(zone);
		return layer !== null && this.skipped.has(layer);
	}

	/** True when a point cloud of this zone is not to be drawn. */
	hidesZone(zone: string): boolean {
		const layer = zoneLayer(zone);
		return layer !== null && !this.isVisible(layer);
	}

	hidesBody(objectType: ObjectType, parentId: string): boolean {
		const layer = bodyLayer(objectType, parentId);
		return layer !== null && !this.isVisible(layer);
	}

	/** True when a spacecraft point cloud is not to be drawn at all. Round
	 *  Earth the cloud mixes satellites with debris, so it only goes when
	 *  neither is wanted; with one of the two on, the repack leaves the other
	 *  kind out instead. */
	hidesSpacecraftGroup(parentId: string): boolean {
		if (parentId !== EARTH_ID) return !this.isVisible('spacecraft');
		return !this.isVisible('satellites') && !this.isVisible('debris');
	}
}

/** The members of a spacecraft group that are drawn. Round Earth the
 *  satellites and the debris ride one point cloud, so leaving one kind out is
 *  a repack of the cloud rather than a switch on it; everywhere else the
 *  group is of one kind and goes whole. */
export function drawnSpacecraft(
	layers: LayerSet,
	parentId: string,
	bodies: PositionedBody[]
): PositionedBody[] {
	if (parentId !== EARTH_ID) return bodies;
	if (layers.isVisible('satellites') === layers.isVisible('debris')) return bodies;
	return bodies.filter((b) => !layers.hidesBody(b.data.objectType, b.data.parentId));
}
