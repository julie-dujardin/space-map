import { Vector3, type Mesh, type PerspectiveCamera, type Scene } from 'three';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { ObjectType, isSurfaceFeature, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { cartesianToSpherical, offsetFacing, sphericalToCartesian } from '$lib/math/spherical';
import type { BodyObjects, Callbacks } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import {
	downgradeBodyMesh,
	isMeshUpgradable,
	upgradeBodyMesh
} from '$lib/scene/objects/body/lifecycle';
import { isModelBearing, modelMinRadiusKm, unloadBodyModel } from '$lib/scene/objects/body/model';
import {
	disposeNomenclatureLabels,
	nomenclatureBodyId
} from '$lib/scene/objects/surface/nomenclature';
import { buildTrails } from '$lib/scene/objects/body/bulk';
import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
import { refreshMinorBodyPosition } from '$lib/scene/minor-body-position';
import {
	FOCUS_DURATION_MS,
	prepareFlyToCamera,
	prepareFocusTarget,
	type FocusState
} from '$lib/scene/animation/focus';
import { f64dist, type Vec3 } from '$lib/scene/animation/math';
import { getSettings } from '$lib/state/settings.svelte';
import type { PointCloudSystem } from '$lib/scene/pointclouds/system';
import type { SystemDataLoader } from '$lib/scene/system-data/loader';
import { PromotionRegistry, type PromotionDeps } from './promotion';

export interface FocusDeps {
	ctx: ContextManager;
	clock: SimClock;
	camera: PerspectiveCamera;
	controls: OrbitControls;
	scene: Scene;
	bodyObjects: Map<string, BodyObjects>;
	clickables: Mesh[];
	meshToBody: Map<Mesh, PositionedBody>;
	callbacks: Callbacks;
	focus: FocusState;
	pointClouds: PointCloudSystem;
	systemData: SystemDataLoader;
	/** Renderer-owned wrappers needed by setFocusTarget. */
	loadTexture: (body: PositionedBody) => void;
	repositionAll: () => void;
	assignMapLayerToTrails: () => void;
}

/** Owns the focused body, focus/fly animation parameters, and the URL-derived
 *  initial-view replay. Delegates promote/teardown to {@link PromotionRegistry}. */
export class FocusController {
	readonly promotion: PromotionRegistry;
	private focusedBody: PositionedBody | undefined;
	private readonly _tmpV3 = new Vector3();
	/** Initial lat/lon/zoom stashed until orientation loads and the camera can be
	 *  re-placed in body-fixed coords. Cleared once applied or once moved. */
	private pendingInitialView: { latitude: number; longitude: number; zoom: number } | null = null;
	/** Members of the last {@link syncUpgradeTargets} pass. */
	private upgradeTargetIds = new Set<string>();

	constructor(
		private readonly deps: FocusDeps,
		initialFocus: PositionedBody | undefined,
		hoveredBodyIds: Set<string>,
		circleTexture: PromotionDeps['circleTexture'],
		renderer: PromotionDeps['renderer']
	) {
		this.focusedBody = initialFocus;
		this.promotion = new PromotionRegistry({
			scene: deps.scene,
			bodyObjects: deps.bodyObjects,
			ctx: deps.ctx,
			clock: deps.clock,
			renderer,
			circleTexture,
			clickables: deps.clickables,
			meshToBody: deps.meshToBody,
			hoveredBodyIds,
			pointClouds: deps.pointClouds,
			onBodyClick: (b) => this.handleFocus(b),
			assignMapLayerToTrails: deps.assignMapLayerToTrails,
			repositionAll: deps.repositionAll,
			getFocusedId: () => this.focusedBody?.data.id,
			onUserPromotedChange: deps.callbacks.onUserPromotedChange
		});
	}

	get current(): PositionedBody | undefined {
		return this.focusedBody;
	}

	setPendingInitialView(view: { latitude: number; longitude: number; zoom: number }): void {
		this.pendingInitialView = view;
	}

	clearPendingInitialView(): void {
		this.pendingInitialView = null;
	}

	/** Quaternion for lat/lon framing around `body`; undefined for scene-frame.
	 *  Excludes spacecraft/probes — fast attitude spin (e.g. Juno) would tie
	 *  the view to rotation. */
	focusedBodyQuat(body?: PositionedBody): [number, number, number, number] | undefined {
		const b = body ?? this.focusedBody;
		if (!b || isModelBearing(b)) return undefined;
		const mesh = this.deps.bodyObjects.get(b.data.id)?.mesh;
		if (!mesh) return undefined;
		const q = mesh.quaternion;
		return [q.x, q.y, q.z, q.w];
	}

	/** Reconstruct camera world position in float64 (focus + scene-relative). */
	cameraTruePos(): Vec3 {
		const { focus, camera } = this.deps;
		return [
			focus.focusTruePos[0] + camera.position.x,
			focus.focusTruePos[1] + camera.position.y,
			focus.focusTruePos[2] + camera.position.z
		];
	}

	/**
	 * Single owner of focus-driven mesh upgrades. Computes the bodies the
	 * current focus needs upgraded ({@link upgradeTargets}: the focus itself, a
	 * moon's parent, a probe's fit center), downgrades `upgradeTargetIds`
	 * members that left the set, upgrades joiners, and loads non-focus
	 * joiners' textures/models. Bodies staying in the set are left untouched,
	 * so their resident texture/DEM/model survive focus switches within it
	 * (Bennu ↔ OSIRIS-REx). Called from initial focus,
	 * {@link setFocusTarget}, and the renderer when a focused probe's fit
	 * center flips mid-focus. Returns the new target ids.
	 */
	syncUpgradeTargets(body: PositionedBody): Set<string> {
		const {
			ctx,
			scene,
			clickables,
			meshToBody,
			bodyObjects,
			pointClouds,
			clock,
			loadTexture,
			assignMapLayerToTrails
		} = this.deps;
		const targets = upgradeTargets(body, ctx);
		const newIds = new Set(targets.map((t) => t.data.id));
		for (const id of this.upgradeTargetIds) {
			if (newIds.has(id)) continue;
			const bo = bodyObjects.get(id);
			if (!bo) continue;
			// Majors keep their own sphere + texture (system residency owns
			// those); only the overlay model is target-scoped.
			if (isMeshUpgradable(bo.body)) downgradeBodyMesh(bo, scene, clickables, meshToBody);
			else unloadBodyModel(bo);
		}
		let didUpgrade = false;
		for (const t of targets) {
			if (this.upgradeTargetIds.has(t.data.id)) continue;
			this.promotion.ensureBodyObjects(t);
			const tBo = bodyObjects.get(t.data.id);
			if (!tBo) {
				// Not buildable yet (still streaming): stay a non-member so the
				// next sync retries the join.
				newIds.delete(t.data.id);
				continue;
			}
			if (isMeshUpgradable(t)) {
				upgradeBodyMesh(tBo, scene, clickables, meshToBody);
				didUpgrade = true;
			}
			// The focused body's own texture load stays with the focus flow.
			if (t.data.id !== body?.data.id) loadTexture(t);
		}
		if (didUpgrade) {
			// Halo-only bodies had no trail; build now that `bo.mesh` is set.
			buildTrails(bodyObjects, scene, pointClouds.basis(), clock.jd);
			assignMapLayerToTrails();
		}
		this.upgradeTargetIds = newIds;
		return newIds;
	}

	/** Pan to frame `body` without changing the focused body — used to re-center on
	 *  the parent when focus goes out of range, keeping the "no data" toast on the original. */
	panCameraToBody(body: PositionedBody): void {
		if (body.positionUnknown) return;
		const { focus, camera } = this.deps;
		prepareFocusTarget(
			focus,
			[...body.position],
			camera,
			this.cameraTruePos(),
			undefined,
			getSettings().resolvedReducedMotion
		);
	}

	/** Point the camera at a place, not a body (e.g. a spot on a drawn trajectory).
	 *  Clears the focused body — otherwise `updatePositions` re-pins the origin
	 *  to it every frame; a moving point needs the caller to re-drive it. */
	focusOnPoint(position: Vec3, distance?: number): void {
		const { focus, camera, callbacks } = this.deps;
		const camWorld = this.cameraTruePos();
		let camPos: Vec3 | undefined;
		if (distance !== undefined) {
			// Arrive from the camera's current direction, so it reads as a glide not a cut.
			const dir = this._tmpV3
				.set(position[0] - camWorld[0], position[1] - camWorld[1], position[2] - camWorld[2])
				.normalize()
				.negate();
			camPos = [
				position[0] + dir.x * distance,
				position[1] + dir.y * distance,
				position[2] + dir.z * distance
			];
		}
		this.focusedBody = undefined;
		prepareFocusTarget(
			focus,
			[...position],
			camera,
			camWorld,
			camPos,
			getSettings().resolvedReducedMotion
		);
		const spherical = cartesianToSpherical(camPos ?? camWorld, position, undefined);
		callbacks.onCameraPosition?.(spherical.latitude, spherical.longitude, spherical.distance);
	}

	/** Click → emit + fly. Re-clicking the focused body re-emits without moving the camera. */
	handleFocus(body: PositionedBody): void {
		if (this.focusedBody?.data.id === body.data.id) {
			this.deps.callbacks.onFocusChange(body);
			return;
		}
		this.setFocusTarget(body);
		if (body.positionUnknown) return; // camera never moved — nothing to report
		const camWorld = this.cameraTruePos();
		const { latitude, longitude, distance } = cartesianToSpherical(
			camWorld,
			body.position,
			this.focusedBodyQuat(body)
		);
		this.deps.callbacks.onCameraPosition?.(latitude, longitude, distance);
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		const { ctx, bodyObjects, controls, callbacks, focus, camera, systemData, loadTexture } =
			this.deps;
		// Surface-feature bodies render nothing themselves — the host draws the
		// terrain. Skip halo/label allocation.
		if (!isSurfaceFeature(body)) this.promotion.ensureBodyObjects(body);

		// Unfocused bodies stay halo-only for cost; minDistance below reads the
		// focused body's mesh radius, so swap focus first.
		const prev = this.focusedBody;
		// Labels live on the landing body, not the probe — dispose only when it changes.
		const prevNomBodyId = nomenclatureBodyId(prev, bodyObjects);
		const newNomBodyId = nomenclatureBodyId(body, bodyObjects);
		// A surface feature defers its model to its host; unload only when that changes.
		const prevModelId =
			prev && (isSurfaceFeature(prev) ? prev.featureAnchor!.hostId : prev.data.id);
		const newModelId = isSurfaceFeature(body) ? body.featureAnchor!.hostId : body.data.id;
		const newTargetIds = this.syncUpgradeTargets(body);
		// A target that stays upgraded keeps its model too (a probe's fit
		// center focused, then unfocused back to the probe).
		if (prevModelId && prevModelId !== newModelId && !newTargetIds.has(prevModelId)) {
			const prevBo = bodyObjects.get(prevModelId);
			if (prevBo) unloadBodyModel(prevBo);
		}
		if (prevNomBodyId && prevNomBodyId !== newNomBodyId) {
			const prevNomBo = bodyObjects.get(prevNomBodyId);
			if (prevNomBo) disposeNomenclatureLabels(prevNomBo);
		}

		this.focusedBody = body;
		// Retire the synthetic feature body so getBody stops resolving a stale id.
		if (!isSurfaceFeature(body)) ctx.bodies.focusFeature = null;
		controls.minDistance = minCameraDistance(body, modelMinRadiusKm(bodyObjects.get(body.data.id)));
		// System/attribution follow the host (a crater has no ephemeris); camera
		// still orbits the feature body.
		const featureHost = isSurfaceFeature(body)
			? ctx.getBody(body.featureAnchor!.hostId)
			: undefined;
		ctx.visibility.setFocused(featureHost ?? body);
		callbacks.onFocusChange(body);
		// The feature body has no detail bundle of its own; its host loads below.
		if (!isSurfaceFeature(body)) loadTexture(body);
		// Landed probe / surface feature: also load the host for its nomenclature/terrain.
		if (newNomBodyId && newNomBodyId !== body.data.id) {
			const landingBody = ctx.getBody(newNomBodyId);
			if (landingBody) loadTexture(landingBody);
		}
		systemData.syncToFocus();
		// An unplaced body's `position` is a stand-in (its parent, or the scene
		// origin): moving the camera there would fly it to the Sun or the
		// barycentre. Take the focus, leave the camera where the user left it.
		if (!body.positionUnknown) {
			prepareFocusTarget(
				focus,
				[...body.position],
				camera,
				this.cameraTruePos(),
				camPos,
				getSettings().resolvedReducedMotion
			);
		}
		// Re-emit: the clear button excludes the focused body, so it must stay in sync.
		this.promotion.emitUserPromotedCount();
	}

	/**
	 * Programmatic focus: fly to body at optional zoom, optionally landing at a
	 * specific body-fixed lat/lon. Returns the animation duration in ms.
	 */
	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		const { ctx, clock, focus, camera, callbacks, pointClouds } = this.deps;
		const body = ctx.getBody(id);
		if (!body) return 0;
		// Point-cloud bodies materialize frozen at [0,0,0]; refresh before computing
		// the camera destination below, or we'd frame the SSB instead of the body.
		if (!ctx.bodies.bodiesById.has(id)) refreshMinorBodyPosition(body, clock.jd, ctx);
		// Nowhere to fly: take the focus (drawer, trails, system data) and hold the
		// camera. Framing the stand-in position would read as a jump to the Sun.
		if (body.positionUnknown) {
			this.setFocusTarget(body);
			return 0;
		}
		let camPos: Vec3 | undefined;
		if (zoom !== undefined) {
			if (latitude !== undefined && longitude !== undefined) {
				camPos = sphericalToCartesian(
					body.position,
					latitude,
					longitude,
					zoom,
					this.focusedBodyQuat(body)
				);
			} else {
				// Place camera at `zoom` distance, arriving from the current direction.
				const camWorld = this.cameraTruePos();
				const dir = this._tmpV3
					.set(
						body.position[0] - camWorld[0],
						body.position[1] - camWorld[1],
						body.position[2] - camWorld[2]
					)
					.normalize()
					.negate();
				camPos = [
					body.position[0] + dir.x * zoom,
					body.position[1] + dir.y * zoom,
					body.position[2] + dir.z * zoom
				];
			}
		}
		// Emit before dispatch so AppState's camera fields are fresh when
		// onFocusChange fires inside setFocusTarget.
		const emitFrom = camPos ?? this.cameraTruePos();
		const spherical = cartesianToSpherical(emitFrom, body.position, this.focusedBodyQuat(body));
		callbacks.onCameraPosition?.(spherical.latitude, spherical.longitude, spherical.distance);
		if (zoom !== undefined && camPos) {
			// Re-framing needs the camera actually orbiting this body — `focusedBody` is
			// set eagerly and can be stale, so gate on origin coincidence instead.
			const orbitingThisBody =
				this.focusedBody?.data.id === id &&
				f64dist(focus.focusTruePos, body.position) < minCameraDistance(body);
			if (orbitingThisBody) {
				// Snap focus in case a prior fly animation hasn't fully settled.
				focus.focusTruePos = [...body.position];
				this.deps.repositionAll();
				pointClouds.rebuildBasis();
				prepareFlyToCamera(
					focus,
					camera,
					this.cameraTruePos(),
					camPos,
					getSettings().resolvedReducedMotion
				);
			} else {
				this.setFocusTarget(body, camPos);
				if (latitude !== undefined && longitude !== undefined) {
					// Orbit mode so Earth stays centered during approach.
					focus.orbitFly = true;
				}
			}
		} else {
			this.setFocusTarget(body);
		}
		return focus.focusDurationMs;
	}

	/** Instantly focus a now-resident body per the URL, no approach fly — for a
	 *  late-arriving chunk landing after the camera settled on the placeholder parent. */
	snapToBody(id: string, latitude: number, longitude: number, zoom: number): void {
		const body = this.deps.ctx.getBody(id);
		if (!body || body.positionUnknown) return;
		this.settleOnBodyInstant(body);
		this.snapToBodyFrame(latitude, longitude, zoom);
	}

	/** Snap focus onto a body, framed toward `towardId` (e.g. the Sun) at
	 *  `elevationDeg` above the ecliptic. Scene-frame, not body-fixed — clears
	 *  the pending replay. Used for the home/bare-Earth landing view. */
	snapToBodyFacing(id: string, towardId: string, elevationDeg: number, distance: number): void {
		const { ctx, camera, controls, callbacks } = this.deps;
		const body = ctx.getBody(id);
		if (!body || body.positionUnknown) return;
		this.settleOnBodyInstant(body);
		const toward = ctx.getBody(towardId)?.position ?? [0, 0, 0];
		const offset = offsetFacing(body.position, toward, elevationDeg, distance);
		camera.position.set(offset[0], offset[1], offset[2]);
		controls.update();
		const settled = cartesianToSpherical(offset, [0, 0, 0]);
		callbacks.onCameraPosition?.(settled.latitude, settled.longitude, settled.distance);
		this.pendingInitialView = null; // scene-frame placement is final; skip the body-fixed replay
	}

	/** Settle focus onto a resident body with no approach fly, nulling the cam-fly
	 *  fields so stepFocusAnimation's settle branch leaves the snapped frame untouched. */
	private settleOnBodyInstant(body: PositionedBody): void {
		const { focus, pointClouds } = this.deps;
		this.setFocusTarget(body);
		focus.focusTruePos = [...body.position];
		focus.focusOriginWorld = [...body.position];
		focus.focusTargetWorld = [...body.position];
		focus.focusStartTime = -FOCUS_DURATION_MS; // already settled
		focus.camOriginWorld = null;
		focus.camTargetWorld = null;
		focus.flyQ0 = null;
		focus.orbitFly = false;
		focus.arcOrbit = false;
		focus.cameraStaysOnBody = false;
		this.deps.repositionAll();
		pointClouds.rebuildBasis();
	}

	/** Snap the camera to a body-fixed lat/lon/zoom for URL deep links, no fly.
	 *  Uses the current quat (identity if not loaded); queues a replay to
	 *  correct the angle once orientation lands. */
	snapToBodyFrame(latitude: number, longitude: number, zoom: number): void {
		const body = this.focusedBody;
		if (!body) return;
		const { camera, controls, callbacks } = this.deps;
		// Spacecraft use world coords (see focusedBodyQuat); natural bodies are
		// body-fixed, falling back to identity until orientation loads.
		const bodyFixed = !isModelBearing(body);
		const quat = bodyFixed ? (this.focusedBodyQuat(body) ?? [0, 0, 0, 1]) : undefined;
		const camOffset = sphericalToCartesian([0, 0, 0], latitude, longitude, zoom, quat);
		camera.position.set(camOffset[0], camOffset[1], camOffset[2]);
		controls.update();
		// Read back via cartesianToSpherical to canonicalize to (-180, 180] — feature
		// lon is stored 0..360 and would otherwise leak straight to the URL.
		const settled = cartesianToSpherical(camOffset, [0, 0, 0], quat);
		callbacks.onCameraPosition?.(settled.latitude, settled.longitude, settled.distance);
		const isIdentity =
			bodyFixed && quat![0] === 0 && quat![1] === 0 && quat![2] === 0 && quat![3] === 1;
		if (isIdentity) {
			// Overrides any queued URL at= — feature framing is more specific.
			this.pendingInitialView = { latitude, longitude, zoom };
		}
	}

	/** Re-place the camera at the URL's body-fixed lat/lon once orientation has
	 *  loaded — the ctor's initial placement runs before that fetch and falls
	 *  back to scene-frame. */
	reapplyInitialViewIfPending(): void {
		const pending = this.pendingInitialView;
		if (!pending) return;
		const quat = this.focusedBodyQuat();
		// Identity quat → no orientation data (e.g. asteroids); keep scene-frame placement.
		if (!quat || (quat[0] === 0 && quat[1] === 0 && quat[2] === 0 && quat[3] === 1)) {
			this.pendingInitialView = null;
			return;
		}
		const camPos = sphericalToCartesian(
			[0, 0, 0],
			pending.latitude,
			pending.longitude,
			pending.zoom,
			quat
		);
		this.deps.camera.position.set(...camPos);
		this.deps.controls.update();
		this.pendingInitialView = null;
	}
}

