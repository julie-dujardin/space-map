import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { CreditsStore } from '$lib/scene/state/credits.svelte';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { VisibilityController } from '$lib/scene/visibility/controller.svelte';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import type { ZoneRefresher } from '$lib/scene/zone-refresher';
import { loadScene } from '$lib/scene/setup/scene-load';
import { fetchEarthGroupMembers } from '$lib/fetch/groups/membership';
import { fetchGroupDetail } from '$lib/fetch/groups/details';
import {
	CAT_ASTEROIDS,
	CAT_COMETS,
	CAT_DEBRIS,
	CAT_SATELLITES,
	CLASS_SLUG_PREFIX,
	MISSION_SLUG_PREFIX,
	SMALL_BODY_FLAG_MASK,
	SMALL_BODY_FLAG_SLUG_PREFIX,
	fetchGroupIndex,
	smallBodyCategory,
	smallBodyFiltersEqual,
	type GroupCategory,
	type SmallBodyFilter,
	type SmallBodyFlagName
} from '$lib/fetch/groups/registry';
import { EARTH_ID } from '$lib/constants';
import { isLagrangeClass } from '$lib/math/orbit/lagrange';

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

	/** Focus state + per-frame visibility decisions, read by `visibility/update.ts`
	 *  to apply VISIBILITY values to Three.js objects. */
	visibility = new VisibilityController(
		this.bodies,
		() => this.probeStore,
		() => this.earthSatFilter,
		() => this.smallBodyFilter
	);

	loading = $state(true);
	error = $state<string | null>(null);

	/** Set by MapPage; fired when data looks stale mid-session so it can prompt a reload. */
	onDataStale: (() => void) | null = null;

	constructor() {
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
	private currentGroupSlug: string | null = null;
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
		if (f === null) return false;
		if (f.kind === 'class' || f.kind === 'category') {
			const zone = this.bodies.findAsteroidZone(bodyId);
			if (zone?.startsWith('small_bodies/') !== true) return false;
			const className = zone.slice('small_bodies/'.length);
			return f.kind === 'class'
				? className === f.className
				: smallBodyCategory(className) === f.category;
		}
		const body = this.bodies.getBody(bodyId);
		return ((body?.data.flags ?? 0) & f.mask) === f.mask;
	}

	async load(date: Date, targetId?: string): Promise<void> {
		try {
			await loadScene(this, date, targetId);
		} catch (e) {
			this.loading = false;
			// Surface it so MapPage's error screen renders instead of a black scene.
			this.error = e instanceof Error ? e.message : String(e);
			console.error('[scene-load]', e);
			throw e;
		}
	}

	/** Per-frame hook, called when sim jd advances, driving hot-reload of
	 *  time-segmented and chunk-indexed zones. */
	refreshTick(date: Date): void {
		this.refresher?.tick(date);
	}

	/** Stream an out-of-view target into the running scene on demand (no reload).
	 *  No-op before {@link load} sets the refresher, or if already loaded. */
	async ensureBody(targetId: string, date: Date): Promise<void> {
		await this.refresher?.ensureBody(targetId, date);
	}

	/** Install or remove the active group filter, branching on the slug's
	 *  `applies_to`. Safe to call before {@link load}. Small-body filter is a
	 *  render-time mask ({@link VisibilityController.isAsteroidGroupVisible});
	 *  Earth-sat filter is applied at chunk-fetch time, so changes trigger a
	 *  zone invalidation + refetch. */
	async applyGroupFilter(slug: string | null): Promise<void> {
		if (slug === this.currentGroupSlug) return;
		this.currentGroupSlug = slug;

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

		const entry = slug ? await this.resolveIndexEntry(slug) : null;
		if (slug !== this.currentGroupSlug) return;

		const nextSmallBody = this.resolveSmallBodyFilter(slug, entry?.applies_to, entry?.n);
		// SGP4 can't place TLE sats at an L-point, so filtering would just empty
		// the scene — leave Lagrange zones unfiltered until membership is geometric.
		const isLagrange =
			slug != null &&
			slug.startsWith(CLASS_SLUG_PREFIX) &&
			isLagrangeClass(slug.slice(CLASS_SLUG_PREFIX.length));
		const nextEarthSlug = entry?.applies_to === 'earth_sat' && !isLagrange ? slug : null;
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

	private async resolveIndexEntry(slug: string) {
		try {
			const index = await fetchGroupIndex();
			return index[slug] ?? null;
		} catch {
			return null;
		}
	}
}
