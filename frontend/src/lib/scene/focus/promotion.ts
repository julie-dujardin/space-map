import type { CanvasTexture, Mesh, Scene, WebGLRenderer } from 'three';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { fetchLabels } from '$lib/fetch/position/labels';
import { EARTH_ID, MINOR_PROMOTED_IDS } from '$lib/constants';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { buildMajorBodies, disposeMaterial } from '$lib/scene/objects/body/lifecycle';
import { buildTrails } from '$lib/scene/objects/body/bulk';
import { loadBodyLabel } from '$lib/scene/objects/body/textures';
import { refreshMinorBodyPosition } from '$lib/scene/minor-body-position';
import type { PointCloudSystem } from '$lib/scene/pointclouds/system';

/** Group focus shrinks the cloud and promotes its members for visibility:
 *  `half` (<50 currently-visible members) renders each as a halo-only minor
 *  body; `full` (<20) builds the full sphere + trail. `none` keeps everything
 *  as point-cloud dots. Threshold counts use the bodies currently observable
 *  at sim jd, not the group's total membership — so a 1000-member launch site
 *  whose first sat hasn't launched yet starts in `full` and ramps down. */
export type GroupPromotionMode = 'none' | 'half' | 'full';

const GROUP_HALF_PROMOTE_THRESHOLD = 50;
const GROUP_FULL_PROMOTE_THRESHOLD = 20;

function computeGroupMode(count: number): GroupPromotionMode {
	if (count <= 0) return 'none';
	if (count < GROUP_FULL_PROMOTE_THRESHOLD) return 'full';
	if (count < GROUP_HALF_PROMOTE_THRESHOLD) return 'half';
	return 'none';
}

function isCurrentlyValid(body: PositionedBody, jd: number): boolean {
	return body.data.validityStart <= jd && jd <= body.data.validityEnd;
}

export interface PromotionDeps {
	scene: Scene;
	bodyObjects: Map<string, BodyObjects>;
	ctx: ContextManager;
	clock: SimClock;
	renderer: WebGLRenderer;
	circleTexture: CanvasTexture;
	clickables: Mesh[];
	meshToBody: Map<Mesh, PositionedBody>;
	hoveredBodyIds: Set<string>;
	pointClouds: PointCloudSystem;
	/** Called when the user clicks a body's mesh — wired into buildMajorBodies. */
	onBodyClick: (body: PositionedBody) => void;
	/** Called to assign MAP_LAYER to newly-built trails. */
	assignMapLayerToTrails: () => void;
	/** Called to refresh all object positions after a new body is built. */
	repositionAll: () => void;
	/** Returns the focused body id (excluded from clear / count) — null if no focus. */
	getFocusedId: () => string | undefined;
	/** Optional callback fired when the clearable user-promoted count changes. */
	onUserPromotedChange?: (count: number) => void;
}

/**
 * Tracks the "default-important" set (curated body ids that auto-promote from
 * point-cloud dots to full meshes on load), the "user-promoted" set
 * (click/URL-promoted bodies that can be reverted in one shot), and the
 * "group-promoted" set (members of the focused /g/<slug> group, auto-built at
 * <50 members and torn down when the filter changes). Owns the promote/teardown
 * lifecycle for all three.
 */
export class PromotionRegistry {
	/** Curated ids waiting for their body to arrive — promoted directly when
	 *  {@link onBodiesAdded} fires for a matching id. */
	private readonly pendingDefaults = new Set<string>();
	/** Stable curated set: labels-file keys ∪ MINOR_PROMOTED_IDS. */
	private readonly defaults = new Set<string>();
	/** Click/URL-promoted bodies (not in the curated set). */
	private readonly userPromoted = new Set<string>();
	/** Members of the focused group that we've built. Torn down on filter
	 *  change. Stays disjoint from `userPromoted` so `clearUserPromoted` leaves
	 *  them alone. */
	private readonly groupPromoted = new Set<string>();
	private groupTargets: ReadonlySet<string> | null = null;
	private groupMode: GroupPromotionMode = 'none';
	/** Full zone key (`small_bodies/<class>`) tracked for emphasis count
	 *  re-evaluation as chunks land. Null when no class filter is active. */
	private smallBodyZone: string | null = null;

