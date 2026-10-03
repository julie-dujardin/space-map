/**
 * The embeddable system map's three views — the Solar System, one planetary
 * system, one zone of small bodies — as models whose targets report a pick
 * instead of leading anywhere: where a pick goes is the host's to decide.
 */

import { BODY_COLORS, DEFAULT_BODY_COLOR, SSB_ID, SUN_ID } from '$lib/constants';
import { AU_KM } from '$lib/math/units';
import type {
	PlanetarySystemsMapEntry,
	PlanetarySystemsMapFile
} from '$lib/fetch/groups/planetary-systems-map';
import type { SolarSystemMapFile, SolarSystemMapObject } from '$lib/fetch/groups/solar-system-map';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import type { MapBand, MapBody, MapLink, MapSatellite, MapText, SystemMapModel } from './model';
import { planetarySystemModel, systemFromMapEntry } from './planetary';
import {
	SOLAR_PX_PER_DEG,
	SOLAR_PX_PER_KM,
	SUN_COLOR,
	displayName,
	fileStacks,
	solarColor,
	solarSystemModel,
	type SolarStack
} from './solar';

/** Small bodies inside Jupiter's orbit, or from it outward. */
export type SystemMapZone = 'inner' | 'outer';

export type SystemMapView =
	| { kind: 'solar-system' }
	/** One planetary system, named by its primary: `naif-699`, `naif-999`. */
	| { kind: 'system'; id: string }
	| { kind: 'zone'; zone: SystemMapZone };

/** What a click picked. A `system` is a primary drawn with satellites, named
 *  by the primary's id. */
export type SystemMapTarget =
	| { kind: 'body'; id: string; name: string }
	| { kind: 'system'; id: string; name: string }
	| { kind: 'zone'; zone: SystemMapZone; name: string };

/**
 * A body the map files name no place for, as a page that already knows it
 * describes it. The map otherwise reads the body's own bundle to place it,
 * which is a few hundred kilobytes a body.
 */
export interface SystemMapPlace {
	id: string;
	/** The id when left out, unless `names` has one. */
	name?: string;
	/** A moon rides in the stack over `parent` rather than on the axis. */
	moon?: boolean;
	/** Semi-major axis about the Sun in AU, or the perihelion of an orbit that
	 *  has none. A moon needs none. */
	aAu?: number;
	/** Inclination to the ecliptic. */
	tiltDeg?: number;
	radiusKm?: number;
	/** `#rrggbb`. */
	color?: string;
	/** What a moon orbits. */
	parent?: string;
}

/** A place with nothing left out. */
export type ExtraBody = Required<Omit<SystemMapPlace, 'parent'>> & { parent?: string };

export function extraFromPlace(place: SystemMapPlace): ExtraBody {
	return {
		id: place.id,
		name: place.name ?? place.id,
		moon: place.moon ?? false,
		aAu: place.aAu ?? 0,
		tiltDeg: place.tiltDeg ?? 0,
		radiusKm: place.radiusKm ?? 0,
		color: place.color ?? BODY_COLORS[place.id] ?? DEFAULT_BODY_COLOR,
		parent: place.parent
	};
}

export interface ViewData {
	solar: SolarSystemMapFile;
	systems: PlanetarySystemsMapFile;
	extras: readonly ExtraBody[];
}

export interface ViewOptions {
	/** Ids worth drawing; everything when null. */
	bodies: ReadonlySet<string> | null;
	names: Record<string, string>;
	grouping: 'bodies' | 'systems';
	zones: 'belts' | 'inner-outer';
}

export interface ViewText extends MapText {
	solarSystem: string;
	rings: string;
	axisRadii: string;
	zoneInner: string;
	zoneOuter: string;
}

export interface BuiltView {
	model: SystemMapModel;
	/** Everything a click can pick, in drawing order. */
	targets: SystemMapTarget[];
	/** What the view is of, for its accessible name. */
	label: string;
}

/** A stack taller than this runs off the top of the chart. */
const MAX_STACK = 4;
/** px the zone's largest body reads at. */
const ZONE_TOP_R = 10;
const ZONE_DOMAIN: Record<SystemMapZone, [number, number]> = {
	inner: [0.6, 5.5],
	outer: [4.5, 55]
};
const ZONE_TICKS = [0.1, 0.2, 0.3, 0.5, 1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 500, 1000];
/** How far along the axis a tick may sit before it runs into the axis label,
 *  which is longer in primary radii than in AU. */
