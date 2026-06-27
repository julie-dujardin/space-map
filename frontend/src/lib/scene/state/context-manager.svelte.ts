import type { PositionedBody } from '$lib/types/objects';
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

/**
 * Top-level state holder for the rendered scene. Composes four sub-stores —
 * bodies, credits, visibility, plus the loading/error reactive pair — and
 * holds the loader-lifetime handles (chebStore, probeStore, refresher) that
 * {@link loadScene} populates during `load()`.
 */
export class ContextManager {
	/** Body store: every loaded `PositionedBody`, parent/child graph, dirty
	 *  zone markers, and version counters for reactive consumers. */
	bodies = new BodyIndex();

	/** Attribution state: per-body imagery credits, skybox credit, orbit-source set. */
	credits = new CreditsStore();

	/** Focus state + per-frame visibility decisions. Reads body topology from
	 *  {@link BodyIndex}; the rendering side in `visibility/update.ts` reads
	 *  VISIBILITY values from here and applies them to Three.js objects. */
	visibility = new VisibilityController(
		this.bodies,
		() => this.probeStore,
		() => this.earthSatFilter,
		() => this.smallBodyFilter
	);

	loading = $state(true);
	error = $state<string | null>(null);

	/**
	 * Chebyshev polynomial ephemeris for SPICE-sourced major bodies. Null until
	 * the metadata.json fetch in {@link loadScene} resolves; stays null if the
	 * export ships no chebyshev block.
	 */
	chebStore: ChebyshevStore | null = null;
	/**
	 * Per-zone probe sub-chunks (Kepler-pure / Kepler-drift / Chebyshev). Null
	 * until metadata resolves; stays null when the export ships no probe
	 * zones. The renderer's per-frame update path consults it for any body
	 * whose `orbitalSource === SPICE_PROBE`.
	 */
	probeStore: ProbeStore | null = null;

	/** Hot-reload driver for time-segmented (Earth SGP4 sats) and chunk-indexed
	 *  (moons Method-C secular elements) zones. Set at the end of {@link loadScene}
	 *  once the loader and metadata are available. */
	refresher: ZoneRefresher | null = null;

	/** Intersect earth-zone chunks with this set before adding bodies so
	 *  /g/<slug> pages render only group members. */
	earthSatFilter: Set<string> | null = null;
	private earthSatFilterSlug: string | null = null;
	/** Active small-body filter (class or flag) when /g/<slug> is for a small-
	 *  body group; null otherwise. Read by `VisibilityController` for both the
	 *  per-zone hide and the per-tick flag mask. */
	smallBodyFilter: SmallBodyFilter | null = null;
	/** Member object-ids of the active mission group (primary probe + siblings);
	 *  null off a mission page. Lets the focus guard keep the mission view sticky
	 *  when the camera lands on the primary probe. */
	private missionMemberIds: Set<string> | null = null;
	private currentGroupSlug: string | null = null;
	/** Notified after `earthSatFilter` is set (post-fetch). Used by the
	 *  promotion registry + pointclouds to ramp emphasis and bulk-promote
	 *  members when the count is small. */
	private readonly groupFilterListeners = new Set<(filter: ReadonlySet<string> | null) => void>();
	/** Notified after `smallBodyFilter` changes (cheap — no fetch). Used to
	 *  drive the focused-zone point-cloud emphasis (class kind only). */
	private readonly smallBodyFilterListeners = new Set<(f: SmallBodyFilter | null) => void>();

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

	/** Look up any body by ID. Carve-out delegate — see {@link BodyIndex.getBody}. */
	getBody(id: string, zone?: string): PositionedBody | undefined {
		return this.bodies.getBody(id, zone);
	}

	/** True when an /g/<slug> view is active and the given body belongs to it.
	 *  Used by Scene.svelte's click handler to keep the group view sticky when
	 *  the user clicks a member — the camera moves, the URL stays. Earth-sat
	 *  members live in `earthSatFilter`; small-body class members match by
	 *  zone path; small-body flag members match by per-body `flags` bits. */
	isMemberOfActiveGroup(bodyId: string): boolean {
		if (this.missionMemberIds?.has(bodyId) === true) return true;
		if (this.earthSatFilter?.has(bodyId) === true) return true;
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
			throw e;
		}
	}

	/** Per-frame hook called by the renderer when sim jd advances. Drives
	 *  hot-reload of time-segmented zones (Earth SGP4 sats) and chunk-indexed
	 *  zones (moons Method-C-fit elements expire each chunk). */
	refreshTick(date: Date): void {
		this.refresher?.tick(date);
	}

	/** Stream an out-of-view target into the running scene on demand (no reload).
	 *  No-op before {@link load} sets the refresher, or if already loaded. */
	async ensureBody(targetId: string, date: Date): Promise<void> {
		await this.refresher?.ensureBody(targetId, date);
	}

	/** Install or remove the active group filter. Branches on the slug's
	 *  ``applies_to`` (resolved from the group index). Safe to call before
	 *  {@link load} — the first chunk pass picks the filter up.
	 *
	 *  Small-body filter is a render-time mask read by
	 *  {@link VisibilityController.isAsteroidGroupVisible}, so toggling it just
	 *  updates the field — the per-frame visibility pass picks it up. Earth-sat
	 *  filter is applied at chunk-fetch time, so changes trigger a zone
	 *  invalidation + refetch. */
	async applyGroupFilter(slug: string | null): Promise<void> {
		if (slug === this.currentGroupSlug) return;
		this.currentGroupSlug = slug;

		// Mission groups carry no scene filter — their members are probes, not a
		// streamed point layer — but the focus guard needs the member ids so the
		// camera can fly to the primary probe without dropping the mission view.
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
		// L1/L2 members are TLE earth-sats SGP4 can't place at an L-point, so
		// filtering the earth zone to them just empties the scene — don't hide
		// anything on these zones until live geometric membership lands.
		const isLagrange =
			slug != null &&
			slug.startsWith(CLASS_SLUG_PREFIX) &&
			isLagrangeClass(slug.slice(CLASS_SLUG_PREFIX.length));
		const nextEarthSlug = entry?.applies_to === 'earth_sat' && !isLagrange ? slug : null;
		if (!smallBodyFiltersEqual(this.smallBodyFilter, nextSmallBody)) {
			this.smallBodyFilter = nextSmallBody;
			for (const cb of this.smallBodyFilterListeners) cb(nextSmallBody);
		}

		if (nextEarthSlug === this.earthSatFilterSlug) return;

		const filter = nextEarthSlug ? await fetchEarthGroupMembers(nextEarthSlug) : null;
		if (slug !== this.currentGroupSlug) return;
		this.earthSatFilter = filter;
		this.earthSatFilterSlug = nextEarthSlug;
		for (const cb of this.groupFilterListeners) cb(filter);
		if (this.loading) return;
		this.bodies.spacecraftByParent.delete(EARTH_ID);
		this.bodies.dirtySpacecraftGroups.add(EARTH_ID);
		this.bodies.minorBodyVersion++;
		this.refresher?.invalidateZone('earth');
	}

	/** The Asteroids/Comets category pages hide the opposite bucket's zones, like
	 *  a class page hides every other class. Other small-body slugs map to a
	 *  class or flag filter; everything else (earth-orbit classes, other
	 *  categories) is left unfiltered. */
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
