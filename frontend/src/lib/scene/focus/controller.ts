import { Vector3, type Mesh, type PerspectiveCamera, type Scene } from 'three';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { cartesianToSpherical, offsetFacing, sphericalToCartesian } from '$lib/math/spherical';
import type { BodyObjects, Callbacks } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import {
	downgradeBodyMesh,
	isMeshUpgradable,
	upgradeBodyMesh
} from '$lib/scene/objects/body/lifecycle';
import { unloadBodyModel } from '$lib/scene/objects/body/model';
import {
	disposeNomenclatureLabels,
	nomenclatureBodyId
} from '$lib/scene/objects/surface/nomenclature';
import { buildTrails } from '$lib/scene/objects/body/bulk';
import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
import {
	FOCUS_DURATION_MS,
	prepareFlyToCamera,
	prepareFocusTarget,
	type FocusState
} from '$lib/scene/animation/focus';
import { f64dist, type Vec3 } from '$lib/scene/animation/math';
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

/**
 * Owns the focused body, focus/fly animation parameters, and the URL-derived
 * initial-view replay. Delegates promote/teardown to {@link PromotionRegistry}
 * (created here so the two share lifecycle).
 */
export class FocusController {
	readonly promotion: PromotionRegistry;
	private focusedBody: PositionedBody | undefined;
	private readonly _tmpV3 = new Vector3();
	/**
	 * Initial lat/lon/zoom stashed until the focused body's orientation has
	 * loaded, at which point we re-place the camera in body-fixed coords.
	 * Cleared once applied or once the user moves the camera.
	 */
	private pendingInitialView: { latitude: number; longitude: number; zoom: number } | null = null;

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

