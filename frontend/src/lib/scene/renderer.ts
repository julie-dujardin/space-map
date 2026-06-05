import {
	AmbientLight,
	DirectionalLight as DirectionalLightClass,
	type DirectionalLight,
	Mesh,
	PerspectiveCamera as PerspectiveCameraClass,
	type PerspectiveCamera,
	PointLight,
	Scene as SceneClass,
	type Scene,
	TextureLoader,
	Vector3,
	type WebGLRenderer
} from 'three';
import type { ThrottledCSS2DRenderer } from '$lib/scene/label/throttled-renderer';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import type { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OrbitControls as OrbitControlsClass } from 'three/addons/controls/OrbitControls.js';
import { cartesianToSpherical, sphericalToCartesian } from '$lib/math/spherical';
import type { MapViewState } from '$lib/state/view';
import type { PositionedBody } from '$lib/types/objects';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { AU_SCALE, kmToScene } from '$lib/math/units';
import { EARTH_ID, SUN_ID } from '$lib/constants';
import { bootThree } from './setup/three-boot';
import { PointerInteraction } from './interaction/pointer';
import { CameraUpController } from './camera/up-controller';
import { jdToDate } from '$lib/format/date';
import { buildMajorBodies } from './objects/body/lifecycle';
import { loadBodyTexture } from './objects/body/textures';
import { applyOrientation } from '$lib/math/orientation';
import { loadBodyModel, makeModelEnvMap } from './objects/body/model';
import { attachNomenclatureLabels, setActiveFeatureLabel } from './objects/surface/nomenclature';
import { buildTrails } from './objects/body/bulk';
import { makeCircleTexture } from './objects/pointcloud';
import { SystemDataLoader } from './system-data/loader';
import { loadSkybox } from './objects/sky/skybox';
import { SkyboxAdjuster } from './debug/skybox-adjust';
import { SkyDebugMarkers } from './debug/sky-markers';
import { collectDebugStats, type DebugStats } from './debug/stats';
import { PointCloudSystem } from './pointclouds/system';
import { rebaseTrailLocals, refreshBufferTrail } from './objects/trail/refresh';
import { setTrailResolution } from './objects/trail/material';
import type { TrailBuffer } from '$lib/fetch/position/trail-buffer';
import { updatePositions, refreshDeferredTrails } from './position/update-positions';
import { PositionDiagnostics } from './position/diagnostics';
import { updateRingShaders } from './shaders/ring-uniforms';
import { updateAtmosphereShaders } from './shaders/atmosphere-uniforms';
import { updateEclipseUniforms } from './shaders/eclipse-uniforms';
import { evaluateEclipseFactor } from './objects/surface/eclipse-shadow';
import { updateSunShadowLight } from './shaders/sun-shadow-light';
import { updateSphereLOD } from './lod/sphere-lod';
import { updateTextureLOD } from './lod/texture-lod';
import { type BodyObjects, type Callbacks } from './types';
import type { Vec3 } from './animation/math';
import { type FocusState, FOCUS_DURATION_MS, stepFocusAnimation } from './animation/focus';
import { FocusController } from './focus/controller';
import { minCameraDistance } from './visibility/camera-limits';
import { updateBodyVisibility } from './visibility/update';
import { createUserLocationMarker, removeUserLocationMarker } from './user-location/marker';
import { updateUserLocationOcclusion } from './user-location/occlusion';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

/** Base intensity of the model-overlay directional light. Scaled by the eclipse factor. */
const MODEL_LIGHT_BASE_INTENSITY = 3.0;
/** Base intensity of the model-overlay IBL. Heavily dimmed so metals have something
 *  to reflect without overwhelming the sun. Scaled by the eclipse factor. */
const MODEL_ENV_BASE_INTENSITY = 0.04;

export class SceneRenderer {
	private renderer: WebGLRenderer;
	private composer: EffectComposer;
	private bloomPass: UnrealBloomPass;
	private labelRenderer: ThrottledCSS2DRenderer;
	private scene: Scene;
	private camera: PerspectiveCamera;
	private controls: OrbitControls;
	private pointerInteraction!: PointerInteraction;

	private canvas: HTMLCanvasElement;
	private ctx: ContextManager;
	private clock: SimClock;
	private callbacks: Callbacks;
	private selectedFeatureId: number | null = null;

