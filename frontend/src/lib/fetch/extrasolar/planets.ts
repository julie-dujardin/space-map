/**
 * The planets of the extrasolar export (`docs/export-format/extrasolar.md`,
 * "Planets"). The planet index lists each host star with the key of its
 * system file. A system file holds the host stars and the planets of one
 * planetary system. Both are gzip JSON whose `token` field is the `planets`
 * token of `metadata.json`.
 */

import { LruPromiseCache } from '$lib/fetch/position/cache';
import {
	extrasolarAllowed,
	extrasolarPath,
	fetchExtrasolarJson,
	fetchExtrasolarMetadata,
	type ExtrasolarMetadata
} from './files';

/** What fixes the mean anomaly of the elements: `assumed` when the position
 *  on the orbit is unknown. */
export type PlanetPhase = 'transit' | 'periastron' | 'assumed';

/** A planet's orbit around its host on the ecliptic and equinox of J2000:
 *  AU, degrees, degrees per day and JD TDB. */
export interface PlanetElements {
	a: number;
	e: number;
	i: number;
	om: number;
	w: number;
	ma: number;
	/** 0 when the period is unknown: the planet stays at its place at `epoch`. */
	n: number;
	epoch: number;
	phase: PlanetPhase;
	/** Elements that are not as published, such as an eccentricity outside [0, 1). */
	replaced?: string[];
}

export interface PlanetIndexHost {
	id: number;
	/** Key of the system file. */
	system: number;
	/** Live planet numbers, ascending. */
	planets: number[];
	/** pc, in the frame of the render tree; null when the host has no place.
	 *  A resolved star system is not drawn as a star, and has the place of
	 *  one of its points. */
	position: [number, number, number] | null;
	/** AU, the largest semi-major axis of its planets; null when none has one. */
	outer_orbit: number | null;
}

export interface PlanetIndexFile {
	token: string;
	hosts: PlanetIndexHost[];
	/** `"{host}/{n}"` of an alias number → the live planet `[host, n]` it
	 *  leads to, which the index lists. The two hosts can differ. */
	aliases: Record<string, [number, number]>;
}

export interface PlanetCrossId {
	catalogue: string;
	release: string;
	catalogue_id: string;
}

export interface PlanetHost {
	id: number;
	name: string | null;
	name_source: string | null;
	class: string | null;
	cross_ids: PlanetCrossId[];
	planets: number[];
	/** How the render tree knows its distance: `parallax`, the
	 *  `distance_source` of its distance group (as `literature`), `catalogue
	 *  distance`, `parallax with fidelity under 0.5`; null when it is not drawn. */
	placement: string | null;
	position: [number, number, number] | null;
	distance: number | null;
	ra: number | null;
	dec: number | null;
	epoch: number | null;
	teff: number | null;
	teff_source: string | null;
	radius: number | null;
	radius_source: string | null;
	mass: number | null;
	metallicity: number | null;
	spectral_type: string | null;
	bp_rp: number | null;
	catalogue: string | null;
	catalogue_name: string | null;
}

export interface Planet {
	host: number;
	number: number;
	name: string;
	name_source: string | null;
	designation: string | null;
	letter: string | null;
	aliases: string[];
	cross_ids: PlanetCrossId[];
	class: string | null;
	class_basis: string | null;
	mass_ratio: number | null;
	status: string | null;
	/** Null when the planet has no semi-major axis: it has no orbit to draw. */
	elements: PlanetElements | null;
	values: Record<string, number | string | string[] | null>;
	sources: Record<string, string>;
	assumed: string[];
	estimated: string[];
	computed: string[];
	limits: string[];
}

export interface PlanetSystem {
	token: string;
	/** ID of the key star. */
	system: number;
	/** The key star first, then the other hosts by ID. */
	hosts: PlanetHost[];
	/** By host, then number. */
	planets: Planet[];
}

/** The planet index, by host ID. */
export class PlanetIndex {
	readonly hosts: ReadonlyMap<number, PlanetIndexHost>;
	private readonly bySystem = new Map<number, number[]>();