/** Bodies whose mesh should be upgraded while `focus` is focused: the focus
 *  itself, plus the parent for asteroid moons (so it stays a sphere + trail)
 *  and for probes (the fit center the probe is orbiting — Bennu under
 *  OSIRIS-REx — which needs its mesh/model to read the orbit against). */
function upgradeTargets(focus: PositionedBody | undefined, ctx: ContextManager): PositionedBody[] {
	if (!focus) return [];
	// A surface feature renders no mesh; its host must so the camera has terrain
	// to orbit (catches halo-only hosts like small moons/asteroids).
	if (isSurfaceFeature(focus)) {
		const host = ctx.getBody(focus.featureAnchor!.hostId);
		return host && isMeshUpgradable(host) ? [host] : [];
	}
	const out: PositionedBody[] = [];
	if (isMeshUpgradable(focus)) out.push(focus);
	const wantsParent =
		focus.data.objectType === ObjectType.MOON ||
		focus.data.orbitalSource === OrbitalSource.SPICE_PROBE;
	if (wantsParent) {
		// Non-upgradable parents (Ceres under Dawn) join too: they keep their
		// own mesh, but membership drives their texture/DEM/model load and
		// protects the resident state across focus switches.
		const parent = ctx.getBody(focus.data.parentId);
		if (parent) out.push(parent);
	}
	return out;
}
