import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { CreditsStore } from '$lib/scene/state/credits.svelte';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import {
	ALL_PROBES,
	VisibilityController,
	type ProbePage
} from '$lib/scene/visibility/controller.svelte';
import { matchesSmallBodyFilter } from '$lib/scene/visibility/small-body-filter';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import type { ZoneRefresher } from '$lib/scene/zone-refresher';
import type { Placer } from '$lib/scene/position/placer';
import { loadScene } from '$lib/scene/setup/scene-load';
import { ensureExtrasolarBody } from '$lib/scene/setup/extrasolar';
import { ExoplanetStore } from '$lib/scene/exoplanets/store';
import { extrasolarIdOf, isExtrasolarObjectId, planetOfObjectId } from '$lib/fetch/extrasolar/ids';
import { fetchEarthGroupMembers } from '$lib/fetch/groups/membership';
import { fetchGroupDetail } from '$lib/fetch/groups/details';
import {
	CAT_ASTEROIDS,
	CAT_COMETS,
	CAT_DEBRIS,
	CAT_PROBES,
	CAT_SATELLITES,
	CLASS_SLUG_PREFIX,
	MISSION_SLUG_PREFIX,
	SMALL_BODY_FLAG_MASK,
	SMALL_BODY_FLAG_SLUG_PREFIX,
	fetchGroupIndex,
	smallBodyFiltersEqual,
	type GroupCategory,
	type SmallBodyFilter,
	type SmallBodyFlagName
} from '$lib/fetch/groups/registry';
import { LayerSet } from '$lib/scene/layers';
import { EARTH_ID } from '$lib/constants';

export type { SmallBodyFilter } from '$lib/fetch/groups/registry';

/** Earth-zone object types each category page keeps. Singletons so
 *  `applyGroupFilter` can compare them by identity. */
const EARTH_TYPES_BY_CATEGORY: Record<string, ReadonlySet<ObjectType>> = {
	[CAT_SATELLITES]: new Set([ObjectType.SPACECRAFT]),
	[CAT_DEBRIS]: new Set([ObjectType.DEBRIS])
};

/** Top-level state holder for the rendered scene: composes the bodies/credits/
 *  visibility sub-stores plus the loader-lifetime handles {@link loadScene}
 *  populates during `load()`. */
export class ContextManager {
	bodies = new BodyIndex();

	credits = new CreditsStore();

	/** The planetary systems of other stars that the scene holds. */
	exoplanets = new ExoplanetStore(this);

	/** Which layers this map draws, and which it never downloaded. The map
	 *  replaces it from its options before `load()`; this default draws
	 *  everything, which is what the app asks for. */
	layers = new LayerSet();

	/** Focus state + per-frame visibility decisions, read by `visibility/update.ts`
	 *  to apply VISIBILITY values to Three.js objects. */
	visibility = new VisibilityController(
		this.bodies,
		() => this.probeStore,
		() => this.earthSatFilter,
		() => this.smallBodyFilter,
		() => this.layers,
		() => this.earthTypeFilter,
		() => this.probePage
	);

	loading = $state(true);
	error = $state<string | null>(null);

	/** Set by MapPage; fired when data looks stale mid-session so it can prompt a reload. */
	onDataStale: (() => void) | null = null;

	/** The small bodies, the Earth satellites and the skybox wait for this:
	 *  none of them draw from another star. */
	readonly solarSystemShown: Promise<void>;
	/** Resolves {@link solarSystemShown}: when the map opens in the solar
	 *  system, or when the solar system first shows. */
	readonly showSolarSystem: () => void;

	constructor() {
		let show!: () => void;
		this.solarSystemShown = new Promise((resolve) => (show = resolve));
		this.showSolarSystem = show;
		// DEV-only console handle for inspecting live scene state.
		if (import.meta.env.DEV && typeof window !== 'undefined') {
			(window as unknown as { __sm: ContextManager }).__sm = this;
		}
	}