	constructor(private readonly deps: PromotionDeps) {
		deps.ctx.bodies.onBodiesAdded((ids) => {
			this.onBodiesAdded(ids);
			this.autoPromoteAsteroidMoons(ids);
			this.onBodiesAddedGroup();
			if (this.smallBodyZone !== null) this.refreshSmallBodyEmphasis();
		});
		// URL-loaded placeholders flushed before this registry was wired up
		// don't fire the live `onBodiesAdded` listener — sweep them now.
		this.promoteExistingAsteroidMoons();
		// Group filter is applied in MapPage.onMount *before* the scene loads —
		// by the time we exist, the filter may already be set, so seed from the
		// current value rather than waiting for the next change event.
		deps.ctx.onGroupFilterChange((filter) => this.applyGroupFilter(filter));
		this.applyGroupFilter(deps.ctx.earthSatFilter);
		deps.ctx.onSmallBodyClassFilterChange((cls) => this.applySmallBodyClassFilter(cls));
		this.applySmallBodyClassFilter(deps.ctx.smallBodyClassFilter);
		// Curated set = labels-file keys ∪ MINOR_PROMOTED_IDS. Fire-and-forget:
		// until labels resolve a few hundred ms later, defaults is empty so the
		// notification handler matches nothing.
		void fetchLabels().then((labels) => {
			const alreadyLoaded: PositionedBody[] = [];
			const add = (id: string) => {
				if (!this.defaults.add(id)) return;
				if (this.deps.bodyObjects.has(id)) return;
				const body = this.deps.ctx.getBody(id);
				if (!body) {
					this.pendingDefaults.add(id);
					return;
				}
				if (this.shouldAutoPromote(body, id)) alreadyLoaded.push(body);
			};
			for (const id of labels.keys()) add(id);
			// Minor-promoted bodies still need a halo. They may or may not be
			// in the labels file (cheb-covered ones are); add idempotently.
			for (const id of MINOR_PROMOTED_IDS) add(id);
			this.buildBatch(alreadyLoaded);
			// URL navigation that landed before labels resolved may have flagged
			// a curated body as user-promoted; reconcile now.
			let pruned = false;
			for (const id of this.userPromoted) {
				if (this.defaults.has(id)) {
					this.userPromoted.delete(id);
					pruned = true;
				}
			}
			if (pruned) this.emitUserPromotedCount();
		});
	}

	/** Moons whose parent is an asteroid land in `asteroidBodiesByZone` (point-cloud
	 *  bucket), not `bodiesById`, so the curated/labels-driven promotion path skips
	 *  them — they'd only get halos/trails after the user clicked. Auto-promote on
	 *  arrival so they show by default. Sparse in the catalog (handful of bodies).
	 *  Also promotes the parent asteroid when it's been pre-routed to `bodiesById`
	 *  (URL-loaded moon-of-asteroid: scene-load adds the host as a placeholder so
	 *  the moon's per-frame parent lookup resolves) — without this the host would
	 *  stay invisible while its moon renders. */
	private autoPromoteAsteroidMoons(ids: readonly string[]): void {
		const matched: PositionedBody[] = [];
		const seenParents = new Set<string>();
		for (const id of ids) {
			const body = this.deps.ctx.getBody(id);
			if (!body || body.data.objectType !== ObjectType.MOON) continue;
			const parent = this.deps.ctx.getBody(body.data.parentId);
			if (!parent || !isAsteroid(parent.data.objectType)) continue;
			// Parent first so it lands earlier in the `bodyObjects` insertion
			// order — the per-frame loop iterates in insertion order, so the
			// moon's parent lookup hits a freshly-computed position rather
			// than the previous frame's value.
			if (!this.deps.bodyObjects.has(parent.data.id) && !seenParents.has(parent.data.id)) {
				seenParents.add(parent.data.id);
				matched.push(parent);
			}
			if (!this.deps.bodyObjects.has(id)) matched.push(body);
		}
		this.buildBatch(matched);
	}

	/** Scan existing asteroid-moon buckets and promote any moon (+ parent)
	 *  already present at registry construction time. The `onBodiesAdded` hook
	 *  catches future arrivals, but URL-loaded placeholders are added in
	 *  `loadScene` *before* this registry exists, so the live hook misses
	 *  them. */
	private promoteExistingAsteroidMoons(): void {
		const moonBucket = this.deps.ctx.bodies.asteroidBodiesByZone.get('small_body_moons');
		if (!moonBucket || moonBucket.size === 0) return;
		this.autoPromoteAsteroidMoons(Array.from(moonBucket.keys()));
	}