const LAST_AU_TICK_AT = 0.9;
const LAST_RADII_TICK_AT = 0.76;

/** Where a tick sits along the log axis, 0 to 1. */
function tickAt(tick: number, domain: [number, number]): number {
	return Math.log(tick / domain[0]) / Math.log(domain[1] / domain[0]);
}
const JUPITER_ID = 'naif-599';

/** The ids `bodies` names that nothing places yet, each needing its own bundle
 *  read before a zone can draw it. */
export function unplacedIds(
	solar: SolarSystemMapFile,
	systems: PlanetarySystemsMapFile,
	bodies: ReadonlySet<string> | null,
	placed: Iterable<string> = []
): string[] {
	if (!bodies) return [];
	const known = new Set([...solar.objects.map((o) => o.id), ...placed]);
	for (const entry of Object.values(systems)) {
		known.add(entry.primary.id);
		for (const moon of entry.moons) known.add(moon.id);
	}
	return [...bodies].filter((id) => !known.has(id));
}

/** Null for a body whose bundle has no orbit to place it by: the axis is a
 *  distance from the Sun, so an orbit about anything else says nothing of it. */
export function extraFromBundle(global: GlobalObjectData): ExtraBody | null {
	const moon = global.type === 'moon';
	const parent = global.orbit?.parent_id;
	const heliocentric = parent === undefined || parent === SUN_ID || parent === SSB_ID;
	const a = heliocentric ? (global.orbit?.a ?? global.orbit?.q) : undefined;
	if (a === undefined && !moon) return null;
	const radii = global.radii;
	return {
		id: global.id,
		name: displayName(global.name ?? global.id),
		moon,
		aAu: a ?? 0,
		tiltDeg: global.orbit?.i ?? 0,
		radiusKm: radii ? (radii.a + radii.b + radii.c) / 3 : (global.sbdb?.diameter ?? 0) / 2,
		color: BODY_COLORS[global.id] ?? global.sbdb?.color ?? global.color ?? DEFAULT_BODY_COLOR,
		parent: global.orbit?.parent_id
	};
}

/** The trojans share Jupiter's orbit and swing either side of its size: the
 *  cut sits under them, and over the Hildas, so the swarm stays whole. */
const ZONE_CUT = 0.92;

export function zoneOf(aAu: number, jupiterAu: number): SystemMapZone {
	return aAu < jupiterAu * ZONE_CUT ? 'inner' : 'outer';
}

export function systemEntry(
	systems: PlanetarySystemsMapFile,
	primaryId: string
): PlanetarySystemsMapEntry | undefined {
	return Object.values(systems).find((entry) => entry.primary.id === primaryId);
}

function targetKey(target: SystemMapTarget): string {
	return target.kind === 'zone' ? `zone:${target.zone}` : `${target.kind}:${target.id}`;
}

/** Shared by the three views: what is in scope, what things are called, and
 *  the links that report a pick while keeping the list of them. */
class Scope {
	readonly targets = new Map<string, SystemMapTarget>();

	constructor(
		readonly data: ViewData,
		readonly options: ViewOptions,
		private readonly pick: (target: SystemMapTarget) => void
	) {}

	has(id: string): boolean {
		return !this.options.bodies || this.options.bodies.has(id);
	}

	name(id: string, exported?: string): string {
		return this.options.names[id] ?? (exported ? displayName(exported) : id);
	}

	/** The same for a name that is not the export's to tidy: the page's own,
	 *  or one already tidied. */
	named(id: string, name: string): string {
		return this.options.names[id] ?? name;
	}

	link(target: SystemMapTarget): MapLink {
		this.targets.set(targetKey(target), target);
		return { onclick: () => this.pick(target) };
	}

	body(id: string, name: string): MapLink | undefined {
		return this.has(id) ? this.link({ kind: 'body', id, name }) : undefined;
	}