	constructor(readonly file: PlanetIndexFile) {
		this.hosts = new Map(file.hosts.map((h) => [h.id, h]));
		for (const h of file.hosts) this.bySystem.set(h.system, [...this.hostsOf(h.system), h.id]);
	}

	host(id: number): PlanetIndexHost | undefined {
		return this.hosts.get(id);
	}

	/** The hosts of the system file `key`, by ID. */
	hostsOf(key: number): readonly number[] {
		return this.bySystem.get(key) ?? [];
	}

	/** The live planet of the page `/x/{host}/b/{n}`: itself, or the one its
	 *  alias leads to, maybe on another host. Null for a page that is a 404. */
	live(host: number, n: number): { host: number; n: number } | null {
		const target = this.file.aliases[`${host}/${n}`];
		if (target) return { host: target[0], n: target[1] };
		return this.hosts.get(host)?.planets.includes(n) ? { host, n } : null;
	}
}

/** Where the planet files are read. */
export interface PlanetSource {
	metadata(): Promise<ExtrasolarMetadata | null>;
	/** A file, decoded, its token checked against `token`. */
	json<T extends { token: string }>(path: string, token: string): Promise<T>;
	allowed(entry: { distribution?: string }): boolean;
}

const DEFAULT_SYSTEMS = 32;

/**
 * The index, loaded once, and the system files in a small LRU. Null where the
 * host serves no planets or may not show them. A failed load is not kept.
 */
export class PlanetCatalogue {
	private indexLoad: Promise<PlanetIndex | null> | null = null;
	private readonly systems: LruPromiseCache<PlanetSystem>;

	constructor(
		private readonly source: PlanetSource,
		systems = DEFAULT_SYSTEMS
	) {
		this.systems = new LruPromiseCache(systems);
	}

	index(): Promise<PlanetIndex | null> {
		if (this.indexLoad) return this.indexLoad;
		const p = (async () => {
			const planets = (await this.source.metadata())?.planets;
			if (!planets || !this.source.allowed(planets)) return null;
			const file = await this.source.json<PlanetIndexFile>(planets.index, planets.token);
			return new PlanetIndex(file);
		})();
		this.indexLoad = p;
		p.catch(() => {
			if (this.indexLoad === p) this.indexLoad = null;
		});
		return p;
	}

	/** The system file of the star `host`; null when it has no planets. */
	async hostSystem(host: number): Promise<PlanetSystem | null> {
		const entry = (await this.index())?.host(host);
		return entry ? this.system(entry.system) : null;
	}

	/** The live planet of the page `/x/{host}/b/{n}` and its system file: the
	 *  planet itself, or the one its alias leads to, which can be on another
	 *  host. Its `host` and `number` are the live ones. Null for a 404. */
	async planet(host: number, n: number): Promise<{ planet: Planet; system: PlanetSystem } | null> {
		const index = await this.index();
		const live = index?.live(host, n) ?? null;
		if (live === null) return null;
		const entry = index!.host(live.host);
		if (!entry)
			throw new Error(`[planets] ${host}/b/${n} leads to host ${live.host}, not in the index`);
		const system = await this.system(entry.system);
		const planet = system.planets.find((p) => p.host === live.host && p.number === live.n);
		if (!planet) {
			throw new Error(`[planets] ${live.host}/b/${live.n} is not in system ${system.system}`);
		}
		return { planet, system };
	}

	/** The system file keyed by the star `key`. */
	system(key: number): Promise<PlanetSystem> {
		return this.systems.getOrCompute(String(key), async () => {
			const planets = (await this.source.metadata())?.planets;
			if (!planets || !this.source.allowed(planets)) {
				throw new Error(`[planets] no planet files for system ${key}`);
			}
			return this.source.json<PlanetSystem>(extrasolarPath(planets.system, { key }), planets.token);
		});
	}
}

export const planetCatalogue = new PlanetCatalogue({
	metadata: fetchExtrasolarMetadata,
	json: fetchExtrasolarJson,
	allowed: extrasolarAllowed
});
