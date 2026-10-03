/**
 * The system map as an embed: the Solar System, a planetary system or a zone
 * of small bodies as a diagram to pick from. It draws from the export's own
 * figures and no imagery, so it carries no credit line.
 */

import {
	fetchPlanetarySystemsMap,
	type PlanetarySystemsMapFile
} from '$lib/fetch/groups/planetary-systems-map';
import { fetchSolarSystemMap } from '$lib/fetch/groups/solar-system-map';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { host } from '$lib/host';
import { AU_KM } from '$lib/math/units';
import { SystemMapChart } from './chart';
import {
	buildSolarView,
	buildSystemView,
	buildZoneView,
	extraFromBundle,
	extraFromPlace,
	systemEntry,
	unplacedIds,
	type BuiltView,
	type ExtraBody,
	type SystemMapPlace,
	type SystemMapTarget,
	type SystemMapView,
	type ViewData,
	type ViewOptions,
	type ViewText
} from './views';

export interface SystemMapOptions {
	/** What to draw first; the Solar System when omitted. */
	view?: SystemMapView;
	/** The ids worth drawing, for a map that offers part of the catalogue. A
	 *  primary outside them is still drawn while a moon of it is in, as the
	 *  thing the moon is found by. Everything the export lists when omitted. */
	bodies?: readonly string[];
	/** Names by id, over the export's own. */
	names?: Record<string, string>;
	/** Bodies neither map file places, described by the page so the map need
	 *  not read each one's bundle to draw it in its zone. */
	places?: readonly SystemMapPlace[];
	/** `systems` makes a primary and the moons stacked on it one target, a
	 *  `system`; `bodies` leaves the dot and the stack a target each. */
	grouping?: 'bodies' | 'systems';
	/** `inner-outer` turns the two belts into the doors of the two zones of
	 *  small bodies; `belts` leaves them the scenery they are. */
	zones?: 'belts' | 'inner-outer';
}

export interface SystemMapEvents {
	/** Something was picked. The map does not follow it: {@link SystemMap.setView}
	 *  is the host's to call. */
	select: (target: SystemMapTarget) => void;
	viewchange: (view: SystemMapView) => void;
	/** A view could not be loaded, or a body named in `bodies` could not be read. */
	error: (error: Error) => void;
}

const onceTarget = new WeakMap<object, unknown>();

/** Under this, in AU, a distance reads better in kilometres. */
const AU_TO_KM_THRESHOLD = 0.01;

function viewText(): ViewText {
	const { messages, locale } = host();
	const number = new Intl.NumberFormat(locale(), { maximumSignificantDigits: 3 });
	const kilometres = new Intl.NumberFormat(locale(), {
		style: 'unit',
		unit: 'kilometer',
		maximumSignificantDigits: 3
	});
	const au = messages.unit_symbol_astronomical_unit();
	return {
		primary: messages.planetary_system_primary(),
		retrograde: messages.planetary_system_retrograde(),
		moons: (count) => messages.system_map_moons({ count }),
		distance: (km) => {
			const distance = km / AU_KM;
			return distance > 0 && distance < AU_TO_KM_THRESHOLD
				? kilometres.format(km)
				: `${number.format(distance)} ${au}`;
		},
		axisAu: messages.system_map_axis_au(),
		solarSystem: messages.system_map_solar_system(),
		rings: messages.tab_rings(),
		axisRadii: messages.planetary_system_axis_unit(),
		zoneInner: messages.system_map_zone_inner(),
		zoneOuter: messages.system_map_zone_outer()
	};
}

/** The diagram and what it shows. It follows no click: `select` says what was
 *  picked and {@link SystemMap.setView} is the page's to call. */
export class SystemMap {
	private readonly chart = new SystemMapChart();
	private readonly listeners = new Map<keyof SystemMapEvents, Set<(...args: never[]) => void>>();
	private view: SystemMapView;
	private bodies: ReadonlySet<string> | null;
	private readonly names: Record<string, string>;
	private readonly grouping: 'bodies' | 'systems';
	private readonly zones: 'belts' | 'inner-outer';
	private readonly places: ExtraBody[];
	private targets: SystemMapTarget[] = [];
	/** Bundles read for the bodies no map file places, by id; null where the
	 *  bundle has no orbit to place it by. */
	private readonly extras = new Map<string, Promise<ExtraBody | null>>();
	/** Draws run one after another, so a later one neither lands under an
	 *  earlier nor takes it off the map by failing. */
	private queue: Promise<void> = Promise.resolve();
	private disposed = false;