	/** The moons in scope over `primaryId`, largest first, cut to what fits. */
	stack(primaryId: string, listed?: SolarStack): SolarStack | undefined {
		if (listed && !this.options.bodies) return listed;
		const entry = systemEntry(this.data.systems, primaryId);
		const moons: MapSatellite[] = (entry?.moons ?? [])
			.filter((moon) => this.has(moon.id))
			.map((moon) => ({
				id: moon.id,
				name: this.name(moon.id),
				radiusKm: moon.radius_km,
				color: BODY_COLORS[moon.id] ?? moon.color ?? DEFAULT_BODY_COLOR
			}));
		if (!moons.length) return undefined;
		moons.sort((a, b) => b.radiusKm - a.radiusKm);
		return { satellites: moons.slice(0, MAX_STACK), count: moons.length, tab: true };
	}

	/** What a body and its stack lead to, under the host's grouping. */
	links(
		id: string,
		name: string,
		stack: SolarStack | undefined
	): Pick<MapBody, 'link' | 'satellitesLink' | 'grouped'> {
		if (!stack) return { link: this.body(id, name) };
		const system = () => this.link({ kind: 'system', id, name });
		if (this.options.grouping === 'systems') return { link: system(), grouped: true };
		const largest = stack.satellites[0];
		return {
			link: this.body(id, name),
			satellitesLink: stack.tab ? system() : this.body(largest.id, largest.name)
		};
	}

	built(model: SystemMapModel, label: string): BuiltView {
		return { model, targets: [...this.targets.values()], label };
	}
}

export function buildSolarView(
	data: ViewData,
	options: ViewOptions,
	text: ViewText,
	pick: (target: SystemMapTarget) => void
): BuiltView {
	const scope = new Scope(data, options, pick);
	const name = (o: SolarSystemMapObject) => scope.name(o.id, o.name);
	const listed = fileStacks(data.solar, name);
	const stacks = new Map(
		data.solar.objects.map((o) => [o.id, scope.stack(o.id, listed.get(o.id))])
	);
	const sun = data.solar.objects.find((o) => o.kind === 'star');
	const zoneBand = (zone: SystemMapZone) => {
		const label = zone === 'inner' ? text.zoneInner : text.zoneOuter;
		return { label, sub: '', ...scope.link({ kind: 'zone', zone, name: label }) };
	};
	const model = solarSystemModel(data.solar, {
		text,
		name,
		primaryLink: sun && scope.body(sun.id, name(sun)),
		keep: (o) => scope.has(o.id) || !!stacks.get(o.id),
		stack: (o) => stacks.get(o.id),
		links: (o, stack) => scope.links(o.id, name(o), stack),
		band: (belt) =>
			options.zones === 'belts'
				? { label: belt.label }
				: zoneBand(belt.kind === 'kuiper_belt' ? 'outer' : 'inner')
	});
	if (!model) throw new Error('spacemap: the Solar System map names no Sun');
	return scope.built(model, text.solarSystem);
}

export function buildSystemView(
	data: ViewData,
	primaryId: string,
	/** The export's own names for the primary and its moons, by id. */
	exported: Record<string, string>,
	options: ViewOptions,
	text: ViewText,
	pick: (target: SystemMapTarget) => void
): BuiltView {
	const entry = systemEntry(data.systems, primaryId);
	if (!entry) throw new Error(`spacemap: no planetary system around ${primaryId}`);
	const scope = new Scope(data, options, pick);
	const system = systemFromMapEntry(entry, scope.name(primaryId, exported[primaryId]));
	system.moons = system.moons
		.filter((moon) => scope.has(moon.id))
		.map((moon) => ({ ...moon, name: scope.name(moon.id, exported[moon.id]) }));
	const rKm = system.planetRadiusKm;
	const bands: MapBand[] = system.rings
		? [
				{
					key: 'rings',
					label: text.rings,
					innerKm: system.rings.innerRp * rKm,
					outerKm: system.rings.outerRp * rKm,
					tone: 'amber'
				}
			]
		: [];
	const model = planetarySystemModel(system, {
		text,
		axisLabel: text.axisRadii,
		bands,
		primaryLink: scope.body(primaryId, system.planetName),
		moonLink: (moon) => scope.body(moon.id, moon.name)
	});
	model.ticks = model.ticks.filter((t) => tickAt(t, model.domain) < LAST_RADII_TICK_AT);
	return scope.built(model, system.planetName);
}