	/** Notification hook from {@link BodyIndex}. Promotes any newly-arrived
	 *  curated bodies in a single batch (shared post-processing pass). */
	private onBodiesAdded(ids: readonly string[]): void {
		if (this.pendingDefaults.size === 0) return;
		const matched: PositionedBody[] = [];
		for (const id of ids) {
			if (!this.pendingDefaults.delete(id)) continue;
			const body = this.deps.ctx.getBody(id);
			if (body && this.shouldAutoPromote(body, id)) matched.push(body);
		}
		this.buildBatch(matched);
	}

	/** Barycenters and Lagrange points share the labels file with promoted
	 *  bodies (their names are needed for URL navigation), but they aren't
	 *  rendered by default — except those listed in MINOR_PROMOTED_IDS, which
	 *  render as collapsed halos so the user sees the SSB / Pluto-Charon offset. */
	private shouldAutoPromote(body: PositionedBody, id: string): boolean {
		if (
			body.data.objectType !== ObjectType.BARYCENTER &&
			body.data.objectType !== ObjectType.LAGRANGE_POINT
		)
			return true;
		return MINOR_PROMOTED_IDS.has(id);
	}

	isDefault(id: string): boolean {
		return this.defaults.has(id);
	}

	/** Build mesh, label, halo, and trail for a body that only existed as a point-cloud dot. */
	ensureBodyObjects(body: PositionedBody): void {
		if (!this.buildBodyInstance(body)) return;
		this.finalizeBuilds();
	}

	/** Build mesh, label, halo, and dirty markers for one body. Returns false
	 *  if the body was already promoted (caller can skip `finalizeBuilds`).
	 *  `halfPromoteIds`, when non-null, asks `buildMajorBodies` to render the
	 *  body as a halo-only minor entry — used for group half-promotion. */
	private buildBodyInstance(body: PositionedBody, halfPromoteIds?: ReadonlySet<string>): boolean {
		const { bodyObjects, ctx, clock, scene, clickables, meshToBody, circleTexture, renderer } =
			this.deps;
		if (bodyObjects.has(body.data.id)) return false;
		// Point-cloud bodies aren't touched by updatePositions — their CPU
		// position is frozen at load. Refresh before building so the mesh,
		// halo, and trail spawn at the current jd instead of jumping
		// on the next tick.
		refreshMinorBodyPosition(body, clock.jd, ctx);
		// Minor bodies from chunks lack orbitElements; populate from data so
		// trails can be built. Skip probes: their `body.data` carries
		// a=e=…=0 (positions come from per-sub-chunk dispatch), and assigning
		// those zeros to `orbitElements` defeats the SPICE_PROBE guard in
		// DetailDrawer — currentStateFromElements would warn every frame.
		if (!body.orbitElements && body.data.orbitalSource !== OrbitalSource.SPICE_PROBE) {
			body.orbitElements = body.data;
			const parent = bodyObjects.get(body.data.parentId);
			if (parent) body.orbitCenter = [...parent.body.position];
		}
		buildMajorBodies(
			[body],
			scene,
			clickables,
			meshToBody,
			bodyObjects,
			circleTexture,
			renderer.domElement,
			this.deps.onBodyClick,
			(id, hovered) =>
				hovered ? this.deps.hoveredBodyIds.add(id) : this.deps.hoveredBodyIds.delete(id),
			halfPromoteIds
		);
		// Click-promoted minor bodies start unnamed; fire-and-forget the bundle fetch.
		const bo = bodyObjects.get(body.data.id);
		if (bo && !body.data.name) loadBodyLabel(bo);
		// Mark the body's point-cloud group dirty so its dot disappears on the
		// next `rebuildMinor` pass.
		if (body.data.objectType === ObjectType.SPACECRAFT) {
			ctx.bodies.dirtySpacecraftGroups.add(body.data.parentId);
		} else if (isAsteroid(body.data.objectType) || body.data.objectType === ObjectType.COMET) {
			const zone = this.deps.ctx.bodies.findAsteroidZone(body.data.id);
			if (zone) ctx.bodies.dirtyAsteroidZones.add(zone);
		}
		const id = body.data.id;
		if (this.defaults.has(id)) {
			// Curated default — no extra tracking.
		} else if (this.groupTargets?.has(id)) {
			this.groupPromoted.add(id);
		} else {
			this.userPromoted.add(id);
			this.emitUserPromotedCount();
		}
		return true;
	}