	private bodyObjects = new Map<string, BodyObjects>();
	private circleTexture = makeCircleTexture();
	private pointClouds!: PointCloudSystem;
	private systemData!: SystemDataLoader;
	private readonly positionDiagnostics = new PositionDiagnostics();
	private clickables: Mesh[] = [];
	private meshToBody = new Map<Mesh, PositionedBody>();
	private hoveredBodyIds = new Set<string>();
	private cullFrameCounter = 0;

	// TODO: expose via UI settings
	hideCappedMoonLabels = false;

	private focusController!: FocusController;
	private readonly _tmpV3 = new Vector3();

	/**
	 * Isolated overlay scene for spacecraft 3D models. Main scene's log depth
	 * buffer collapses inside the focused body's ~10⁻¹⁰-scene-unit bubble and
	 * Z-fights thin structures. The overlay renders the model at unit scale
	 * with a tight near/far, projected to the same on-screen position.
	 */
	private modelScene!: Scene;
	private modelCamera!: PerspectiveCamera;
	private modelLight!: DirectionalLight;

	private cameraUp!: CameraUpController;
	private skyboxAdjuster!: SkyboxAdjuster;
	private skyDebugMarkers!: SkyDebugMarkers;

	private readonly focus: FocusState = {
		focusTruePos: [0, 0, 0],
		focusOriginWorld: [0, 0, 0],
		focusTargetWorld: [0, 0, 0],
		camOriginWorld: null,
		camTargetWorld: null,
		camTargetOffset: null,
		flyQ0: null,
		flyQ1: null,
		orbitFly: false,
		cameraStaysOnBody: false,
		focusStartTime: 0,
		focusDurationMs: FOCUS_DURATION_MS
	};
	/** JD at which per-frame body positions were last computed. */
	private lastUpdatedJd = NaN;
	private readonly _positionMapScratch = new Map<string, Vec3>();

	private rafId = 0;
	private firstFrame = true;
	private pendingUrlWrite = false;
	/** Ring buffer of recent tick timestamps; fps = (n-1) / (last - first). */
	private static readonly FPS_SAMPLE_FRAMES = 30;
	private fpsSamples: number[] = [];
	private fpsSampleHead = 0;
	private readonly textureLoader = new TextureLoader();
	private readonly shadowLight: DirectionalLight;
	private sunPointLight: PointLight | undefined;
	/** Pinned user-location dot on Earth's surface (Google-Maps-style). */
	private userLocationMarker: CSS2DObject | null = null;
	/** DOM container for CSS2D labels; hidden entirely in immersive mode. */
	private labelContainer: HTMLElement;
	/**
	 * Layer used for "map UI": trails + point clouds. Immersive mode
	 * disables this layer on the camera, so the WebGL pass skips them while
	 * meshes (layer 0) keep rendering.
	 */
	private static readonly MAP_LAYER = 1;

