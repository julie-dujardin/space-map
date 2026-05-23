import type { CanvasTexture, Mesh, Scene, WebGLRenderer } from 'three';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { fetchLabels } from '$lib/fetch/position/labels';
import { MINOR_PROMOTED_IDS } from '$lib/constants';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import type { SimClock } from '$lib/scene/clock.svelte';
import { buildMajorBodies, buildOrbitLines, loadBodyLabel } from '$lib/scene/objects/construction';
import { refreshMinorBodyPosition } from '$lib/scene/minor-body-position';
import type { PointCloudSystem } from '$lib/scene/pointclouds/system';

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
	/** Called to assign MAP_LAYER to newly-built orbit lines. */
	assignMapLayerToOrbitLines: () => void;
	/** Called to refresh all object positions after a new body is built. */
	repositionAll: () => void;
	/** Returns the focused body id (excluded from clear / count) — null if no focus. */
	getFocusedId: () => string | undefined;
	/** Optional callback fired when the clearable user-promoted count changes. */
	onUserPromotedChange?: (count: number) => void;
}

/**
 * Tracks the "default-important" set (curated body ids that auto-promote from
 * point-cloud dots to full meshes on load) and the "user-promoted" set
 * (click/URL-promoted bodies that can be reverted in one shot). Owns the
 * promote/teardown lifecycle for both.
 */
export class PromotionRegistry {
	/** Bodies queued for auto-promotion — drained one per frame in {@link drainOneAutoPromote}. */
	private readonly pendingDefaults = new Set<string>();
	/** Stable curated set: labels-file keys ∪ MINOR_PROMOTED_IDS. Never drained. */
	private readonly defaults = new Set<string>();
	/** Click/URL-promoted bodies (not in the curated set). */
	private readonly userPromoted = new Set<string>();