	/** Global post-processing shared by all bodies built in a batch — trail
	 *  setup, layer/position resync, point-cloud rebuild. Walks every
	 *  bodyObject, so calling once per batch instead of once per body keeps
	 *  bulk promotions (curated asteroids landing in a single chunk) cheap. */
	private finalizeBuilds(): void {
		buildTrails(
			this.deps.bodyObjects,
			this.deps.scene,
			this.deps.pointClouds.basis(),
			this.deps.clock.jd
		);
		this.deps.assignMapLayerToTrails();
		this.deps.repositionAll();
		this.deps.pointClouds.rebuildMinor();
	}

	/** Build a batch of bodies with a single shared post-processing pass. */
	private buildBatch(bodies: Iterable<PositionedBody>, halfPromoteIds?: ReadonlySet<string>): void {
		let built = false;
		for (const body of bodies) {
			if (this.buildBodyInstance(body, halfPromoteIds)) built = true;
		}
		if (built) this.finalizeBuilds();
	}

	/** Filter change from `ctx.applyGroupFilter`: update targets, then re-evaluate
	 *  the mode against the current sim-time count. */
	private applyGroupFilter(filter: ReadonlySet<string> | null): void {
		this.groupTargets = filter;
		this.reevaluateGroupMode();
	}

	/** Small-body class focus: tell the point-cloud system which `small_bodies/<class>`
	 *  zone to emphasize, ramped against the bucket's body count (same thresholds
	 *  as earth-sat). No body-promotion side: asteroid clouds are dense enough
	 *  that the earth-style bulk-promote-on-small-count doesn't apply. */
	private applySmallBodyClassFilter(cls: string | null): void {
		this.smallBodyZone = cls ? `small_bodies/${cls}` : null;
		this.refreshSmallBodyEmphasis();
	}

	/** Recompute the emphasized zone's count from the current bucket and push it
	 *  to the point-cloud system. Called on filter change and whenever new
	 *  bodies land — chunk-time additions can move a class through the ramp
	 *  thresholds as more members arrive. */
	private refreshSmallBodyEmphasis(): void {
		const zone = this.smallBodyZone;
		if (zone === null) {
			this.deps.pointClouds.setEmphasizedSmallBodyZone(null, null);
			return;
		}
		const count = this.deps.ctx.bodies.asteroidBodiesByZone.get(zone)?.size ?? 0;
		this.deps.pointClouds.setEmphasizedSmallBodyZone(zone, count);
	}

	/** Chunk-flush hook: every time a new earth-zone segment lands (or any
	 *  bucket changes), recount currently-visible members and re-evaluate mode.
	 *  Most events are no-ops; the cost is `O(|spacecraftByParent[EARTH_ID]|)`
	 *  per call, fine at ~500ms cadence. */
	private onBodiesAddedGroup(): void {
		if (!this.groupTargets) return;
		this.reevaluateGroupMode();
	}

	/** Recompute count + mode and reconcile group-promoted bodies. Handles all
	 *  transitions: filter swap, mode flip (half↔full), expired members
	 *  (validity window ended), newly-arrived members. */
	private reevaluateGroupMode(): void {
		if (!this.groupTargets) {
			// Group cleared: drop everything we built for the group.
			this.teardownGroupPromoted(true);
			this.groupMode = 'none';
			this.deps.pointClouds.setEarthSatEmphasis(null);
			return;
		}
		const count = this.currentMemberCount();
		const newMode = computeGroupMode(count);
		this.deps.pointClouds.setEarthSatEmphasis(count);
		const modeChanged = newMode !== this.groupMode;
		this.teardownGroupPromoted(modeChanged);
		this.groupMode = newMode;
		if (newMode === 'none') return;

		// Promote currently-valid, currently-loaded targets that aren't yet built.
		const bucket = this.deps.ctx.bodies.spacecraftByParent.get(EARTH_ID);
		if (!bucket) return;
		const jd = this.deps.clock.jd;
		const matched: PositionedBody[] = [];
		for (const body of bucket.values()) {
			if (!this.groupTargets.has(body.data.id)) continue;
			if (!isCurrentlyValid(body, jd)) continue;
			if (this.deps.bodyObjects.has(body.data.id)) continue;
			matched.push(body);
		}
		if (matched.length === 0) return;
		this.buildBatch(matched, newMode === 'half' ? this.groupTargets : undefined);
	}

	/** Count members observable at the current sim jd. Walks the earth-sat
	 *  bucket (already filtered to group members at chunk-load time) and gates
	 *  each entry on its per-body `validityStart/validityEnd`. */
	private currentMemberCount(): number {
		if (!this.groupTargets) return 0;
		const bucket = this.deps.ctx.bodies.spacecraftByParent.get(EARTH_ID);
		if (!bucket) return 0;
		const jd = this.deps.clock.jd;
		let n = 0;
		for (const body of bucket.values()) {
			if (!this.groupTargets.has(body.data.id)) continue;
			if (isCurrentlyValid(body, jd)) n++;
		}
		return n;
	}