	constructor(
		canvas: HTMLCanvasElement,
		labelContainer: HTMLElement,
		ctx: ContextManager,
		clock: SimClock,
		initialView: MapViewState,
		callbacks: Callbacks
	) {
		this.canvas = canvas;
		this.ctx = ctx;
		this.clock = clock;
		this.callbacks = callbacks;
		this.labelContainer = labelContainer;

		const boot = bootThree(canvas, labelContainer, ctx);
		this.renderer = boot.renderer;
		this.labelRenderer = boot.labelRenderer;
		this.scene = boot.scene;
		this.camera = boot.camera;
		this.composer = boot.composer;
		this.bloomPass = boot.bloomPass;
		this.shadowLight = boot.shadowLight;

		this.modelScene = new SceneClass();
		this.modelScene.environment = makeModelEnvMap(this.renderer);
		this.modelScene.environmentIntensity = MODEL_ENV_BASE_INTENSITY;
		this.modelCamera = new PerspectiveCameraClass(60, 1, 0.01, 1000);
		this.modelScene.add(this.modelCamera);
		this.modelScene.add(new AmbientLight(0xffffff, 0.01));
		this.modelLight = new DirectionalLightClass(0xffffff, MODEL_LIGHT_BASE_INTENSITY);
		// Model is normalised to unit-radius (see model.ts `fitToUnitRadius`); the
		// light sits at distance 10 from origin (see `renderModelOverlay`). Ortho
		// frustum covers the silhouette with a small margin.
		this.modelLight.castShadow = true;
		this.modelLight.shadow.mapSize.set(2048, 2048);
		this.modelLight.shadow.camera.left = -1.5;
		this.modelLight.shadow.camera.right = 1.5;
		this.modelLight.shadow.camera.top = 1.5;
		this.modelLight.shadow.camera.bottom = -1.5;
		this.modelLight.shadow.camera.near = 8;
		this.modelLight.shadow.camera.far = 12;
		this.modelLight.shadow.bias = -0.0001;
		this.modelLight.shadow.normalBias = 0.02;
		this.modelScene.add(this.modelLight);
		this.modelScene.add(this.modelLight.target);

		// Seed skybox rotation synchronously so frame 1 is correct and a debug-menu
		// setSkyboxAdjust isn't clobbered by the async load.
		this.skyboxAdjuster = new SkyboxAdjuster(this.scene);
		this.skyDebugMarkers = new SkyDebugMarkers(this.scene);
		this.skyboxAdjuster.set(0, 0, 0);
		void loadSkybox(this.scene, this.renderer, ctx);

		const sunBody = ctx.bodies.majorBodies.find((b) => b.data.id === SUN_ID);
		const matchedBody = ctx.getBody(initialView.id);
		const focusBody = matchedBody ?? sunBody;
		const focusPos: Vec3 = focusBody?.position ?? [0, 0, 0];

		this.focus.focusTruePos = [...focusPos];
		this.focus.focusOriginWorld = [...focusPos];
		this.focus.focusTargetWorld = [...focusPos];
		this.focus.focusStartTime = -FOCUS_DURATION_MS; // already settled

		this.pointClouds = new PointCloudSystem(
			ctx,
			this.scene,
			this.bodyObjects,
			this.circleTexture,
			this.focus,
			SceneRenderer.MAP_LAYER,
			() => this.rebuildTrailBasis()
		);
		this.pointClouds.seedBasis(focusPos);

		// OrbitControls — target always at origin
		this.controls = new OrbitControlsClass(this.camera, canvas);
		this.controls.enableDamping = true;
		this.controls.minDistance = focusBody ? minCameraDistance(focusBody) : kmToScene(0.01);
		this.controls.maxDistance = 31_620.5 * AU_SCALE; // 0.5 light-year
		this.controls.target.set(0, 0, 0);
		this.controls.update();
		this.controls.addEventListener('end', this.onControlsEnd);

		this.cameraUp = new CameraUpController(this.camera, this.controls, ctx);

		this.systemData = new SystemDataLoader(
			this.scene,
			ctx,
			this.renderer,
			this.textureLoader,
			this.bodyObjects,
			clock,
			() => this.focusController.reapplyInitialViewIfPending()
		);

		this.focusController = new FocusController(
			{
				ctx,
				clock,
				camera: this.camera,
				controls: this.controls,
				scene: this.scene,
				bodyObjects: this.bodyObjects,
				clickables: this.clickables,
				meshToBody: this.meshToBody,
				callbacks,
				focus: this.focus,
				pointClouds: this.pointClouds,
				systemData: this.systemData,
				loadTexture: (b) => this.maybeLoadTexture(b),
				repositionAll: () => this.repositionAll(),
				assignMapLayerToTrails: () => this.assignMapLayerToTrails()
			},
			focusBody,
			this.hoveredBodyIds,
			this.circleTexture,
			this.renderer
		);

		// Camera initial placement: focus-relative. lat/lon are body-fixed, but
		// the mesh quaternion is still identity (orientation metadata hasn't
		// loaded yet), so this falls back to scene-frame. Stash the requested
		// view and re-apply once orientation loads.
		const camPos = sphericalToCartesian(
			[0, 0, 0],
			initialView.latitude,
			initialView.longitude,
			initialView.zoom,
			this.focusController.focusedBodyQuat()
		);
		this.camera.position.set(...camPos);
		this.focusController.setPendingInitialView({
			latitude: initialView.latitude,
			longitude: initialView.longitude,
			zoom: initialView.zoom
		});

		if (focusBody) ctx.visibility.setFocused(focusBody);
		ctx.visibility.updateCamera(initialView.zoom, this.clock.jd);

		callbacks.onFocusChange(focusBody);

		this.buildScene();

		const sunBo = this.bodyObjects.get(SUN_ID);
		this.sunPointLight = sunBo?.extraObjects.find((o): o is PointLight => o instanceof PointLight);

		if (focusBody) this.focusController.promotion.ensureBodyObjects(focusBody);

		// Initial focus on a halo-only type (asteroid/comet/probe) builds its mesh
		// immediately; for moons-of-asteroids `upgradeMeshTargets` also upgrades
		// the parent host so it appears as a sphere alongside the focused moon.
		// setFocusTarget handles subsequent focus changes symmetrically.
		if (focusBody) {
			const didUpgrade = this.focusController.upgradeMeshTargets(focusBody);
			if (didUpgrade) {
				buildTrails(this.bodyObjects, this.scene, this.pointClouds.basis(), this.clock.jd);
				this.assignMapLayerToTrails();
			}
		}

		this.repositionAll();

		if (focusBody) this.maybeLoadTexture(focusBody);
		this.systemData.syncToFocus();

		this.pointerInteraction = new PointerInteraction(
			canvas,
			this.camera,
			ctx,
			clock,
			this.focus,
			this.clickables,
			this.meshToBody,
			(body) => this.focusController.handleFocus(body)
		);
		this.pointerInteraction.attach();

		this.tick();
	}