export function buildZoneView(
	data: ViewData,
	zone: SystemMapZone,
	options: ViewOptions,
	text: ViewText,
	pick: (target: SystemMapTarget) => void
): BuiltView {
	const scope = new Scope(data, options, pick);
	const { solar, extras } = data;
	const sun = solar.objects.find((o) => o.kind === 'star');
	const jupiterAu = solar.objects.find((o) => o.id === JUPITER_ID)?.a;
	if (!sun || jupiterAu === undefined)
		throw new Error('spacemap: the Solar System map names no Sun or no Jupiter');

	interface Small {
		id: string;
		name: string;
		aAu: number;
		tiltDeg: number;
		radiusKm: number;
		color: string;
	}
	const small: Small[] = solar.objects
		.filter((o) => o.kind === 'dwarf' || o.kind === 'asteroid')
		.map((o) => ({
			id: o.id,
			name: scope.name(o.id, o.name),
			aAu: o.a,
			tiltDeg: o.i,
			radiusKm: o.diameter_km / 2,
			color: solarColor(o)
		}));
	for (const extra of extras) {
		if (extra.moon || small.some((s) => s.id === extra.id)) continue;
		// The axis is a logarithm of the orbit's size: a place given none, or a
		// hyperbola's negative one, has nowhere on it.
		if (!(extra.aAu > 0)) continue;
		small.push({ ...extra, name: scope.named(extra.id, extra.name) });
	}

	const bodies: MapBody[] = [];
	for (const s of small) {
		if (zoneOf(s.aAu, jupiterAu) !== zone) continue;
		const base = { ...s, aKm: s.aAu * AU_KM };
		const stack = scope.stack(s.id);
		if (stack) {
			bodies.push({
				...base,
				satellites: stack.satellites,
				satelliteCount: stack.count,
				satellitesTab: true,
				...scope.links(s.id, s.name, stack)
			});
			continue;
		}
		// Moons no system map places: each its own target over its parent.
		const moons = extras
			.filter((extra) => extra.moon && extra.parent === s.id && scope.has(extra.id))
			.map((extra) => {
				const name = scope.named(extra.id, extra.name);
				return { ...extra, name, link: scope.body(extra.id, name) };
			});
		if (!scope.has(s.id) && !moons.length) continue;
		bodies.push({
			...base,
			link: scope.body(s.id, s.name),
			satellites: moons.length ? moons : undefined
		});
	}

	const [lo, hi] = ZONE_DOMAIN[zone];
	const domain: [number, number] = [
		Math.min(lo, ...bodies.map((b) => (b.aKm / AU_KM) * 0.85)),
		Math.max(hi, ...bodies.map((b) => (b.aKm / AU_KM) * 1.15))
	];
	const within = (au: number) => au >= domain[0] && au <= domain[1];
	const pxPerKm = ZONE_TOP_R / Math.max(...bodies.map((b) => b.radiusKm), 1);
	// The planets are what a reader finds the zone by; they are not in it.
	for (const o of solar.objects) {
		if (o.kind !== 'planet' || !within(o.a)) continue;
		bodies.push({
			id: o.id,
			name: scope.name(o.id, o.name),
			aKm: o.a * AU_KM,
			tiltDeg: 0,
			radiusKm: 0,
			color: solarColor(o),
			reference: true
		});
	}

	const label = zone === 'inner' ? text.zoneInner : text.zoneOuter;
	return scope.built(
		{
			primary: {
				id: sun.id,
				name: scope.name(sun.id, sun.name),
				// Its Solar System map size: at the small bodies' scale the Sun
				// would be a wall with no limb to read it by.
				radiusKm: ((sun.diameter_km / 2) * SOLAR_PX_PER_KM) / pxPerKm,
				color: SUN_COLOR
			},
			bodies,
			bands: solar.belts
				.filter((belt) => within(belt.inner_au) && within(belt.outer_au))
				.map((belt) => ({
					key: belt.slug,
					label: belt.label,
					innerKm: belt.inner_au * AU_KM,
					outerKm: belt.outer_au * AU_KM,
					tone: belt.kind === 'kuiper_belt' ? 'sky' : 'muted'
				})),
			unitKm: AU_KM,
			domain,
			ticks: ZONE_TICKS.filter((t) => within(t) && tickAt(t, domain) < LAST_AU_TICK_AT),
			axisLabel: text.axisAu,
			pxPerKm,
			pxPerDeg: SOLAR_PX_PER_DEG,
			text
		},
		label
	);
}