	/** Tear down group-promoted bodies that no longer belong: dropped from the
	 *  target set, validity expired, or `forceAll` (mode flip / group cleared).
	 *  Skips the focused body — ripping its mesh out mid-frame breaks the
	 *  focus pipeline. */
	private teardownGroupPromoted(forceAll: boolean): void {
		if (this.groupPromoted.size === 0) return;
		const focusedId = this.deps.getFocusedId();
		const jd = this.deps.clock.jd;
		const toRemove: string[] = [];
		for (const id of this.groupPromoted) {
			if (id === focusedId) continue;
			if (forceAll || !this.groupTargets?.has(id)) {
				toRemove.push(id);
				continue;
			}
			const body = this.deps.bodyObjects.get(id)?.body;
			if (body && !isCurrentlyValid(body, jd)) toRemove.push(id);
		}
		if (toRemove.length === 0) return;
		this.tearDownBodies(toRemove, this.groupPromoted);
	}

	/** Tear down every user-promoted body except the focused one, reverting them to point-cloud dots. */
	clearUserPromoted(): void {
		const focusedId = this.deps.getFocusedId();
		const toRemove = [...this.userPromoted].filter((id) => id !== focusedId);
		this.tearDownBodies(toRemove, this.userPromoted);
		this.emitUserPromotedCount();
	}

	/** Reverse a batch of promotions: remove their scene objects, dispose GPU
	 *  resources, and mark the parent point-cloud dirty so the dots reappear.
	 *  Caller is responsible for skipping the focused body and updating its own
	 *  bookkeeping (passed in as `tracker` so each entry is dropped together
	 *  with its scene objects). */
	private tearDownBodies(ids: string[], tracker: Set<string>): void {
		if (ids.length === 0) return;
		const { bodyObjects, ctx, scene, clickables, meshToBody, pointClouds } = this.deps;
		const dirtySpacecraftParents = new Set<string>();
		const dirtyAsteroidZones = new Set<string>();
		for (const id of ids) {
			const bo = bodyObjects.get(id);
			if (!bo) {
				tracker.delete(id);
				continue;
			}
			// CSS2DRenderer doesn't remove the DOM node when its object leaves
			// the scene graph, so it stays clickable in place. Detach manually.
			if (bo.label) {
				bo.label.element.remove();
				bo.label.removeFromParent();
			}
			scene.remove(bo.group);
			// Mesh + (for stars) corona/starPoint/etc. are added to scene directly.
			for (const obj of bo.extraObjects) scene.remove(obj);
			if (bo.trail) scene.remove(bo.trail);
			if (bo.mesh) {
				bo.mesh.geometry.dispose();
				disposeMaterial(bo.mesh.material);
				const idx = clickables.indexOf(bo.mesh);
				if (idx >= 0) clickables.splice(idx, 1);
				meshToBody.delete(bo.mesh);
			}
			if (bo.trail) {
				bo.trail.geometry.dispose();
				disposeMaterial(bo.trail.material);
			}
			const objectType = bo.body.data.objectType;
			if (objectType === ObjectType.SPACECRAFT) {
				dirtySpacecraftParents.add(bo.body.data.parentId);
			} else if (isAsteroid(objectType) || objectType === ObjectType.COMET) {
				const zone = this.deps.ctx.bodies.findAsteroidZone(id);
				if (zone) dirtyAsteroidZones.add(zone);
			}
			bodyObjects.delete(id);
			tracker.delete(id);
		}
		for (const p of dirtySpacecraftParents) ctx.bodies.dirtySpacecraftGroups.add(p);
		for (const z of dirtyAsteroidZones) ctx.bodies.dirtyAsteroidZones.add(z);
		if (dirtySpacecraftParents.size > 0 || dirtyAsteroidZones.size > 0) {
			pointClouds.rebuildMinor();
		}
	}

	/**
	 * Emit the clearable user-promoted count. The focused body is excluded —
	 * clearing it would leave the camera pointed at a torn-down mesh.
	 */
	emitUserPromotedCount(): void {
		if (!this.deps.onUserPromotedChange) return;
		const focusedId = this.deps.getFocusedId();
		let count = this.userPromoted.size;
		if (focusedId && this.userPromoted.has(focusedId)) count--;
		this.deps.onUserPromotedChange(count);
	}
}