	constructor(private readonly deps: PromotionDeps) {
		// Promoted set = keys of the global per-language labels file. Fire-and-
		// forget: drainOneAutoPromote is a no-op until labels resolve a few
		// hundred ms later.
		void fetchLabels().then((labels) => {
			for (const id of labels.keys()) {
				this.pendingDefaults.add(id);
				this.defaults.add(id);
			}
			// Minor-promoted bodies still need a halo. They may or may not be
			// in the labels file (cheb-covered ones are); add idempotently.
			for (const id of MINOR_PROMOTED_IDS) {
				this.pendingDefaults.add(id);
				this.defaults.add(id);
			}
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

	isDefault(id: string): boolean {
		return this.defaults.has(id);
	}

	/** Build mesh, label, halo, and orbit line for a body that only existed as a point-cloud dot. */
	ensureBodyObjects(body: PositionedBody): void {
		const { bodyObjects, ctx, clock, scene, clickables, meshToBody, circleTexture, renderer } =
			this.deps;
		if (bodyObjects.has(body.data.id)) return;
		// Point-cloud bodies aren't touched by updatePositions — their CPU
		// position is frozen at load. Refresh before building so the mesh,
		// halo, and orbit line spawn at the current jd instead of jumping
		// on the next tick.
		refreshMinorBodyPosition(body, clock.jd, ctx);
		// Minor bodies from chunks lack orbitElements; populate from data so
		// orbit lines can be built. Skip probes: their `body.data` carries
		// a=e=…=0 (positions come from per-sub-chunk dispatch), and assigning
		// those zeros to `orbitElements` defeats the SPICE_PROBE guard in
		// ObjectDrawer — currentStateFromElements would warn every frame.
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
				hovered ? this.deps.hoveredBodyIds.add(id) : this.deps.hoveredBodyIds.delete(id)
		);
		buildOrbitLines(bodyObjects, scene, this.deps.pointClouds.basis(), clock.jd);
		this.deps.assignMapLayerToOrbitLines();
		this.deps.repositionAll();

		// Click-promoted minor bodies enter unnamed (global labels file only
		// carries the curated set). Fire-and-forget the detail bundle fetch
		// so the label fills in once Wikidata arrives.
		const bo = bodyObjects.get(body.data.id);
		if (bo && !body.data.name) loadBodyLabel(bo);

		// Rebuild the body's point-cloud group so its dot disappears.
		if (body.data.objectType === ObjectType.SPACECRAFT) {
			ctx.dirtySpacecraftGroups.add(body.data.parentId);
		} else if (isAsteroid(body.data.objectType) || body.data.objectType === ObjectType.COMET) {
			for (const [zone, byId] of ctx.asteroidBodiesByZone) {
				if (byId.has(body.data.id)) {
					ctx.dirtyAsteroidZones.add(zone);
					break;
				}
			}
		}
		this.deps.pointClouds.rebuildMinor();

		// Track click/URL-promoted bodies so the user can revert them via clearUserPromoted.
		if (!this.defaults.has(body.data.id)) {
			this.userPromoted.add(body.data.id);
			this.emitUserPromotedCount();
		}
	}

	/** Tear down every user-promoted body except the focused one, reverting them to point-cloud dots. */
	clearUserPromoted(): void {
		const { bodyObjects, ctx, scene, clickables, meshToBody, pointClouds } = this.deps;
		const focusedId = this.deps.getFocusedId();
		const dirtySpacecraftParents = new Set<string>();
		const dirtyAsteroidZones = new Set<string>();

		for (const id of [...this.userPromoted]) {
			if (id === focusedId) continue;
			const bo = bodyObjects.get(id);
			if (!bo) {
				this.userPromoted.delete(id);
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
			if (bo.orbitLine) scene.remove(bo.orbitLine);

			if (bo.mesh) {
				bo.mesh.geometry.dispose();
				const mat = bo.mesh.material;
				if (Array.isArray(mat)) for (const m of mat) m.dispose();
				else mat.dispose();
				const idx = clickables.indexOf(bo.mesh);
				if (idx >= 0) clickables.splice(idx, 1);
				meshToBody.delete(bo.mesh);
			}
			if (bo.orbitLine) {
				bo.orbitLine.geometry.dispose();
				const mat = bo.orbitLine.material;
				if (Array.isArray(mat)) for (const m of mat) m.dispose();
				else mat.dispose();
			}

			// Mark the body's point-cloud group dirty so the dot reappears.
			const objectType = bo.body.data.objectType;
			if (objectType === ObjectType.SPACECRAFT) {
				dirtySpacecraftParents.add(bo.body.data.parentId);
			} else if (isAsteroid(objectType) || objectType === ObjectType.COMET) {
				for (const [zone, byId] of ctx.asteroidBodiesByZone) {
					if (byId.has(id)) {
						dirtyAsteroidZones.add(zone);
						break;
					}
				}
			}

			bodyObjects.delete(id);
			this.userPromoted.delete(id);
		}

		for (const p of dirtySpacecraftParents) ctx.dirtySpacecraftGroups.add(p);
		for (const z of dirtyAsteroidZones) ctx.dirtyAsteroidZones.add(z);
		if (dirtySpacecraftParents.size > 0 || dirtyAsteroidZones.size > 0) {
			pointClouds.rebuildMinor();
		}

		this.emitUserPromotedCount();
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

	/** Drain one auto-promote candidate per frame to spread GPU work. */
	drainOneAutoPromote(): void {
		if (this.pendingDefaults.size === 0) return;
		const { bodyObjects, ctx } = this.deps;
		for (const id of this.pendingDefaults) {
			if (bodyObjects.has(id)) {
				this.pendingDefaults.delete(id);
				continue;
			}
			const body = ctx.getBody(id);
			if (!body) continue; // not loaded yet — retry on a later frame
			this.pendingDefaults.delete(id);
			// Barycenters and Lagrange points share the labels file with promoted
			// bodies (their names are needed for URL navigation), but they aren't
			// shown by default — except those listed in MINOR_PROMOTED_IDS, which
			// render as collapsed halos so the user sees the SSB / Pluto-Charon offset.
			if (
				(body.data.objectType === ObjectType.BARYCENTER ||
					body.data.objectType === ObjectType.LAGRANGE_POINT) &&
				!MINOR_PROMOTED_IDS.has(id)
			)
				continue;
			// Asteroids, comets, and probes auto-promote to a halo + label only
			// (no sphere mesh, no orbit line) via buildMajorBodies's isHaloOnly
			// branch. Full-mesh upgrade on focus is a follow-up.
			this.ensureBodyObjects(body);
			break; // one per frame
		}
	}
}