	private buildScene(): void {
		buildMajorBodies(
			this.ctx.bodies.majorBodies,
			this.scene,
			this.clickables,
			this.meshToBody,
			this.bodyObjects,
			this.circleTexture,
			this.renderer.domElement,
			(body) => this.focusController.handleFocus(body),
			(id, hovered) => (hovered ? this.hoveredBodyIds.add(id) : this.hoveredBodyIds.delete(id))
		);
		this.pointClouds.buildInitial(new Set(this.bodyObjects.keys()));
		// Defer trail geometry (100K+ Kepler solves) to after first paint.
		const basis = this.pointClouds.basis();
		const scheduleIdle = globalThis.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 0));
		scheduleIdle(() => {
			buildTrails(this.bodyObjects, this.scene, basis, this.clock.jd);
			this.assignMapLayerToTrails();
		});
	}

	/** Assign all current trails to MAP_LAYER so they can be hidden together by immersive mode. */
	private assignMapLayerToTrails(): void {
		for (const bo of this.bodyObjects.values()) {
			if (bo.trail) bo.trail.layers.set(SceneRenderer.MAP_LAYER);
		}
	}

	/**
	 * Map vs immersive view. Immersive hides CSS2D labels (DOM), trails,
	 * and point clouds — leaving only meshes + skybox visible. Picking and
	 * camera controls keep working, so the user can still navigate (with
	 * difficulty) and toggle back.
	 */
	setImmersive(immersive: boolean): void {
		if (immersive) {
			this.camera.layers.disable(SceneRenderer.MAP_LAYER);
			this.labelContainer.style.display = 'none';
		} else {
			this.camera.layers.enable(SceneRenderer.MAP_LAYER);
			this.labelContainer.style.display = '';
		}
	}

	rebuildMinorPointClouds(): void {
		this.pointClouds.rebuildMinor();
	}

	private repositionAll(): void {
		this.repositionBodies();
		this.rebuildTrailBasis();
	}

	/** Like {@link repositionAll} but skips the trail rewrite — for callers that already refreshed lines per-body. */
	private repositionBodies(): void {
		const [fx, fy, fz] = this.focus.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			const [bx, by, bz] = bo.body.position;
			const rx = bx - fx;
			const ry = by - fy;
			const rz = bz - fz;
			bo.group.position.set(rx, ry, rz);
			for (const obj of bo.extraObjects) obj.position.set(rx, ry, rz);
		}
		this.pointClouds.reposition();
	}

	/**
	 * Rebase cached orbit-local vertices against the current focus. No Kepler
	 * recompute; the per-jd path uses {@link refreshTrail} instead.
	 */
	private rebuildTrailBasis(): void {
		const basis = this.focus.focusTruePos;
		const [fx, fy, fz] = basis;
		for (const bo of this.bodyObjects.values()) {
			const line = bo.trail;
			// New lines have visible=false until updateBodyVisibility flips them
			// later this frame, so don't gate on .visible — they still need rebase.
			if (!line) continue;
			const trailBuffer = line.userData.trailBuffer as TrailBuffer | undefined;
			if (trailBuffer) {
				refreshBufferTrail(bo.body, line, trailBuffer, basis);
				continue;
			}
			const localPositions = line.userData.trailLocalPositions as
				| [number, number, number][]
				| undefined;
			if (!localPositions) continue;
			const oc = line.userData.orbitCenter as Vector3;
			rebaseTrailLocals(line, localPositions, oc.x - fx, oc.y - fy, oc.z - fz);
		}
	}

	private tick = (): void => {
		this.rafId = requestAnimationFrame(this.tick);

		const nowMs = performance.now();
		if (this.fpsSamples.length < SceneRenderer.FPS_SAMPLE_FRAMES) {
			this.fpsSamples.push(nowMs);
		} else {
			this.fpsSamples[this.fpsSampleHead] = nowMs;
			this.fpsSampleHead = (this.fpsSampleHead + 1) % SceneRenderer.FPS_SAMPLE_FRAMES;
		}

		this.cameraUp.update(this.clock.jd);

		if (this.firstFrame) {
			this.firstFrame = false;
			this.controls.target.set(0, 0, 0);
			this.controls.update();
		}

		// Gate body updates on jd actually changing — skips work while paused.
		this.clock.tick(performance.now());
		if (this.clock.jd !== this.lastUpdatedJd) {
			this.lastUpdatedJd = this.clock.jd;
			this.ctx.refreshTick(jdToDate(this.clock.jd));
			updatePositions({
				jd: this.clock.jd,
				ctx: this.ctx,
				bodyObjects: this.bodyObjects,
				focus: this.focus,
				focusedBody: this.focusController.current,
				positionMap: this._positionMapScratch,
				diagnostics: this.positionDiagnostics
			});
			this.pointClouds.updateForJd(this.clock.jd);
			// stepFocusAnimation handles repositionAll while animating.
			const elapsed = performance.now() - this.focus.focusStartTime;
			if (elapsed >= this.focus.focusDurationMs) {
				this.repositionBodies();
				this.pointClouds.maybeRebase();
			}
		}

		const controlsSettled = stepFocusAnimation(
			this.focus,
			this.camera,
			this.controls,
			() => this.repositionAll(),
			() => this.pointClouds.rebuildBasis()
		);
		if (this.pendingUrlWrite && controlsSettled) {
			this.pendingUrlWrite = false;
			const { latitude, longitude, distance } = this.getCameraState();
			this.callbacks.onCameraPosition?.(latitude, longitude, distance);
		}

		// Deferred system-data unload so a reversed mid-fly doesn't thrash the GPU.
		if (
			this.systemData.hasPendingUnloads() &&
			performance.now() - this.focus.focusStartTime >= this.focus.focusDurationMs
		) {
			this.systemData.drainPendingUnloads();
		}

		const { distance } = this.getCameraState();
		this.ctx.visibility.updateCamera(distance, this.clock.jd);

		this.cullFrameCounter = updateBodyVisibility(
			this.bodyObjects,
			this.camera,
			this.ctx,
			this.focus.focusTruePos,
			this.focusController.current?.data.id,
			this.hideCappedMoonLabels,
			this.hoveredBodyIds,
			this.pointClouds.asteroids(),
			this.pointClouds.spacecraft(),
			this.pointClouds.moons(),
			this.cullFrameCounter,
			this.renderer,
			this._tmpV3
		);

		// Catches lines updatePositions skipped (visible=false) that updateBodyVisibility
		// just flipped on, so they don't render at a stale basis for one frame.
		refreshDeferredTrails(this.bodyObjects, this.focus, this.lastUpdatedJd);

		updateRingShaders(this.bodyObjects, this.focus.focusTruePos);
		updateAtmosphereShaders(this.bodyObjects);
		updateEclipseUniforms(this.bodyObjects, this.focus.focusTruePos);

		updateUserLocationOcclusion(this.userLocationMarker, this.bodyObjects, this.camera);

		const focusedIdLod = this.focusController.current?.data.id;
		updateTextureLOD(
			this.bodyObjects,
			this.camera,
			this.renderer,
			this.ctx,
			this.textureLoader,
			focusedIdLod,
			this.clock.jd
		);
		updateSphereLOD(this.bodyObjects, this.camera, this.renderer, this.ctx, focusedIdLod);

		updateSunShadowLight(
			this.bodyObjects,
			this.focus.focusTruePos,
			this.ctx,
			this.shadowLight,
			this.sunPointLight,
			distance,
			this._tmpV3
		);

		// One point-cloud upload per frame to spread GPU cost. Auto-promotion
		// now happens push-style at chunk-arrival time (PromotionRegistry
		// listens on `BodyIndex.onBodiesAdded`).
		this.pointClouds.drainOnePendingSceneAdd();

		this.composer.render();
		this.renderModelOverlay();
		this.labelRenderer.render(this.scene, this.camera);
	};

	/**
	 * Composite the focused body's 3D model on top of the main render. The model
	 * lives in `modelScene` at unit scale; the overlay camera mirrors the main
	 * camera's orientation at a distance that keeps the model's screen footprint
	 * matching what the body sphere occupied, with tight near/far for depth.
	 */
	private renderModelOverlay(): void {
		const focusBody = this.focusController.current;
		if (!focusBody) return;
		const bo = this.bodyObjects.get(focusBody.data.id);
		if (!bo?.model) return;

		const camDist = this.camera.position.length();
		// Model is normalised to radius 1 in modelScene; this overlayDist matches
		// the screen size the focused body's sphere had.
		const overlayDist = camDist / (2 * bo.radiusScene);
		this.modelCamera.position.copy(this.camera.position).normalize().multiplyScalar(overlayDist);
		this.modelCamera.quaternion.copy(this.camera.quaternion);
		this.modelCamera.aspect = this.camera.aspect;
		this.modelCamera.near = Math.max(0.01, overlayDist - 5);
		this.modelCamera.far = overlayDist + 50;
		this.modelCamera.updateProjectionMatrix();

		// Sun direction in the overlay = (sun - focus) normalised, applied as
		// the directional light position (target at origin, distance arbitrary).
		const sunBody = this.bodyObjects.get(SUN_ID)?.body;
		if (sunBody) {
			const [sx, sy, sz] = sunBody.position;
			const [fx, fy, fz] = focusBody.position;
			this._tmpV3.set(sx - fx, sy - fy, sz - fz).normalize();
			this.modelLight.position.copy(this._tmpV3).multiplyScalar(10);
		}

		// Dim the sun by the analytical eclipse occlusion at the focused body's center.
		this._tmpV3.set(0, 0, 0);
		const factor = evaluateEclipseFactor(this._tmpV3, this._tmpV3);
		this.modelLight.intensity = MODEL_LIGHT_BASE_INTENSITY * factor;
		this.modelScene.environmentIntensity = MODEL_ENV_BASE_INTENSITY * factor;

		this.renderer.autoClear = false;
		this.renderer.clearDepth();
		this.renderer.render(this.modelScene, this.modelCamera);
		this.renderer.autoClear = true;
	}

	private getCameraState() {
		const cam = this.camera.position;
		return cartesianToSpherical(
			[cam.x, cam.y, cam.z],
			[0, 0, 0],
			this.focusController.focusedBodyQuat()
		);
	}

	private onControlsEnd = (): void => {
		this.pendingUrlWrite = true;
		// User-initiated motion wins — don't overwrite it when orientation loads.
		this.focusController.clearPendingInitialView();
	};

	private maybeLoadTexture(body: PositionedBody): void {
		const bo = this.bodyObjects.get(body.data.id);
		if (!bo) return;
		void loadBodyTexture(bo, this.textureLoader, this.clock.jd, this.ctx).then(() => {
			// Standalone focus (asteroids, comets) doesn't go through
			// systemData.onLoaded, so the URL-load snap initially runs with an
			// identity mesh quat and any queued pendingInitialView never gets
			// replayed. Force-apply orientation now and trigger reapply so the
			// camera lands on the body-fixed feature once orientation arrives.
			if (this.focusController.current?.data.id !== body.data.id) return;
			if (body.orientation && bo.mesh) {
				applyOrientation(bo.mesh, body.orientation, this.clock.jd, body.nutPrec);
				this.focusController.reapplyInitialViewIfPending();
			}
		});
		// Cheap no-op for bodies without a model bundle (gated inside loadBodyModel).
		loadBodyModel(bo, this.modelScene, this.ctx);
		// Nomenclature labels are focus-scoped — only the focused body fetches
		// and attaches them. Idempotent. Re-tag the active label after attach
		// resolves: `setSelectedFeature` may have run during the in-flight
		// detail+positions fetch (URL-load case), and that earlier call would
		// have no-op'd because labels weren't on `bo` yet.
		void attachNomenclatureLabels(bo, this.canvas, (featureId, lat, lon, diameterM) =>
			this.callbacks.onFeatureSelect?.(bo.body.data.id, featureId, lat, lon, diameterM)
		).then(() => {
			if (this.selectedFeatureId !== null) setActiveFeatureLabel(bo, this.selectedFeatureId);
		});
	}

	/** Update which surface-feature label renders as "active" (larger, bolder).
	 *  Tracked on the renderer so a body's labels picked up after a fly-in still
	 *  see the right selection. */
	setSelectedFeature(featureId: number | null): void {
		this.selectedFeatureId = featureId;
		const focused = this.focusController.current;
		if (!focused) return;
		const bo = this.bodyObjects.get(focused.data.id);
		if (bo) setActiveFeatureLabel(bo, featureId);
	}

	clearUserPromoted(): void {
		this.focusController.promotion.clearUserPromoted();
	}

	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		return this.focusController.focusOnBody(id, zoom, latitude, longitude);
	}

	snapToBodyFrame(latitude: number, longitude: number, zoom: number): void {
		this.focusController.snapToBodyFrame(latitude, longitude, zoom);
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.focusController.setFocusTarget(body, camPos);
	}

	getFocusedBody(): PositionedBody | undefined {
		return this.focusController.current;
	}

	getDebugStats(): DebugStats {
		const samples = this.fpsSamples;
		let fps = 0;
		if (samples.length >= 2) {
			const head = samples.length < SceneRenderer.FPS_SAMPLE_FRAMES ? 0 : this.fpsSampleHead;
			const oldest = samples[head];
			const newest = samples[(head - 1 + samples.length) % samples.length];
			const dtSec = (newest - oldest) / 1000;
			if (dtSec > 0) fps = (samples.length - 1) / dtSec;
		}
		return collectDebugStats({
			fps,
			orbitPool: this.pointClouds.orbitPool,
			renderer: this.renderer,
			bodyObjects: this.bodyObjects,
			focusedBody: this.focusController.current,
			cameraDistanceScene: this.getCameraState().distance
		});
	}

	setNorthReference(id: string | null): void {
		this.cameraUp.setNorthReference(id);
	}

	getSkyboxAdjust(): { rxDeg: number; ryDeg: number; rzDeg: number } {
		return this.skyboxAdjuster.get();
	}

	setSkyboxAdjust(rxDeg: number, ryDeg: number, rzDeg: number): void {
		this.skyboxAdjuster.set(rxDeg, ryDeg, rzDeg);
	}

	setSkyDebugMarkersVisible(visible: boolean): void {
		this.skyDebugMarkers.setVisible(visible);
	}

	/** Drop a "you are here" pin at lat/lon on Earth; re-pins if already set. */
	setUserLocation(latitude: number, longitude: number): void {
		const earth = this.bodyObjects.get(EARTH_ID);
		if (!earth?.mesh) return;
		if (this.userLocationMarker) removeUserLocationMarker(this.userLocationMarker);
		this.userLocationMarker = createUserLocationMarker(
			earth.mesh,
			earth.radiusScene,
			latitude,
			longitude
		);
	}

	clearUserLocation(): void {
		if (this.userLocationMarker) {
			removeUserLocationMarker(this.userLocationMarker);
			this.userLocationMarker = null;
		}
	}

	resize(width: number, height: number): void {
		this.renderer.setSize(width, height, false);
		this.composer.setSize(width, height);
		this.bloomPass.setSize(width, height);
		this.labelRenderer.setSize(width, height);
		this.camera.aspect = width / height;
		this.camera.updateProjectionMatrix();
		this.ctx.visibility.updateViewport(height);
		setTrailResolution(width, height);
	}

	dispose(): void {
		cancelAnimationFrame(this.rafId);
		this.pointerInteraction.detach();
		this.controls.removeEventListener('end', this.onControlsEnd);
		this.controls.dispose();
		this.renderer.dispose();
	}
}
