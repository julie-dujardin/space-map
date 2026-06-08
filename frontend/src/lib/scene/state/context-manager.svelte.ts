import type { PositionedBody } from '$lib/types/objects';
import { CreditsStore } from '$lib/scene/state/credits.svelte';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { VisibilityController } from '$lib/scene/visibility/controller.svelte';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import type { ProbeCoverage } from '$lib/fetch/metadata';
import type { ZoneRefresher } from '$lib/scene/zone-refresher';
import { loadScene } from '$lib/scene/setup/scene-load';
import { fetchEarthGroupMembers } from '$lib/fetch/groups/membership';
import { CLASS_SLUG_PREFIX, fetchGroupIndex } from '$lib/fetch/groups/registry';
import { EARTH_ID } from '$lib/constants';

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
		() => this.earthSatFilter
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
	/**
	 * Per-probe `(start_jd, end_jd)` from `metadata.position.probe_coverage`.
	 * Empty map when the export ships no probes; null when the metadata
	 * predates the field (legacy exports). Drives the focused-probe
	 * coverage-end pause; the renderer reads it once at scene-build time.
	 */
	probeCoverage: Map<string, ProbeCoverage> | null = null;

	/** Hot-reload driver for time-segmented (Earth SGP4 sats) and chunk-indexed
	 *  (moons Method-C secular elements) zones. Set at the end of {@link loadScene}
	 *  once the loader and metadata are available. */
	refresher: ZoneRefresher | null = null;

	/** Intersect earth-zone chunks with this set before adding bodies so
	 *  /g/<slug> pages render only group members. */
	earthSatFilter: Set<string> | null = null;
	private earthSatFilterSlug: string | null = null;
	/** Orbit-class name (e.g. "MBA") when /g/class-<NAME> is active; null
	 *  otherwise. Read by `planMinorChunks` to skip non-matching
	 *  `small_bodies/*` zones at fetch time. */
	smallBodyClassFilter: string | null = null;
	private currentGroupSlug: string | null = null;
	/** Notified after `earthSatFilter` is set (post-fetch). Used by the
	 *  promotion registry + pointclouds to ramp emphasis and bulk-promote
	 *  members when the count is small. */
	private readonly groupFilterListeners = new Set<(filter: ReadonlySet<string> | null) => void>();

	/** Subscribe to filter changes. The callback fires on each `applyGroupFilter`
	 *  completion. Returns an unsubscribe. */
	onGroupFilterChange(cb: (filter: ReadonlySet<string> | null) => void): () => void {
		this.groupFilterListeners.add(cb);
		return () => this.groupFilterListeners.delete(cb);
	}

	/** Look up any body by ID. Carve-out delegate — see {@link BodyIndex.getBody}. */
	getBody(id: string, zone?: string): PositionedBody | undefined {
		return this.bodies.getBody(id, zone);
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

	/** Install or remove the active group filter. Branches on the slug's
	 *  ``applies_to`` (resolved from the group index). Safe to call before
	 *  {@link load} — the first chunk pass picks the filter up. Mid-session
	 *  transitions in or out of a small-body filter reload the page; the
	 *  asteroid zone state isn't surgically evictable. */
	async applyGroupFilter(slug: string | null): Promise<void> {
		if (slug === this.currentGroupSlug) return;
		this.currentGroupSlug = slug;
		const category = slug ? await this.resolveCategory(slug) : null;
		if (slug !== this.currentGroupSlug) return;

		const nextSmallBody = category === 'small_body' ? slug!.slice(CLASS_SLUG_PREFIX.length) : null;
		const smallBodyChange = nextSmallBody !== this.smallBodyClassFilter;
		this.smallBodyClassFilter = nextSmallBody;

		if (nextSmallBody !== null) {
			// Earth filter is mutually exclusive with small-body filter.
			this.earthSatFilter = null;
			this.earthSatFilterSlug = null;
			if (!this.loading && smallBodyChange) window.location.reload();
			return;
		}

		if (smallBodyChange && !this.loading) {
			// Leaving small-body mode: need a full re-fetch of small_bodies/* zones.
			window.location.reload();
			return;
		}

		const filter = slug ? await fetchEarthGroupMembers(slug) : null;
		if (slug !== this.currentGroupSlug) return;
		this.earthSatFilter = filter;
		this.earthSatFilterSlug = slug;
		for (const cb of this.groupFilterListeners) cb(filter);
		if (this.loading) return;
		this.bodies.spacecraftByParent.delete(EARTH_ID);
		this.bodies.dirtySpacecraftGroups.add(EARTH_ID);
		this.bodies.minorBodyVersion++;
		this.refresher?.invalidateZone('earth');
	}

	private async resolveCategory(slug: string): Promise<string | null> {
		try {
			const index = await fetchGroupIndex();
			return index[slug]?.applies_to ?? null;
		} catch {
			return null;
		}
	}
}