	/** Chebyshev ephemeris for SPICE-sourced major bodies. Null until metadata
	 *  resolves in {@link loadScene}, or if the export ships no chebyshev block. */
	chebStore: ChebyshevStore | null = null;
	/** Per-zone probe sub-chunks, consulted per-frame for bodies with
	 *  `orbitalSource === SPICE_PROBE`. Null until metadata resolves. */
	probeStore: ProbeStore | null = null;

	/** Hot-reload driver for time-segmented and chunk-indexed zones. Set at the
	 *  end of {@link loadScene}. */
	refresher: ZoneRefresher | null = null;

	/** Settles where bodies are. Set by the renderer, which owns the render
	 *  objects a placement updates. */
	placer: Placer | null = null;

	/** Renderer-set: true when `id` is promoted to a mesh body. Keeps the
	 *  zone-refresher from dropping the bucket entry a mesh still shares. */
	hasMeshBody: ((id: string) => boolean) | null = null;

	/** Intersect earth-zone chunks with this set so /g/<slug> pages render
	 *  only group members. */
	earthSatFilter: Set<string> | null = null;
	private earthSatFilterSlug: string | null = null;
	/** Keep only these object types in the earth zone (Satellites/Debris pages
	 *  partition by the per-point `objectType`, no membership fetch needed). */
	earthTypeFilter: ReadonlySet<ObjectType> | null = null;
	/** Active small-body filter for a /g/<slug> group; null otherwise. Read by
	 *  `VisibilityController` for the per-zone hide and per-tick flag mask. */
	smallBodyFilter: SmallBodyFilter | null = null;
	/** Member ids of the active mission group; lets the focus guard keep the
	 *  mission view sticky when the camera lands on the primary probe. */
	private missionMemberIds: Set<string> | null = null;
	/** The slug the filter is installed for, or being installed for. Undefined
	 *  after an install that failed: the scene then matches no slug. */
	private currentGroupSlug: string | null | undefined = null;
	/** The install of {@link currentGroupSlug}. */
	private groupFilterJob: Promise<void> = Promise.resolve();
	/** Notified after `earthSatFilter` is set. Ramps emphasis / bulk-promotes
	 *  members when the count is small. */
	private readonly groupFilterListeners = new Set<(filter: ReadonlySet<string> | null) => void>();
	/** Notified after `smallBodyFilter` changes; drives focused-zone point-cloud emphasis. */
	private readonly smallBodyFilterListeners = new Set<(f: SmallBodyFilter | null) => void>();
	/** Notified after an Earth-sat snapshot rollover — emphasis ramps off the
	 *  valid count, which shifts independent of membership, so it can't ride
	 *  `onBodiesAdded`. */
	private readonly earthSatRolloverListeners = new Set<() => void>();

	/** Subscribe to filter changes. The callback fires on each `applyGroupFilter`
	 *  completion. Returns an unsubscribe. */
	onGroupFilterChange(cb: (filter: ReadonlySet<string> | null) => void): () => void {
		this.groupFilterListeners.add(cb);
		return () => this.groupFilterListeners.delete(cb);
	}

	/** Subscribe to small-body filter changes. Callback fires synchronously
	 *  inside `applyGroupFilter` when the filter flips. Returns an unsubscribe. */
	onSmallBodyFilterChange(cb: (f: SmallBodyFilter | null) => void): () => void {
		this.smallBodyFilterListeners.add(cb);
		return () => this.smallBodyFilterListeners.delete(cb);
	}

	/** Subscribe to Earth-sat snapshot rollovers. Returns an unsubscribe. */
	onEarthSatRollover(cb: () => void): () => void {
		this.earthSatRolloverListeners.add(cb);
		return () => this.earthSatRolloverListeners.delete(cb);
	}

	/** Fired by {@link ZoneRefresher} after an Earth-sat snapshot rollover. */
	notifyEarthSatRollover(): void {
		for (const cb of this.earthSatRolloverListeners) cb();
	}