	constructor(options: SystemMapOptions = {}) {
		this.view = options.view ?? { kind: 'solar-system' };
		this.bodies = options.bodies ? new Set(options.bodies) : null;
		this.names = options.names ?? {};
		this.grouping = options.grouping ?? 'bodies';
		this.zones = options.zones ?? 'belts';
		this.places = (options.places ?? []).map(extraFromPlace);
	}

	// -- lifecycle ------------------------------------------------------------

	/** @internal Put the map's own box inside `container`. {@link createSystemMap}
	 *  does this; a host never has to. */
	mount(container: HTMLElement): void {
		container.append(this.chart.root);
	}

	/** Take the map back out of its container. It is finished afterwards; open
	 *  another with {@link createSystemMap}. */
	remove(): void {
		this.disposed = true;
		this.chart.destroy();
	}

	/** @internal Draw the opening view. Resolves once it is on screen. */
	load(): Promise<void> {
		return this.draw();
	}

	// -- what it shows --------------------------------------------------------

	/** Draw another view. Resolves once it is on screen; rejects, leaving the
	 *  map as it was, when the view cannot be loaded — a `system` named for a
	 *  body with no moons has no map. */
	async setView(view: SystemMapView): Promise<void> {
		await this.draw(view);
	}

	getView(): SystemMapView {
		return this.view;
	}

	/** Change which bodies are worth drawing; null for all of them. The view
	 *  stays, redrawn: resolves once it is, and `error` says when it could not be. */
	setBodies(ids: readonly string[] | null): Promise<void> {
		const bodies = ids ? new Set(ids) : null;
		return this.draw(undefined, bodies).catch(() => {});
	}

	/** Everything a click on the current view can pick. */
	getTargets(): SystemMapTarget[] {
		return [...this.targets];
	}

	/** Draw `view`, or the one on the map, in its turn. `bodies` is taken up
	 *  at that turn too, so it never changes under a draw that is under way. */
	private draw(view?: SystemMapView, bodies?: ReadonlySet<string> | null): Promise<void> {
		const turn = this.queue.then(() => {
			if (bodies !== undefined) this.bodies = bodies;
			return this.drawNow(view ?? this.view);
		});
		this.queue = turn.catch(() => {});
		return turn;
	}

	private async drawNow(view: SystemMapView): Promise<void> {
		let built: BuiltView;
		try {
			built = await this.build(view);
		} catch (cause) {
			const error = cause instanceof Error ? cause : new Error(String(cause));
			if (!this.disposed) this.emit('error', error);
			throw error;
		}
		if (this.disposed) return;
		const changed = JSON.stringify(view) !== JSON.stringify(this.view);
		this.view = view;
		this.targets = built.targets;
		this.chart.update(built.model, { ariaLabel: built.label });
		if (changed) this.emit('viewchange', view);
	}

	private async build(view: SystemMapView): Promise<BuiltView> {
		const [solar, systems] = await Promise.all([fetchSolarSystemMap(), fetchPlanetarySystemsMap()]);
		const options: ViewOptions = {
			bodies: this.bodies,
			names: this.names,
			grouping: this.grouping,
			zones: this.zones
		};
		const text = viewText();
		const pick = (target: SystemMapTarget) => this.emit('select', target);
		const data: ViewData = { solar, systems, extras: [] };
		switch (view.kind) {
			case 'solar-system':
				return buildSolarView(data, options, text, pick);
			case 'system':
				return buildSystemView(
					data,
					view.id,
					await this.exportedNames(view.id, systems),
					options,
					text,
					pick
				);
			case 'zone': {
				const ids = unplacedIds(
					solar,
					systems,
					this.bodies,
					this.places.map((place) => place.id)
				);
				const read = (await Promise.all(ids.map((id) => this.extra(id)))).filter(
					(extra) => extra !== null
				);
				// A moon is drawn over its parent, which `bodies` need not name.
				const placed = [...this.places, ...read];
				const parents = unplacedIds(
					solar,
					systems,
					new Set(placed.flatMap((extra) => (extra.moon && extra.parent ? [extra.parent] : []))),
					placed.map((extra) => extra.id)
				);
				const hosts = await Promise.all(parents.map((id) => this.extra(id)));
				const extras = [...placed, ...hosts.filter((extra) => extra !== null)];
				return buildZoneView({ ...data, extras }, view.zone, options, text, pick);
			}
		}
	}