	/** Quaternion of `body`'s (or the focused body's) mesh — undefined if no mesh yet. */
	focusedBodyQuat(body?: PositionedBody): [number, number, number, number] | undefined {
		const id = (body ?? this.focusedBody)?.data.id;
		if (!id) return undefined;
		const mesh = this.deps.bodyObjects.get(id)?.mesh;
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

	/** Initial-focus mesh upgrade: walks {@link upgradeTargets} so the focused
	 *  body AND (for moons-of-asteroids) the parent host get a sphere mesh on
	 *  first paint, not just the focused body itself. Used by the renderer at
	 *  scene-build time; subsequent focus changes go through
	 *  {@link setFocusTarget}, which handles upgrade/downgrade symmetrically.
	 *  Returns true if any mesh was upgraded so the caller can rebuild trails. */
	upgradeMeshTargets(body: PositionedBody): boolean {
		const { ctx, scene, clickables, meshToBody, bodyObjects } = this.deps;
		let didUpgrade = false;
		for (const t of upgradeTargets(body, ctx)) {
			this.promotion.ensureBodyObjects(t);
			const tBo = bodyObjects.get(t.data.id);
			if (!tBo) continue;
			const hadMesh = tBo.mesh !== null;
			upgradeBodyMesh(tBo, scene, clickables, meshToBody);
			if (!hadMesh && tBo.mesh !== null) didUpgrade = true;
		}
		return didUpgrade;
	}

	/** Pan the camera to frame `body` without changing the focused/selected body.
	 *  Used to re-center on the parent when the focus goes out of range, keeping
	 *  the focus (and its "no data" toast) on the original body. */
	panCameraToBody(body: PositionedBody): void {
		const { focus, camera } = this.deps;
		prepareFocusTarget(focus, [...body.position], camera, this.cameraTruePos());
	}

	/** Click → emit + fly. Re-clicking the focused body re-emits without moving the camera. */
	handleFocus(body: PositionedBody): void {
		if (this.focusedBody?.data.id === body.data.id) {
			this.deps.callbacks.onFocusChange(body);
			return;
		}
		this.setFocusTarget(body);
		const camWorld = this.cameraTruePos();
		const { latitude, longitude, distance } = cartesianToSpherical(
			camWorld,
			body.position,
			this.focusedBodyQuat(body)
		);
		this.deps.callbacks.onCameraPosition?.(latitude, longitude, distance);
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		const {
			ctx,
			scene,
			clickables,
			meshToBody,
			bodyObjects,
			controls,
			callbacks,
			focus,
			camera,
			pointClouds,
			clock,
			systemData,
			loadTexture,
			assignMapLayerToTrails
		} = this.deps;
		this.promotion.ensureBodyObjects(body);

		// Halo-only-with-mesh-on-focus: asteroids/comets/probes build their
		// sphere mesh (and a/c their trail) only while focused; reverting
		// to halo-only on un-focus keeps the unfocused scene cheap. Asteroid
		// moons extend the upgrade set to their parent so the parent stays
		// visible (mesh + trail) while the user orbits the moon. minDistance
		// below reads the focused body's mesh radius, so do the swap first.
		// Always unload the prev body's overlay model — it isn't tied to the
		// sphere mesh, so non-upgradable bodies would otherwise leak GLBs.
		const prev = this.focusedBody;
		// Labels live on the landing body, not the probe — only dispose when
		// the effective nomenclature body actually changes.
		const prevNomBodyId = nomenclatureBodyId(prev, bodyObjects);
		const newNomBodyId = nomenclatureBodyId(body, bodyObjects);
		if (prev && prev.data.id !== body.data.id) {
			const prevBo = bodyObjects.get(prev.data.id);
			if (prevBo) unloadBodyModel(prevBo);
		}
		if (prevNomBodyId && prevNomBodyId !== newNomBodyId) {
			const prevNomBo = bodyObjects.get(prevNomBodyId);
			if (prevNomBo) disposeNomenclatureLabels(prevNomBo);
		}
		const prevTargets = upgradeTargets(prev, ctx);
		const newTargets = upgradeTargets(body, ctx);
		const prevIds = new Set(prevTargets.map((b) => b.data.id));
		const newIds = new Set(newTargets.map((b) => b.data.id));
		for (const t of prevTargets) {
			if (newIds.has(t.data.id)) continue;
			const tBo = bodyObjects.get(t.data.id);
			if (tBo) downgradeBodyMesh(tBo, scene, clickables, meshToBody);
		}
		let didUpgrade = false;
		for (const t of newTargets) {
			if (prevIds.has(t.data.id)) continue;
			this.promotion.ensureBodyObjects(t);
			const tBo = bodyObjects.get(t.data.id);
			if (tBo) {
				upgradeBodyMesh(tBo, scene, clickables, meshToBody);
				didUpgrade = true;
			}
		}
		if (didUpgrade) {
			// Mesh-upgradable bodies had no trail as halo-only; this picks them
			// up now that `bo.mesh` is set.
			buildTrails(bodyObjects, scene, pointClouds.basis(), clock.jd);
			assignMapLayerToTrails();
		}

		this.focusedBody = body;
		controls.minDistance = minCameraDistance(body);
		ctx.visibility.setFocused(body);
		callbacks.onFocusChange(body);
		loadTexture(body);
		// Landed probe: also load the landing body so its nomenclature attaches.
		if (newNomBodyId && newNomBodyId !== body.data.id) {
			const landingBody = ctx.getBody(newNomBodyId);
			if (landingBody) loadTexture(landingBody);
		}
		systemData.syncToFocus();
		prepareFocusTarget(focus, [...body.position], camera, this.cameraTruePos(), camPos);
		// Focus moved on/off a user-promoted body — re-emit so the clear button
		// (which excludes the focused body) stays in sync.
		this.promotion.emitUserPromotedCount();
	}

	/**
	 * Programmatic focus: fly to body at optional zoom, optionally landing at a
	 * specific body-fixed lat/lon. Returns the animation duration in ms.
	 */
	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		const { ctx, focus, camera, callbacks, pointClouds } = this.deps;
		const body = ctx.getBody(id);
		if (!body) return 0;
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
		// Emit the target camera position before any focus/fly dispatch so that
		// AppState's camera fields are fresh when onFocusChange fires inside
		// setFocusTarget and setFocus captures the intended destination.
		const emitFrom = camPos ?? this.cameraTruePos();
		const spherical = cartesianToSpherical(emitFrom, body.position, this.focusedBodyQuat(body));
		callbacks.onCameraPosition?.(spherical.latitude, spherical.longitude, spherical.distance);
		if (zoom !== undefined && camPos) {
			// In-object re-framing (arc-orbit) is only correct when the camera is
			// actually orbiting this body right now — `focusedBody` is set eagerly at
			// fly-start and can be stale (e.g. a still-animating fly, or a second
			// feature-pick landing mid-flight), so gate on the focus origin being
			// coincident with the body. Otherwise fall through to the approach fly so
			// the camera glides in instead of teleporting onto the body.
			const orbitingThisBody =
				this.focusedBody?.data.id === id &&
				f64dist(focus.focusTruePos, body.position) < minCameraDistance(body);
			if (orbitingThisBody) {
				// Snap focus in case a prior fly animation hasn't fully settled.
				focus.focusTruePos = [...body.position];
				this.deps.repositionAll();
				pointClouds.rebuildBasis();
				prepareFlyToCamera(focus, camera, this.cameraTruePos(), camPos);
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

	/**
	 * Instantly focus a now-resident body and frame it per the URL — no approach
	 * fly. Used at load when the target's element chunk arrives after the initial
	 * render has already settled the camera on the placeholder parent (Earth):
	 * the user should land directly on the target, not watch a fly in from Earth.
	 */
	snapToBody(id: string, latitude: number, longitude: number, zoom: number): void {
		const body = this.deps.ctx.getBody(id);
		if (!body) return;
		this.settleOnBodyInstant(body);
		this.snapToBodyFrame(latitude, longitude, zoom);
	}

	/** Snap focus onto a body, framed looking toward `towardId` (e.g. the Sun),
	 *  `elevationDeg` above the ecliptic. Placed in the scene frame, not body-fixed,
	 *  so the pending replay is cleared. Used for the home/bare-Earth landing view. */
	snapToBodyFacing(id: string, towardId: string, elevationDeg: number, distance: number): void {
		const { ctx, camera, controls, callbacks } = this.deps;
		const body = ctx.getBody(id);
		if (!body) return;
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

	/** Snap the camera to a body-fixed lat/lon/zoom without any fly animation.
	 *  Used for URL-load deep links where the user expects the page to open
	 *  already framed on the target. Applies immediately with the current quat
	 *  (identity if not loaded yet — fine for asteroids whose mesh is identity-
	 *  oriented, matches where feature labels are placed). For bodies whose
	 *  orientation arrives async, also queues a replay so the framing snaps to
	 *  the right angle once the real quat lands. */
	snapToBodyFrame(latitude: number, longitude: number, zoom: number): void {
		const body = this.focusedBody;
		if (!body) return;
		const { camera, controls, callbacks } = this.deps;
		const quat = this.focusedBodyQuat(body) ?? [0, 0, 0, 1];
		const camOffset = sphericalToCartesian([0, 0, 0], latitude, longitude, zoom, quat);
		camera.position.set(camOffset[0], camOffset[1], camOffset[2]);
		controls.update();
		// Read back via cartesianToSpherical so the URL writeback matches the
		// canonical (-180, 180] longitude the fly-settle path produces — feature
		// lon is stored in 0..360 and would otherwise leak straight to the URL.
		const settled = cartesianToSpherical(camOffset, [0, 0, 0], quat);
		callbacks.onCameraPosition?.(settled.latitude, settled.longitude, settled.distance);
		const isIdentity = quat[0] === 0 && quat[1] === 0 && quat[2] === 0 && quat[3] === 1;
		if (isIdentity) {
			// Replaces whatever the URL's at= had queued — the feature framing
			// is more specific than the URL's body-level at=.
			this.pendingInitialView = { latitude, longitude, zoom };
		}
	}

	/**
	 * Re-place the camera using the URL's body-fixed lat/lon once the focused
	 * body's orientation has loaded. The initial placement in the ctor runs
	 * before orientation fetches, so it falls back to scene-frame; this
	 * corrects for that.
	 */
	reapplyInitialViewIfPending(): void {
		const pending = this.pendingInitialView;
		if (!pending) return;
		const quat = this.focusedBodyQuat();
		// Identity quat → body has no orientation data (e.g. asteroids) — keep
		// the initial scene-frame placement.
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

/** Bodies whose mesh should be upgraded while `focus` is the focused body.
 *  Always includes the focus itself if it's mesh-upgradable; for asteroid moons
 *  also includes the parent asteroid, so the parent stays as a sphere + trail
 *  instead of dropping back to a label-only halo. */
function upgradeTargets(focus: PositionedBody | undefined, ctx: ContextManager): PositionedBody[] {
	if (!focus) return [];
	const out: PositionedBody[] = [];
	if (isMeshUpgradable(focus)) out.push(focus);
	if (focus.data.objectType === ObjectType.MOON) {
		const parent = ctx.getBody(focus.data.parentId);
		if (parent && isMeshUpgradable(parent)) out.push(parent);
	}
	return out;
}