	/** Look up any body by ID. Carve-out delegate — see {@link BodyIndex.getBody}. */
	getBody(id: string, zone?: string): PositionedBody | undefined {
		return this.bodies.getBody(id, zone);
	}

	/** Place of `body` at `jd`. Null when it has none, and before the scene is up. */
	place(body: PositionedBody, jd: number): [number, number, number] | null {
		return this.placer?.place(body, jd) ?? null;
	}

	/** The probes the open group page is about, which a cleared sky leaves. */
	private get probePage(): ProbePage {
		return this.currentGroupSlug === CAT_PROBES ? ALL_PROBES : this.missionMemberIds;
	}

	/** True when an /g/<slug> view is active and the body belongs to it — keeps
	 *  the group view sticky when a member is clicked. */
	isMemberOfActiveGroup(bodyId: string): boolean {
		if (this.missionMemberIds?.has(bodyId) === true) return true;
		if (this.earthSatFilter?.has(bodyId) === true) return true;
		const types = this.earthTypeFilter;
		if (types) {
			const type = this.bodies.getBody(bodyId)?.data.objectType;
			if (type !== undefined && types.has(type)) return true;
		}
		const f = this.smallBodyFilter;
		// No small-body group active: nothing is a member through this path.
		if (f === null) return false;
		return matchesSmallBodyFilter(this.bodies, bodyId, f);
	}

	async load(date: Date, targetId?: string): Promise<void> {
		try {
			await loadScene(this, date, targetId);
		} catch (e) {
			this.fail(e);
			throw e;
		}
	}

	/** End the load on an error. Every way to open the scene ends here or in
	 *  `loading = false`: the page shows this, with a reload, in place of a
	 *  loading bar that never ends. */
	fail(e: unknown): void {
		this.loading = false;
		this.error = e instanceof Error ? e.message : String(e);
		console.error('[scene-load]', e);
	}

	/** Per-frame hook, called when sim jd advances, driving hot-reload of
	 *  time-segmented and chunk-indexed zones. */
	refreshTick(date: Date): void {
		// Only the Sun draws: no zone shows, so none loads.
		if (this.visibility.systemShare === 0) return;
		this.refresher?.tick(date);
	}

	/** Resolves when the scene holds its data for `date`. A navigation waits on
	 *  it before it reads a place. */
	async ready(date: Date): Promise<void> {
		await this.refresher?.ready(date);
	}

	/** Add an object the scene does not hold yet (no reload). One of the solar
	 *  system needs {@link ready} first. No-op before the first load phase ends,
	 *  or if it is here. */
	async ensureBody(targetId: string, date: Date): Promise<void> {
		if (isExtrasolarObjectId(targetId)) await this.ensureExtrasolar(targetId);
		else await this.refresher?.ensureBody(targetId, date);
	}

	/** Add an object of another star. It needs no data of the solar system, so
	 *  the first load phase can bring it too. */
	async ensureExtrasolar(targetId: string): Promise<void> {
		// A planet comes with its system and its host.
		if (planetOfObjectId(targetId)) {
			await this.exoplanets.ensurePlanet(targetId);
			return;
		}
		// A star is in no zone: its record places it. A star with planets brings
		// its planetary system, and a star in a star system brings that, so a link
		// can frame it.
		const host = extrasolarIdOf(targetId);
		const system =
			host === null
				? null
				: this.exoplanets.ensureHost(host).catch((e) => {
						console.warn(`[planets] the system of ${targetId} did not load:`, e);
					});
		const star = ensureExtrasolarBody(this, targetId).then((found) =>
			this.exoplanets.ensureStarSystemOf(found)
		);
		await Promise.all([star, system]);
	}