	/** One body's own bundle, read once. A body that cannot be read is left
	 *  off the map and reported, rather than taking the view down with it. */
	private extra(id: string): Promise<ExtraBody | null> {
		let pending = this.extras.get(id);
		if (!pending) {
			pending = fetchObjectDetail(id, false)
				.then((detail) => {
					if (!detail.global) throw new Error(`spacemap: no such body as ${id}`);
					return extraFromBundle(detail.global);
				})
				.catch((cause: unknown) => {
					this.extras.delete(id);
					this.emit('error', cause instanceof Error ? cause : new Error(String(cause)));
					return null;
				});
			this.extras.set(id, pending);
		}
		return pending;
	}

	/** The primary's and its notable moons' names as the export has them, in
	 *  the reading language where it has them in it. Empty when the bundle does not load: the map then
	 *  falls back to ids rather than failing over a label. */
	private async exportedNames(
		primaryId: string,
		systems: PlanetarySystemsMapFile
	): Promise<Record<string, string>> {
		// A page that names everything in view spares the read.
		const drawn = [primaryId, ...(systemEntry(systems, primaryId)?.moons ?? []).map((m) => m.id)];
		const unnamed = drawn.some(
			(id) => !(id in this.names) && (id === primaryId || !this.bodies || this.bodies.has(id))
		);
		if (!unnamed) return {};
		try {
			const { global, localized } = await fetchObjectDetail(primaryId, true, host().locale());
			const names: Record<string, string> = {};
			for (const moon of global?.notable_moons ?? []) if (moon.id) names[moon.id] = moon.name;
			Object.assign(names, localized?.notable_moon_names);
			const name = localized?.name ?? global?.name;
			if (name) names[primaryId] = name;
			return names;
		} catch {
			return {};
		}
	}

	// -- events ---------------------------------------------------------------

	/** Listen for `event`. The returned function stops listening, which is the
	 *  same thing {@link off} does. */
	on<K extends keyof SystemMapEvents>(event: K, listener: SystemMapEvents[K]): () => void {
		let set = this.listeners.get(event);
		if (!set) {
			set = new Set();
			this.listeners.set(event, set);
		}
		set.add(listener as (...args: never[]) => void);
		return () => set.delete(listener as (...args: never[]) => void);
	}

	/** Listen for the next `event` only. */
	once<K extends keyof SystemMapEvents>(event: K, listener: SystemMapEvents[K]): () => void {
		const wrapped = ((...args: Parameters<SystemMapEvents[K]>) => {
			off();
			(listener as (...a: Parameters<SystemMapEvents[K]>) => void)(...args);
		}) as SystemMapEvents[K];
		onceTarget.set(wrapped, listener);
		const off = this.on(event, wrapped);
		return off;
	}

	off<K extends keyof SystemMapEvents>(event: K, listener: SystemMapEvents[K]): void {
		const set = this.listeners.get(event);
		if (!set) return;
		set.delete(listener as (...args: never[]) => void);
		// A `once` listener is held as its wrapper, which the host never sees.
		for (const held of set) if (onceTarget.get(held) === listener) set.delete(held);
	}

	private emit<K extends keyof SystemMapEvents>(
		event: K,
		...args: Parameters<SystemMapEvents[K]>
	): void {
		const set = this.listeners.get(event);
		if (!set) return;
		for (const listener of [...set]) (listener as (...a: unknown[]) => void)(...args);
	}
}
