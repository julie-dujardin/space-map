import {
	AmbientLight,
	ArrowHelper,
	CanvasTexture,
	DirectionalLight as DirectionalLightClass,
	type DirectionalLight,
	Group,
	type Material,
	Mesh,
	PerspectiveCamera as PerspectiveCameraClass,
	type PerspectiveCamera,
	PointLight,
	Scene as SceneClass,
	type Scene,
	Sprite,
	SpriteMaterial,
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
import { UrlType, type MapViewState } from '$lib/state/view';
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
import { isModelBearing, loadBodyModel, makeModelEnvMap } from './objects/body/model';
import type { PointingSpec } from '$lib/math/orientation';
import { attachNomenclatureLabels, setActiveFeatureLabel } from './objects/surface/nomenclature';
import { buildTrails } from './objects/body/bulk';
import { makeCircleTexture } from './objects/pointcloud';
import { SystemDataLoader } from './system-data/loader';
import { loadSkybox } from './objects/sky/skybox';
import { SkyboxAdjuster } from './debug/skybox-adjust';
import { SkyDebugMarkers } from './debug/sky-markers';
import { HaloDebugOverlay } from './debug/halo-overlay';
import { collectDebugStats, type DebugStats } from './debug/stats';
import { PointCloudSystem, type CloudViewInfo } from './pointclouds/system';
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
import { ProbeCoverageWatch } from './probe-coverage-watch';
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
	/** Null until scene setup; fetches each focused probe's coverage lazily. */
	private coverageWatch: ProbeCoverageWatch | null = null;
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
	/** Debug ±XYZ axis arrows over the focused model; built lazily in the overlay. */
	private showPointingAxes = false;
	private pointingAxes: Group | null = null;

	private cameraUp!: CameraUpController;
	private skyboxAdjuster!: SkyboxAdjuster;
	private skyDebugMarkers!: SkyDebugMarkers;
	private haloDebug!: HaloDebugOverlay;

	private readonly focus: FocusState = {
		focusTruePos: [0, 0, 0],
		focusOriginWorld: [0, 0, 0],
		focusTargetWorld: [0, 0, 0],
		camOriginWorld: null,
		camTargetWorld: null,
		camTargetOffset: null,
		camOriginOffset: null,
		flyQ0: null,
		orbitFly: false,
		arcOrbit: false,
		cameraStaysOnBody: false,
		focusStartTime: 0,
		focusDurationMs: FOCUS_DURATION_MS
	};
	/** JD at which per-frame body positions were last computed. */
	private lastUpdatedJd = NaN;
	/** Tracks the focus's out-of-range state across frames so the camera pans onto
	 *  the parent only on the transition in, not every frame parked there. */
	private focusWasOutOfRange = false;
	private readonly _positionMapScratch = new Map<string, Vec3>();
	/** Landing body driven by the current landed focused probe; tracked so the
	 *  attach fires only on transitions (URL-direct, land/launch mid-session). */
	private landedNomBodyId: string | null = null;

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
		ctx.hasMeshBody = (id) => this.bodyObjects.has(id);
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
		this.haloDebug = new HaloDebugOverlay(this.canvas);
		this.skyboxAdjuster.set(0, 0, 0);
		void loadSkybox(this.scene, this.renderer, ctx);

		const sunBody = ctx.bodies.majorBodies.find((b) => b.data.id === SUN_ID);
		const matchedBody = ctx.getBody(initialView.id);
		// When the URL target isn't resident yet (e.g. an Earth sat whose element
		// chunk is still streaming), settle the camera on its parent body rather
		// than the Sun — a far gentler starting frame that MapPage eases onto the
		// real target from once it lands. Falls back to the Sun if even the parent
		// isn't loaded.
		const fallbackParentId = initialView.type === UrlType.EarthSatellite ? EARTH_ID : null;
		const fallbackBody =
			(fallbackParentId && ctx.bodies.majorBodies.find((b) => b.data.id === fallbackParentId)) ||
			sunBody;
		const focusBody = matchedBody ?? fallbackBody;
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

		this.coverageWatch = new ProbeCoverageWatch(clock);

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

		// Arm coverage-end stops before the clock advances so a forward tick
		// lands exactly on the focused probe's end_jd (and pauses) instead of
		// flying past into the no-data region.
		this.coverageWatch?.sync(this.focusController.current, this.clock.jd);

		// Gate body updates on jd actually changing — skips work while paused.
		this.clock.tick(performance.now());
		this.applyJdUpdate(true);

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

		// A flyby probe entering a planet's system mid-play (time advancing, not a
		// focus change) flips `focusedSystemId` inside updateCamera with no focus
		// event — without this the new system's textures never load and its bodies
		// render white. syncToFocus is idempotent (no-op until the barycenter changes).
		this.systemData.syncToFocus();

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
			this._tmpV3,
			// Camera moving (drag/inertia/fly): label screen positions shift many
			// px/frame, so the overlap cull must run every frame to stay in sync —
			// the throttled (every-3rd-frame) pass judges stale positions and lets
			// overlapping labels both stay maximized mid-motion. Throttle resumes
			// once the camera settles; clock-only drift at 1x is sub-pixel/frame.
			!controlsSettled
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

		if (this.haloDebug.active) {
			this.haloDebug.draw(
				this.bodyObjects,
				this.camera,
				this.focus.focusTruePos,
				this.focusController.current?.data.id,
				this.renderer.domElement.clientWidth,
				this.renderer.domElement.clientHeight
			);
		}
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

		// Debug axis arrows share the model's world attitude (model sits at the
		// overlay origin), drawn over it so the pointing config reads clearly.
		if (this.showPointingAxes) {
			if (!this.pointingAxes) {
				this.pointingAxes = this.buildPointingAxes();
				this.modelScene.add(this.pointingAxes);
			}
			this.pointingAxes.quaternion.copy(bo.model.quaternion);
			// Arrows are built at unit length; scale them to a constant angular size
			// (~0.45·overlayDist keeps tips inside the 60° overlay frame) so they stay
			// on-screen when the model is zoomed in enough to overflow, capped at 0.8
			// so they stay glued to the model when zoomed out.
			this.pointingAxes.scale.setScalar(Math.min(0.8, 0.45 * overlayDist));
			this.pointingAxes.visible = true;
		} else if (this.pointingAxes) {
			this.pointingAxes.visible = false;
		}

		this.renderer.autoClear = false;
		this.renderer.clearDepth();
		this.renderer.render(this.modelScene, this.modelCamera);
		this.renderer.autoClear = true;
	}

	/** View geometry for the point clouds' subpixel solve gate. Camera position is
	 *  already focus-relative (controls target is the origin); pxPerRad converts an
	 *  angular size at the camera into CSS pixels from the vertical FOV + height. */
	private cloudViewInfo(): CloudViewInfo {
		const cam = this.camera.position;
		const height = this.renderer.domElement.clientHeight || 1;
		const halfFov = (this.camera.fov * Math.PI) / 360;
		return {
			camPos: [cam.x, cam.y, cam.z],
			pxPerRad: height / 2 / Math.tan(halfFov)
		};
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
		// On resolve the body's radius may have been true-sized from the model's
		// scale_meters; refresh closest-approach so zoom-in tracks real size.
		void loadBodyModel(bo, this.modelScene, this.ctx).then(() => {
			if (this.focusController.current?.data.id === bo.body.data.id) {
				this.controls.minDistance = minCameraDistance(bo.body);
			}
		});
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

	/** Attach landing-body nomenclature when the focused probe is landed —
	 *  catches URL-direct focus (no position update yet) and land/launch transitions. */
	private syncLandedNomenclature(): void {
		const focused = this.focusController.current;
		const fbo = focused ? this.bodyObjects.get(focused.data.id) : undefined;
		const landingId = fbo?.isLanded ? focused!.data.parentId : null;
		if (landingId === this.landedNomBodyId) return;
		this.landedNomBodyId = landingId;
		if (!landingId) return;
		const landingBody = this.ctx.getBody(landingId);
		if (landingBody) this.maybeLoadTexture(landingBody);
	}

	clearUserPromoted(): void {
		this.focusController.promotion.clearUserPromoted();
	}

	/** Process a pending jd change now instead of next frame, re-anchoring focus to
	 *  the current body's new-time position. No-op when jd is already current.
	 *  `allowOorRefocus` (tick loop only) pans onto the parent when a seek lands
	 *  where the focus no longer exists. */
	private applyJdUpdate(allowOorRefocus = false): void {
		if (this.clock.jd === this.lastUpdatedJd) {
			this.clock.seeked = false;
			return;
		}
		const seeked = this.clock.seeked;
		this.clock.seeked = false;
		this.lastUpdatedJd = this.clock.jd;
		this.ctx.refreshTick(jdToDate(this.clock.jd));
		const result = updatePositions({
			jd: this.clock.jd,
			ctx: this.ctx,
			bodyObjects: this.bodyObjects,
			focus: this.focus,
			focusedBody: this.focusController.current,
			positionMap: this._positionMapScratch,
			diagnostics: this.positionDiagnostics
		});
		this.pointClouds.updateForJd(this.clock.jd, this.cloudViewInfo());
		// stepFocusAnimation handles repositionAll while animating.
		const elapsed = performance.now() - this.focus.focusStartTime;
		if (elapsed >= this.focus.focusDurationMs) {
			this.repositionBodies();
			this.pointClouds.maybeRebase();
		}
		this.syncLandedNomenclature();

		// A seek just landed where the focus has no data — pan the camera onto the
		// in-range ancestor it's now tracking. Only on the transition into
		// out-of-range: the focus (and its "no data at this time" toast) stays on
		// the original body, so it keeps firing while parked here. Once per episode.
		const enteringOutOfRange = result.focusedOutOfRange && !this.focusWasOutOfRange;
		this.focusWasOutOfRange = result.focusedOutOfRange;
		if (allowOorRefocus && seeked && enteringOutOfRange && result.reanchorId) {
			const anchor = this.ctx.getBody(result.reanchorId);
			if (anchor) this.focusController.panCameraToBody(anchor);
		}
	}

	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		// Settle a pending time jump first so the fly starts from the focus's
		// new-time position, not its pre-jump one (else it swoops the orbital arc).
		this.applyJdUpdate();
		this.focusWasOutOfRange = false;
		return this.focusController.focusOnBody(id, zoom, latitude, longitude);
	}

	snapToBodyFrame(latitude: number, longitude: number, zoom: number): void {
		this.focusController.snapToBodyFrame(latitude, longitude, zoom);
	}

	snapToBodyFacing(id: string, towardId: string, elevationDeg: number, distance: number): void {
		this.focusController.snapToBodyFacing(id, towardId, elevationDeg, distance);
	}

	snapToBody(id: string, latitude: number, longitude: number, zoom: number): void {
		this.focusController.snapToBody(id, latitude, longitude, zoom);
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.applyJdUpdate();
		this.focusWasOutOfRange = false;
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

	/** Debug: the focused body's natural pointing (config or south-default,
	 *  ignoring any live override) and whether the per-frame loop applies it
	 *  (model-bearing). `base` is always populated so the panel can label its
	 *  "default (…)" options with the current values. */
	getFocusedPointing(): { supported: boolean; base: PointingSpec } | null {
		const body = this.focusController.current;
		if (!body) return null;
		const base = body.pointing ?? { primary: { axis: '-y', target: 'parent' } };
		return { supported: isModelBearing(body), base };
	}

	/** Debug: override the focused body's pointing live (null clears it, restoring
	 *  the config/default). Re-focusing reloads the config value. */
	setFocusedPointing(spec: PointingSpec | null): void {
		const body = this.focusController.current;
		if (body) body.pointingOverride = spec ?? undefined;
	}

	/** Debug: overlay ±XYZ body-axis arrows on the focused model (x=red,
	 *  y=green, z=blue; negatives dimmed) so the pointing config is legible. */
	setPointingAxesVisible(visible: boolean): void {
		this.showPointingAxes = visible;
	}

	private buildPointingAxes(): Group {
		const g = new Group();
		const O = new Vector3(0, 0, 0);
		// Built at unit length; renderModelOverlay scales the group per-frame to a
		// constant angular size so the arrows stay inside the overlay frame.
		const add = (dir: Vector3, color: number, label: string, labelColor: string) => {
			const arrow = new ArrowHelper(dir, O, 1, color, 0.22, 0.12);
			// Draw over the model so the arrows never hide inside its geometry.
			(arrow.line.material as Material).depthTest = false;
			(arrow.cone.material as Material).depthTest = false;
			arrow.renderOrder = 999;
			g.add(arrow);
			const tag = this.makeAxisLabel(label, labelColor);
			tag.position.copy(dir).multiplyScalar(1.12);
			g.add(tag);
		};
		add(new Vector3(1, 0, 0), 0xff4444, '+X', '#ff9999');
		add(new Vector3(-1, 0, 0), 0x884444, '-X', '#cc7777');
		add(new Vector3(0, 1, 0), 0x44ff44, '+Y', '#99ff99');
		add(new Vector3(0, -1, 0), 0x448844, '-Y', '#77cc77');
		add(new Vector3(0, 0, 1), 0x4488ff, '+Z', '#99bbff');
		add(new Vector3(0, 0, -1), 0x445588, '-Z', '#7799cc');
		return g;
	}

	/** Camera-facing text sprite for an axis arrow tip, drawn over the model. */
	private makeAxisLabel(text: string, color: string): Sprite {
		const size = 128;
		const canvas = document.createElement('canvas');
		canvas.width = canvas.height = size;
		const cx = canvas.getContext('2d')!;
		cx.font = 'bold 72px sans-serif';
		cx.textAlign = 'center';
		cx.textBaseline = 'middle';
		cx.fillStyle = color;
		cx.fillText(text, size / 2, size / 2);
		const mat = new SpriteMaterial({
			map: new CanvasTexture(canvas),
			depthTest: false,
			transparent: true
		});
		const sprite = new Sprite(mat);
		sprite.scale.setScalar(0.175);
		sprite.renderOrder = 1000;
		return sprite;
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

	/** Toggle the virtual-halo debug overlay (label-anchor silhouette discs). */
	setHaloDebugVisible(visible: boolean): void {
		this.haloDebug.setVisible(visible);
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
		this.haloDebug.dispose();
		this.renderer.dispose();
	}
}