	/** Install or remove the active group filter, branching on the slug's
	 *  `applies_to`. Safe to call before {@link load}. Small-body filter is a
	 *  render-time mask ({@link VisibilityController.isAsteroidGroupVisible});
	 *  Earth-sat filter is applied at chunk-fetch time, so changes trigger a
	 *  zone invalidation + refetch.
	 *
	 *  Rejects when a file the filter is made from does not load. A call for
	 *  the same slug then starts over, and one made while the install runs
	 *  shares its outcome. */
	applyGroupFilter(slug: string | null): Promise<void> {
		if (slug === this.currentGroupSlug) return this.groupFilterJob;
		this.currentGroupSlug = slug;
		const job = this.installGroupFilter(slug);
		this.groupFilterJob = job;
		job.catch(() => {
			if (this.groupFilterJob === job) this.currentGroupSlug = undefined;
		});
		return job;
	}

	private async installGroupFilter(slug: string | null): Promise<void> {
		// Mission members are probes, not a streamed layer — no scene filter — but
		// the focus guard needs their ids to keep the mission view on a fly-to.
		if (slug?.startsWith(MISSION_SLUG_PREFIX)) {
			const detail = await fetchGroupDetail(slug);
			if (slug !== this.currentGroupSlug) return;
			this.missionMemberIds = new Set(
				(detail.global?.notable_members ?? []).map((mm) => mm.id).filter((id): id is string => !!id)
			);
		} else {
			this.missionMemberIds = null;
		}

		// A slug the index does not list filters nothing.
		const entry = slug ? ((await fetchGroupIndex())[slug] ?? null) : null;
		if (slug !== this.currentGroupSlug) return;

		const nextSmallBody = this.resolveSmallBodyFilter(slug, entry?.applies_to, entry?.n);
		const nextEarthSlug = entry?.applies_to === 'earth_sat' ? slug : null;
		const nextTypes = EARTH_TYPES_BY_CATEGORY[slug ?? ''] ?? null;
		if (!smallBodyFiltersEqual(this.smallBodyFilter, nextSmallBody)) {
			this.smallBodyFilter = nextSmallBody;
			for (const cb of this.smallBodyFilterListeners) cb(nextSmallBody);
		}

		// Sets are module-level singletons, so identity is the right comparison.
		if (nextEarthSlug === this.earthSatFilterSlug && nextTypes === this.earthTypeFilter) {
			return;
		}

		const filter = nextEarthSlug ? await fetchEarthGroupMembers(nextEarthSlug) : null;
		if (slug !== this.currentGroupSlug) return;
		this.earthSatFilter = filter;
		this.earthSatFilterSlug = nextEarthSlug;
		this.earthTypeFilter = nextTypes;
		for (const cb of this.groupFilterListeners) cb(filter);
		if (this.loading) return;
		this.bodies.spacecraftByParent.delete(EARTH_ID);
		this.bodies.dirtySpacecraftGroups.add(EARTH_ID);
		this.bodies.minorBodyVersion++;
		this.refresher?.invalidateZone('earth');
	}

	/** Asteroids/Comets pages hide the opposite bucket, like a class page hides
	 *  other classes. Other small-body slugs map to a class or flag filter;
	 *  everything else is unfiltered. */
	private resolveSmallBodyFilter(
		slug: string | null,
		appliesTo: GroupCategory | undefined,
		n: number | undefined
	): SmallBodyFilter | null {
		if (slug === CAT_ASTEROIDS) return { kind: 'category', category: 'asteroid' };
		if (slug === CAT_COMETS) return { kind: 'category', category: 'comet' };
		if (slug === null || appliesTo !== 'small_body') return null;
		if (slug.startsWith(CLASS_SLUG_PREFIX)) {
			return { kind: 'class', className: slug.slice(CLASS_SLUG_PREFIX.length) };
		}
		if (slug.startsWith(SMALL_BODY_FLAG_SLUG_PREFIX)) {
			const name = slug.slice(SMALL_BODY_FLAG_SLUG_PREFIX.length) as SmallBodyFlagName;
			const mask = SMALL_BODY_FLAG_MASK[name];
			if (mask === undefined) return null;
			return { kind: 'flag', flag: name, mask, n: n ?? 0 };
		}
		return null;
	}
}
