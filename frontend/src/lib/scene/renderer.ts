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
	PlaneGeometry,
	PointLight,
	Raycaster,
	Scene as SceneClass,
	type Scene,
	ShadowMaterial,
	Sprite,
	SpriteMaterial,
	TextureLoader,
	Vector2,
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
import {
	isSurfaceFeature,
	ObjectType,
	type FeatureAnchor,
	type PositionedBody
} from '$lib/types/objects';
import { makeFeatureBody, seatFeatureBody } from './focus/feature-focus';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import { AU_SCALE, kmToScene } from '$lib/math/units';
import { EARTH_ID, SUN_ID } from '$lib/constants';
import { bootThree, CAMERA_FAR_DEFAULT } from './setup/three-boot';
import { isReversedDepth } from './setup/depth-mode';
import { cappedPixelRatio } from '$lib/device';
import { PointerInteraction } from './interaction/pointer';
import { GpuPickPass } from './interaction/gpu-pick';
import { CameraUpController } from './camera/up-controller';
import { jdToDate } from '$lib/format/date';
import { buildMajorBodies } from './objects/body/lifecycle';
import {
	ATMOSPHERE_PARAMS,
	applyAtmosphereParams,
	type AtmosphereParams
} from './objects/surface/atmosphere';
import { loadBodyTexture, unloadBodyTexture } from './objects/body/textures';
import { applyOrientation, bodyQuaternion } from '$lib/math/orientation';
import {
	isModelBearing,
	loadBodyModel,
	unloadBodyModel,
	modelUnitScene
} from './objects/body/model';
import {
	AMBIENT_BOOST_INTENSITY,
	AMBIENT_INTENSITY,
	ENV_BASE_INTENSITY,
	SUN_LIGHT_INTENSITY,
	makeEnvMap,
	sunIrradianceFactor
} from './lighting';
import { getSettings } from '$lib/state/settings.svelte';
import type { PointingSpec } from '$lib/math/orientation';
import {
	attachNomenclatureLabels,
	nomenclatureBodyId,
	setActiveFeatureLabel
} from './objects/surface/nomenclature';
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
import {
	type FocusState,
	FOCUS_DURATION_MS,
	prepareFlyToCamera,
	stepFocusAnimation
} from './animation/focus';
import { FocusController } from './focus/controller';
import { ProbeCoverageWatch } from './probe-coverage-watch';
import { minCameraDistance, clampCameraOutsideBody } from './visibility/camera-limits';
import { renderedSurfaceRadialKm, surfaceDataEpoch } from './position/rendered-surface';
import { collisionParentId } from './state/bodies.svelte';
import { updateBodyVisibility } from './visibility/update';
import { createUserLocationMarker, removeUserLocationMarker } from './user-location/marker';
import { updateUserLocationOcclusion } from './user-location/occlusion';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

/** OrbitControls inertia. The reduced-motion factor is far higher so the camera
 *  stops promptly on release instead of coasting (three's default is 0.05). */
const DEFAULT_DAMPING = 0.05;
const REDUCED_MOTION_DAMPING = 0.4;

/** Depth-far tuning for subsystem views (see {@link SceneRenderer.updateDepthFar}). */
const FAR_MARGIN = 1.2; // headroom past the farthest anchor so its halo isn't clipped
const FAR_MIN = kmToScene(1e6); // floor: never squeeze far below a planetary system's own extent
/** Skip the projection-matrix rebuild until far drifts more than this fraction. */
const FAR_UPDATE_EPS = 0.02;

/** Tight-far regime: camera within ~1 focused-body radius of the surface
 *  (< 2 radii from centre). The Sun leaves the far computation (a scaled proxy
 *  stands in — {@link SceneRenderer.updateSunProxy}) and heliocentric trails
 *  hide. Looser release keeps the trail from flickering at the boundary. */
const TIGHT_FAR_ENGAGE = 2;
const TIGHT_FAR_RELEASE = 2.3;
/** Proxy-Sun distance as a fraction of far. Below 1/FAR_MARGIN, so the proxy
 *  sits beyond every in-system body and depth-sorts behind them (e.g. a moon
 *  transiting the disc). */
const SUN_PROXY_FAR_FRACTION = 0.9;

export class SceneRenderer {
	private renderer: WebGLRenderer;
	private composer: EffectComposer;
	private bloomPass: UnrealBloomPass;
	private labelRenderer: ThrottledCSS2DRenderer;
	private scene: Scene;
	private camera: PerspectiveCamera;
	private controls: OrbitControls;
	private pointerInteraction!: PointerInteraction;
	private gpuPick!: GpuPickPass;

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
	/** Contact-shadow receiver for landed probes — an invisible `ShadowMaterial`
	 *  plane at the surface, so the rover casts a soft shadow onto the terrain. */
	private modelShadowPlane: Mesh | null = null;
	private readonly _tmpUp = new Vector3();
	private readonly _tmpSun = new Vector3();
	private readonly _planeNormal = new Vector3(0, 0, 1);
	private readonly _modelRaycaster = new Raycaster();
	private readonly _pickNdc = new Vector2();
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
	/** Focused system at the last position update. A change re-runs updatePositions
	 *  even when jd is frozen: out-of-system moons are skipped and left stale, so
	 *  entering their system while paused must recompute them or they render detached. */
	private lastUpdatedSystemId: string | null = null;
	/** Focused landed probe's / surface feature's seat config at the last position update. */
	private lastSeatConfigKey: string | null = null;
	private lastProbeVersion = 0;
	/** Tracks the focus's out-of-range state across frames so the camera pans onto
	 *  the parent only on the transition in, not every frame parked there. */
	private focusWasOutOfRange = false;
	private readonly _positionMapScratch = new Map<string, Vec3>();
	/** Landing body driven by the current landed focused probe; tracked so the
	 *  attach fires only on transitions (URL-direct, land/launch mid-session). */
	private landedNomBodyId: string | null = null;

	private rafId = 0;
	private paused = false;
	private firstFrame = true;
	private pendingUrlWrite = false;
	/** Ring buffer of recent tick timestamps; fps = (n-1) / (last - first). */
	private static readonly FPS_SAMPLE_FRAMES = 30;
	private fpsSamples: number[] = [];
	private fpsSampleHead = 0;
	private readonly textureLoader = new TextureLoader();
	private readonly shadowLight: DirectionalLight;
	/** Both scenes' ambient fills; driven together by the high-ambient toggle. */
	private readonly ambientLights: AmbientLight[];
	private sunPointLight: PointLight | undefined;
	/** Tight-far regime active (see TIGHT_FAR_ENGAGE / updateDepthFar). */
	private tightFar = false;
	/** Current proxy-Sun scale factor; 1 = Sun rendered at its true position. */
	private sunProxyK = 1;
	private sunBaseMeshScale = 1;
	private sunBaseCoronaScale = 0;
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
		this.modelScene.environment = makeEnvMap(this.renderer);
		this.modelScene.environmentIntensity = ENV_BASE_INTENSITY;
		this.modelCamera = new PerspectiveCameraClass(60, 1, 0.01, 1000);
		this.modelScene.add(this.modelCamera);
		const modelAmbient = new AmbientLight(0xffffff, AMBIENT_INTENSITY);
		this.modelScene.add(modelAmbient);
		this.ambientLights = [boot.ambientLight, modelAmbient];
		this.modelLight = new DirectionalLightClass(0xffffff, SUN_LIGHT_INTENSITY);
		// Light sits at distance 10 from the unit-radius model. Frustum reaches well
		// past the silhouette (deep near/far especially) so a grazing-Sun shadow
		// streaking along the light axis isn't clipped; 4096² keeps it crisp.
		this.modelLight.castShadow = true;
		this.modelLight.shadow.mapSize.set(4096, 4096);
		this.modelLight.shadow.camera.left = -4;
		this.modelLight.shadow.camera.right = 4;
		this.modelLight.shadow.camera.top = 4;
		this.modelLight.shadow.camera.bottom = -4;
		this.modelLight.shadow.camera.near = 4;
		this.modelLight.shadow.camera.far = 28;
		this.modelLight.shadow.bias = -0.0001;
		this.modelLight.shadow.normalBias = 0.02;
		this.modelScene.add(this.modelLight);
		this.modelScene.add(this.modelLight.target);

		// Invisible except under the model's shadow, so only the contact shadow
		// composites onto the terrain.
		this.modelShadowPlane = new Mesh(
			new PlaneGeometry(40, 40),
			new ShadowMaterial({ opacity: 0.55 })
		);
		this.modelShadowPlane.receiveShadow = true;
		this.modelShadowPlane.visible = false;
		this.modelScene.add(this.modelShadowPlane);

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
		this.controls.dampingFactor = getSettings().resolvedReducedMotion
			? REDUCED_MOTION_DAMPING
			: DEFAULT_DAMPING;
		this.controls.minDistance = focusBody ? minCameraDistance(focusBody) : kmToScene(0.01);
		this.controls.maxDistance = 31_620.5 * AU_SCALE; // 0.5 light-year
		this.controls.target.set(0, 0, 0);
		this.controls.update();
		this.controls.addEventListener('end', this.onControlsEnd);

		this.cameraUp = new CameraUpController(this.camera, this.controls, ctx, (id) =>
			Boolean(this.bodyObjects.get(id)?.isLanded)
		);

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

		this.gpuPick = new GpuPickPass(this.renderer, this.camera);
		this.pointerInteraction = new PointerInteraction(
			canvas,
			this.camera,
			ctx,
			clock,
			this.focus,
			this.clickables,
			this.meshToBody,
			(body) => this.focusController.handleFocus(body),
			(ndcX, ndcY) => this.pickFocusedModel(ndcX, ndcY),
			this.gpuPick,
			() => [...this.pointClouds.asteroids().values(), ...this.pointClouds.spacecraft().values()],
			this.pointClouds.pickRegistry
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

		// Keep the camera from tunnelling into the focused object's parent (e.g.
		// Earth while focused on the ISS): minDistance only guards the focused body
		// itself, but the orbit sphere around a low orbiter dips below its parent.
		// The clamp caps its wall at the focused object's own radial distance, so a
		// low orbiter stays reachable without clipping the parent; a landed probe
		// or surface feature gets a floor on the rendered terrain under the camera.
		const focused = this.focusController.current;
		if (focused) {
			const parentId = collisionParentId(focused.data.parentId);
			const parent = parentId ? this.ctx.getBody(parentId) : undefined;
			const seated =
				Boolean(this.bodyObjects.get(focused.data.id)?.isLanded) || isSurfaceFeature(focused);
			if (parent) {
				const parentBo = this.bodyObjects.get(parent.data.id);
				// Model-bearing hosts render the shape model, not the sphere mesh the
				// terrain sampler mirrors — fall back to the seat-radius shell there.
				const landedCtx =
					seated && parent.orientation && !parentBo?.model
						? {
								invQuat: bodyQuaternion(parent.orientation, this.clock.jd, parent.nutPrec).invert(),
								radialKm: (dir: [number, number, number]) =>
									renderedSurfaceRadialKm(parentBo, parent.data.id, parent.data.radiusKm, dir)
							}
						: undefined;
				clampCameraOutsideBody(this.camera, parent, this.focus.focusTruePos, landedCtx);
			}
		}

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
		this.updateTightFar(distance);

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
			!controlsSettled,
			this.tightFar
		);

		// Catches lines updatePositions skipped (visible=false) that updateBodyVisibility
		// just flipped on, so they don't render at a stale basis for one frame.
		refreshDeferredTrails(this.bodyObjects, this.focus, this.lastUpdatedJd);

		updateRingShaders(this.bodyObjects, this.focus.focusTruePos, getSettings().realisticLighting);
		updateAtmosphereShaders(
			this.bodyObjects,
			this.camera.position,
			getSettings().showAtmospheres,
			getSettings().realisticLighting,
			this.sunIntensityScale
		);
		updateEclipseUniforms(this.bodyObjects, this.focus.focusTruePos);

		// High-ambient toggle: flat fill so night sides stay visible for inspection.
		// The base fill stands in for scattered sunlight, so realistic mode scales
		// it with the focus body's solar distance — otherwise it exceeds direct
		// sunlight past ~Saturn and night sides read brighter than day sides. The
		// high-ambient boost stays unscaled: it exists to defeat darkness.
		let ambient = getSettings().highAmbient ? AMBIENT_BOOST_INTENSITY : AMBIENT_INTENSITY;
		if (!getSettings().highAmbient && getSettings().realisticLighting) {
			const sunPos = this.bodyObjects.get(SUN_ID)?.body.position;
			if (sunPos && this.ctx.visibility.activeSystemId) {
				const [fx, fy, fz] = this.focus.focusTruePos;
				ambient *= sunIrradianceFactor(Math.hypot(sunPos[0] - fx, sunPos[1] - fy, sunPos[2] - fz));
			}
		}
		for (const light of this.ambientLights) light.intensity = ambient;

		updateUserLocationOcclusion(this.userLocationMarker, this.bodyObjects, this.camera);

		// Terrain/texture LOD follow the surface the camera actually orbits: a
		// focused landed probe or surface feature resolves to its host body.
		const focusedIdLod = nomenclatureBodyId(this.focusController.current, this.bodyObjects);
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
			this._tmpV3,
			getSettings().realisticLighting,
			this.sunIntensityScale
		);

		// One point-cloud upload per frame to spread GPU cost. Auto-promotion
		// now happens push-style at chunk-arrival time (PromotionRegistry
		// listens on `BodyIndex.onBodiesAdded`).
		this.pointClouds.drainOnePendingSceneAdd();

		this.updateDepthFar();
		this.updateSunProxy();

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

	/** Hysteresis gate for the tight-far regime (`distance` = camera to focus,
	 *  scene units). A focused landed probe or surface feature has ~zero radius
	 *  of its own — the host body whose terrain the camera orbits is the scale
	 *  that matters, measured from its centre (the focus sits on the surface). */
	private updateTightFar(distance: number): void {
		// Reversed-Z precision is distance-relative — no far squeeze needed, the
		// real Sun and heliocentric trails stay renderable at any zoom.
		if (isReversedDepth()) return;
		const focused = this.focusController.current;
		const anchorId = focused ? nomenclatureBodyId(focused, this.bodyObjects) : undefined;
		const anchorBo = anchorId ? this.bodyObjects.get(anchorId) : undefined;
		const radius = anchorBo?.radiusScene ?? 0;
		let dist = distance;
		if (focused && anchorBo && anchorId !== focused.data.id) {
			const [fx, fy, fz] = this.focus.focusTruePos;
			const [bx, by, bz] = anchorBo.body.position;
			const cam = this.camera.position;
			dist = Math.hypot(fx + cam.x - bx, fy + cam.y - by, fz + cam.z - bz);
		}
		const bound = this.tightFar ? TIGHT_FAR_RELEASE : TIGHT_FAR_ENGAGE;
		this.tightFar =
			radius > 0 && this.ctx.visibility.activeSystemId !== null && dist < radius * bound;
	}

	/**
	 * Pull the far plane in when zoomed into a subsystem. Log-depth precision
	 * scales as 1/log2(far+1) — near is irrelevant — so collapsing far from the
	 * ~0.5 ly default sharply cuts z-fighting in close-up terrain. Bodies
	 * outside the active system are hidden while zoomed in and mustn't hold the
	 * plane out. Normally the Sun dominates far; in the tight-far regime it
	 * drops out too (updateSunProxy stands in) and the system-extent term keeps
	 * sibling-moon orbit trails inside the plane — a body position alone says
	 * nothing about its trail's far side.
	 */
	private updateDepthFar(): void {
		if (isReversedDepth()) return;
		let far = CAMERA_FAR_DEFAULT;
		const sysId = this.ctx.visibility.activeSystemId;
		if (sysId) {
			const [fx, fy, fz] = this.focus.focusTruePos;
			// Seed with the camera's own reach so we never clip what we're looking at.
			let maxDistSq = this.camera.position.lengthSq();
			const consider = (pos: [number, number, number]) => {
				const dx = pos[0] - fx;
				const dy = pos[1] - fy;
				const dz = pos[2] - fz;
				const d2 = dx * dx + dy * dy + dz * dz;
				if (d2 > maxDistSq) maxDistSq = d2;
			};
			const sunBo = this.bodyObjects.get(SUN_ID);
			if (this.tightFar) {
				// Any in-system orbit stays within apoapsis < 2·a of the root.
				const root = this.bodyObjects.get(sysId)?.body;
				if (root) {
					const rootDist = Math.hypot(
						root.position[0] - fx,
						root.position[1] - fy,
						root.position[2] - fz
					);
					const reach = rootDist + this.ctx.bodies.getSystemExtent(sysId) * AU_SCALE * 2;
					maxDistSq = Math.max(maxDistSq, reach * reach);
				}
			} else {
				// The Sun stays lit and visible from inside a subsystem
				// (hasFullRendering excludes it) — keep it in range.
				if (sunBo) consider(sunBo.body.position);
			}
			// Everything rendered while zoomed in holds the far plane — bodyObjects,
			// not ctx.bodies.majorBodies, so in-system probes (JWST from the Moon)
			// and L-point markers count too. Out-of-system bodies fail
			// hasFullRendering; their sub-pixel meshes clip harmlessly.
			for (const bo of this.bodyObjects.values()) {
				if (this.ctx.visibility.hasFullRendering(bo.body)) consider(bo.body.position);
			}
			far = Math.min(CAMERA_FAR_DEFAULT, Math.max(FAR_MIN, Math.sqrt(maxDistSq) * FAR_MARGIN));
		}
		if (Math.abs(far - this.camera.far) > this.camera.far * FAR_UPDATE_EPS) {
			this.camera.far = far;
			this.camera.updateProjectionMatrix();
		}
	}

	/**
	 * Stand-in Sun for the tight-far regime: re-seat the Sun's visuals at
	 * SUN_PROXY_FAR_FRACTION × far along the true direction, scaled by the same
	 * factor — angular size and surface brightness are distance-invariant, so
	 * disc, corona, and bloom render pixel-identical. Lighting and the
	 * eclipse/atmosphere/shadow uniforms read the true `body.position` and are
	 * unaffected (the PointLight rides along at zero intensity in subsystems).
	 * Must run after updateDepthFar (this frame's far) and after
	 * repositionBodies (so this write wins).
	 */
	private updateSunProxy(): void {
		const sunBo = this.bodyObjects.get(SUN_ID);
		if (!sunBo) return;
		const [fx, fy, fz] = this.focus.focusTruePos;
		const [sx, sy, sz] = sunBo.body.position;
		const rx = sx - fx;
		const ry = sy - fy;
		const rz = sz - fz;
		let k = 1;
		if (this.tightFar) {
			const proxyDist = this.camera.far * SUN_PROXY_FAR_FRACTION;
			const trueDist = Math.hypot(rx, ry, rz);
			if (trueDist > proxyDist) k = proxyDist / trueDist;
		}
		// k = 1 with no proxy applied: positions are repositionBodies' — nothing to do.
		if (k === 1 && this.sunProxyK === 1) return;
		if (this.sunProxyK === 1) {
			// Entering the regime: capture bases (mesh scale may carry PCK radii).
			this.sunBaseMeshScale = sunBo.mesh?.scale.x ?? 1;
			this.sunBaseCoronaScale = sunBo.corona?.scale.x ?? 0;
		}
		sunBo.group.position.set(rx * k, ry * k, rz * k);
		for (const obj of sunBo.extraObjects) obj.position.set(rx * k, ry * k, rz * k);
		sunBo.mesh?.scale.setScalar(this.sunBaseMeshScale * k);
		sunBo.corona?.scale.set(this.sunBaseCoronaScale * k, this.sunBaseCoronaScale * k, 1);
		this.sunProxyK = k;
	}

	/**
	 * Composite the focused body's 3D model on top of the main render. The model
	 * lives in `modelScene` at unit scale; the overlay camera mirrors the main
	 * camera's orientation at a distance that keeps the model's screen footprint
	 * matching what the body sphere occupied, with tight near/far for depth.
	 */
	private renderModelOverlay(): void {
		const focusBody = this.focusController.current;
		if (!focusBody) return;
		// A focused surface feature has no model of its own — its host carries the
		// overlay model the camera is orbiting.
		const modelId = isSurfaceFeature(focusBody)
			? focusBody.featureAnchor!.hostId
			: focusBody.data.id;
		const bo = this.bodyObjects.get(modelId);
		if (!bo?.model) return;

		// Seat a landed probe on its feet at the surface (origin) so it rests on the
		// terrain, not bbox-centred half-buried; flying probes stay centred.
		const fit = bo.model.userData as { centerOffset?: Vector3; feetOffset?: Vector3 };
		if (bo.isLanded && fit.feetOffset) {
			bo.model.position
				.copy(fit.feetOffset)
				.applyQuaternion(bo.model.quaternion)
				.multiplyScalar(-1);
		} else if (fit.centerOffset) {
			bo.model.position.copy(fit.centerOffset).multiplyScalar(-1);
		}

		// Mirror the overlay camera off the body's render-space position, not the
		// focus origin — during flies focusTruePos lags the body's true motion and
		// the model would render displaced from the main-scene body (labels detach).
		this._tmpV3.copy(this.camera.position).sub(bo.group.position);
		const camDist = this._tmpV3.length();
		// Model is normalised to radius 1 in modelScene; this overlayDist makes it
		// subtend exactly what the radiusScene sphere would, so the model renders
		// true-to-scale and label occlusion/anchoring can mirror it via modelUnitScene.
		const overlayDist = camDist / modelUnitScene(bo);
		this.modelCamera.position.copy(this._tmpV3).normalize().multiplyScalar(overlayDist);
		this.modelCamera.quaternion.copy(this.camera.quaternion);
		this.modelCamera.aspect = this.camera.aspect;
		this.modelCamera.near = Math.max(0.01, overlayDist - 5);
		this.modelCamera.far = overlayDist + 50;
		this.modelCamera.updateProjectionMatrix();

		// Sun direction in the overlay = (sun - focus) normalised, applied as
		// the directional light position (target at origin, distance arbitrary).
		const sunBody = this.bodyObjects.get(SUN_ID)?.body;
		let irradiance = 1;
		if (sunBody) {
			const [sx, sy, sz] = sunBody.position;
			const [fx, fy, fz] = bo.body.position;
			this._tmpSun.set(sx - fx, sy - fy, sz - fz);
			if (getSettings().realisticLighting) irradiance = sunIrradianceFactor(this._tmpSun.length());
			this._tmpSun.normalize();
			this.modelLight.position.copy(this._tmpSun).multiplyScalar(10);
		}

		// Contact shadow only for a landed probe in local daytime (nothing to cast
		// onto in flight, unlit at night). Tilt the receiver to the local tangent —
		// model +Y is up under the nadir orientation.
		if (this.modelShadowPlane) {
			this._tmpUp.set(0, 1, 0).applyQuaternion(bo.model.quaternion);
			const daytime = this._tmpSun.dot(this._tmpUp) > 0.03;
			this.modelShadowPlane.visible = Boolean(bo.isLanded) && daytime;
			if (this.modelShadowPlane.visible) {
				this.modelShadowPlane.quaternion.setFromUnitVectors(this._planeNormal, this._tmpUp);
			}
		}

		// Dim the sun by the analytical eclipse occlusion at the focused body's center.
		this._tmpV3.set(0, 0, 0);
		const factor = evaluateEclipseFactor(this._tmpV3, this._tmpV3) * irradiance;
		this.modelLight.intensity = SUN_LIGHT_INTENSITY * factor * this.sunIntensityScale;
		this.modelScene.environmentIntensity = ENV_BASE_INTENSITY * factor;

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

	/** Keyboard camera step (canvas arrow keys / zoom keys). Angles in radians;
	 *  `dolly` > 1 zooms in. Goes through OrbitControls so damping and
	 *  min/maxDistance clamping apply, but fires no 'end' event — sync the URL
	 *  here like a pointer drag would. */
	nudgeCamera(azimuth: number, polar: number, dolly: number): void {
		if (azimuth !== 0) this.controls.rotateLeft(azimuth);
		if (polar !== 0) this.controls.rotateUp(polar);
		// dollyIn scales the orbit radius by its argument, so zooming in needs <1.
		if (dolly !== 1) this.controls.dollyIn(1 / dolly);
		this.onControlsEnd();
	}

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
		//
		// Nomenclature labels are focus-scoped and idempotent. They wait on the
		// model load: shape-model bodies ray-cast the mesh for feature placement.
		// Re-tag the active label after attach: `setSelectedFeature` may have run
		// while labels weren't on `bo` yet (URL-load case) and no-op'd.
		void loadBodyModel(bo, this.modelScene, this.ctx)
			.then(() => {
				if (this.focusController.current?.data.id === bo.body.data.id) {
					this.controls.minDistance = minCameraDistance(bo.body);
				}
				return attachNomenclatureLabels(bo, this.canvas, (featureId, lat, lon, diameterM) =>
					this.callbacks.onFeatureSelect?.(bo.body.data.id, featureId, lat, lon, diameterM)
				);
			})
			.then(() => {
				if (this.selectedFeatureId !== null) setActiveFeatureLabel(bo, this.selectedFeatureId);
			});
	}

	/** Debug: rebuild the focused body's render stack so the current body-layer
	 *  toggles (shape mesh / texture / displacement / self-shadow) take effect.
	 *  Tears the appearance down and re-runs the focus load path, which reads the
	 *  flags as it rebuilds. No-op with nothing focused. */
	reapplyBodyLayers(): void {
		const focused = this.focusController.current;
		if (!focused) return;
		const bo = this.bodyObjects.get(focused.data.id);
		if (!bo) return;
		unloadBodyModel(bo);
		unloadBodyTexture(bo);
		this.maybeLoadTexture(focused);
	}

	/** Update which surface-feature label renders as "active" (larger, bolder).
	 *  Tracked on the renderer so a body's labels picked up after a fly-in still
	 *  see the right selection. */
	setSelectedFeature(featureId: number | null): void {
		this.selectedFeatureId = featureId;
		// The labels live on the host body when a feature/landed probe is focused.
		const nomId = nomenclatureBodyId(this.focusController.current, this.bodyObjects);
		const bo = nomId ? this.bodyObjects.get(nomId) : undefined;
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

	/** Rendered-mesh state a landed probe's or surface feature's seat is keyed on
	 *  (host grid incl. window recenters + the bound height texture + async
	 *  surface-data epoch); null when the focus can't be seated. Gated on the
	 *  focus being a spacecraft or feature, not `isLanded`: that flag is itself
	 *  only set by a position pass, which is exactly what this key must force. */
	private focusedSeatConfigKey(): string | null {
		const focused = this.focusController.current;
		if (!focused) return null;
		if (focused.data.objectType !== ObjectType.SPACECRAFT && !isSurfaceFeature(focused))
			return null;
		const parentId = collisionParentId(focused.data.parentId);
		const bo = parentId ? this.bodyObjects.get(parentId) : undefined;
		if (!bo) return null;
		const tw = bo.terrainWindow;
		const grid = tw
			? `w${tw.stepLevel}x${tw.texWidth}@${tw.centerTheta.toFixed(6)},${tw.centerPhi.toFixed(6)}`
			: `u${bo.currentSegments ?? 128}`;
		return `${grid}|${bo.displacementMap?.uuid ?? 'none'}|${surfaceDataEpoch()}`;
	}

	/** Process a pending jd change now instead of next frame, re-anchoring focus to
	 *  the current body's new-time position. No-op when jd is already current.
	 *  `allowOorRefocus` (tick loop only) pans onto the parent when a seek lands
	 *  where the focus no longer exists. */
	private applyJdUpdate(allowOorRefocus = false): void {
		// Recompute on a focused-system change too, not just a jd change: moons
		// outside the focused system are skipped and their world positions freeze.
		// Likewise on a seat config change: the host body's mesh upgrades on
		// camera-driven schedules (sphere LOD, terrain window, DEM tier) with no
		// jd change, and a paused clock would strand the probe/feature on a seat
		// computed against the boot-time mesh. Probe-chunk arrival is a trigger
		// too: a deep link boots paused, and the boot pass runs before the
		// records exist — without it the probe stays wherever that first pass
		// left it (e.g. inside the planet, unlanded).
		const systemId = this.ctx.visibility.focusedSystemId;
		const seatKey = this.focusedSeatConfigKey();
		const probeVersion = this.ctx.probeStore?.version ?? 0;
		if (
			this.clock.jd === this.lastUpdatedJd &&
			systemId === this.lastUpdatedSystemId &&
			seatKey === this.lastSeatConfigKey &&
			probeVersion === this.lastProbeVersion
		) {
			this.clock.seeked = false;
			return;
		}
		const seeked = this.clock.seeked;
		this.clock.seeked = false;
		this.lastUpdatedJd = this.clock.jd;
		this.lastUpdatedSystemId = systemId;
		this.lastSeatConfigKey = seatKey;
		this.lastProbeVersion = probeVersion;
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

	/** Reduced motion: shorten orbit inertia so the camera stops promptly on release. */
	setReducedMotion(on: boolean): void {
		this.controls.dampingFactor = on ? REDUCED_MOTION_DAMPING : DEFAULT_DAMPING;
	}

	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		// Settle a pending time jump first so the fly starts from the focus's
		// new-time position, not its pre-jump one (else it swoops the orbital arc).
		this.applyJdUpdate();
		this.focusWasOutOfRange = false;
		return this.focusController.focusOnBody(id, zoom, latitude, longitude);
	}

	/**
	 * Focus a surface feature as a real orbitable body seated on its host. `mode`:
	 *  - `pan`: keep the camera put and re-aim onto the seat (a label click — the
	 *    feature is already on screen, so no camera move is wanted).
	 *  - `frame`: move to a `zoom`-scene-unit standoff along the local zenith. When
	 *    already on this host (parent or a sibling feature focused) it arcs around
	 *    at constant radius so the path can't cut a chord through the body;
	 *    arriving from a different object it flies in.
	 *  - `snap`: settle at that framing instantly, for URL deep-links. `view`
	 *    (the URL's `at=`, seat-relative) overrides the zenith standoff so a
	 *    shared link restores the exact camera.
	 * The camera then orbits/zooms the seat like any body; `updatePositions`
	 * re-seats it each frame. Returns the animation duration (ms).
	 */
	focusOnFeature(
		anchor: FeatureAnchor,
		name: string | null,
		zoom: number,
		mode: 'pan' | 'frame' | 'snap' = 'frame',
		view?: { latitude: number; longitude: number; zoom: number } | null
	): number {
		this.applyJdUpdate();
		this.focusWasOutOfRange = false;
		const host = this.ctx.getBody(anchor.hostId);
		if (!host) return 0;
		// The feature framing supersedes the URL's body-level at=: the queued
		// initial-view replay (fired when the host's system data lands — see
		// reapplyInitialViewIfPending) would otherwise re-frame the host and
		// clobber a deep link's feature snap.
		this.focusController.clearPendingInitialView();

		// Capture whether we're already orbiting this host before the focus switch.
		const alreadyOnHost =
			nomenclatureBodyId(this.focusController.current, this.bodyObjects) === anchor.hostId;

		const fb = makeFeatureBody(anchor, name);
		this.ctx.bodies.focusFeature = fb;
		// Tag the feature's label active now so the seat lands on its (ray-cast)
		// surface point from the first frame. Otherwise the async texture/model
		// reload re-tags it a few frames later, jerking the pivot from the ellipsoid
		// fallback onto the real surface — very visible on shape models.
		const hostBo = this.bodyObjects.get(host.data.id);
		this.selectedFeatureId = anchor.featureId;
		if (hostBo) setActiveFeatureLabel(hostBo, anchor.featureId);
		seatFeatureBody(fb, host, hostBo, this.clock.jd);

		const seat = fb.position;
		const quat = this.focusController.focusedBodyQuat(fb);

		if (mode === 'pan') {
			// No camPos → pure re-pivot: the camera keeps its world position and pans
			// to re-centre on the seat. That destination is known now and no later
			// settle emits it (the camera never "moves"), so sync the URL here —
			// mirrors focusOnBody's emit-before-dispatch.
			const s = cartesianToSpherical(this.focusController.cameraTruePos(), seat, quat);
			this.callbacks.onCameraPosition?.(s.latitude, s.longitude, s.distance);
			this.focusController.setFocusTarget(fb);
			return this.focus.focusDurationMs;
		}

		// Camera along the local zenith above the seat; fall back to scene-up at a
		// pole where the zenith is degenerate.
		let zx = seat[0] - host.position[0];
		let zy = seat[1] - host.position[1];
		let zz = seat[2] - host.position[2];
		const len = Math.hypot(zx, zy, zz);
		if (len > 1e-9) {
			zx /= len;
			zy /= len;
			zz /= len;
		} else {
			zx = 0;
			zy = 1;
			zz = 0;
		}
		const camPos: Vec3 =
			mode === 'snap' && view
				? sphericalToCartesian(seat, view.latitude, view.longitude, view.zoom, quat)
				: [seat[0] + zx * zoom, seat[1] + zy * zoom, seat[2] + zz * zoom];

		// Emit the destination camera state before any dispatch (see focusOnBody)
		// so at= reflects the feature framing immediately.
		const s = cartesianToSpherical(camPos, seat, quat);
		this.callbacks.onCameraPosition?.(s.latitude, s.longitude, s.distance);

		if (mode === 'snap') {
			this.focusController.setFocusTarget(fb, camPos);
			// Deterministic settle on the seat (mirrors settleOnBodyInstant) so a
			// URL deep-link opens framed on the feature instead of racing the fly.
			const f = this.focus;
			f.focusTruePos = [...seat];
			f.focusOriginWorld = [...seat];
			f.focusTargetWorld = [...seat];
			f.focusStartTime = -FOCUS_DURATION_MS;
			f.camOriginWorld = null;
			f.camTargetWorld = null;
			f.camTargetOffset = null;
			f.camOriginOffset = null;
			f.flyQ0 = null;
			f.orbitFly = false;
			f.arcOrbit = false;
			f.cameraStaysOnBody = false;
			this.repositionAll();
			this.pointClouds.rebuildBasis();
			this.camera.position.set(camPos[0] - seat[0], camPos[1] - seat[1], camPos[2] - seat[2]);
			this.controls.update();
			return 0;
		}

		if (alreadyOnHost) {
			// Orbit around at constant radius. Reorigin onto the seat while holding
			// the camera's world position (image unchanged — a pure coordinate
			// re-base), then arc from there to the framing standoff.
			const camWorld = this.focusController.cameraTruePos();
			this.focusController.setFocusTarget(fb);
			this.focus.focusTruePos = [...seat];
			this.camera.position.set(camWorld[0] - seat[0], camWorld[1] - seat[1], camWorld[2] - seat[2]);
			this.repositionAll();
			this.pointClouds.rebuildBasis();
			prepareFlyToCamera(
				this.focus,
				this.camera,
				camWorld,
				camPos,
				getSettings().resolvedReducedMotion
			);
		} else {
			// Different object: approach fly, orbit mode so the host stays centred.
			this.focusController.setFocusTarget(fb, camPos);
			this.focus.orbitFly = true;
		}
		return this.focus.focusDurationMs;
	}

	/** Focused body when the NDC ray hits its overlay model, else null. Cast in
	 *  overlay space with `modelCamera` (refreshed every rendered frame), which
	 *  mirrors the main camera exactly. */
	private pickFocusedModel(ndcX: number, ndcY: number): PositionedBody | null {
		const focused = this.focusController.current;
		if (!focused) return null;
		const bo = this.bodyObjects.get(focused.data.id);
		if (!bo?.model) return null;
		this._pickNdc.set(ndcX, ndcY);
		this._modelRaycaster.setFromCamera(this._pickNdc, this.modelCamera);
		return this._modelRaycaster.intersectObject(bo.model, true).length > 0 ? focused : null;
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

	/** Debug lighting-tuner multiplier applied to every direct-sunlight path
	 *  (point/shadow/model lights + atmosphere shells) each frame. */
	private sunIntensityScale = 1;

	getSunIntensityScale(): number {
		return this.sunIntensityScale;
	}

	setSunIntensityScale(v: number): void {
		this.sunIntensityScale = v;
	}

	/** Debug: the focused body's live atmosphere params and the shipped set to
	 *  reset/diff against; null when the focused body has no scattering shell. */
	getFocusedAtmosphere(): {
		id: string;
		current: AtmosphereParams;
		shipped: AtmosphereParams;
	} | null {
		const id = this.focusController.current?.data.id;
		if (!id) return null;
		const node = this.bodyObjects.get(id)?.atmosphere;
		const shipped = ATMOSPHERE_PARAMS[id];
		if (!node || !shipped) return null;
		return { id, current: node.params, shipped };
	}

	/** Debug: swap the focused body's atmosphere params live (uniforms + shell
	 *  scale re-derived). Lost if the body's render stack rebuilds. */
	setFocusedAtmosphereParams(params: AtmosphereParams): void {
		const id = this.focusController.current?.data.id;
		const node = id ? this.bodyObjects.get(id)?.atmosphere : undefined;
		if (node) applyAtmosphereParams(node, params);
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

	/** Stop the RAF loop; rendering against a lost GL context throws. */
	pause(): void {
		if (this.paused) return;
		this.paused = true;
		cancelAnimationFrame(this.rafId);
		this.rafId = 0;
	}

	resume(): void {
		if (!this.paused) return;
		this.paused = false;
		this.tick();
	}

	isContextLost(): boolean {
		return this.renderer.getContext().isContextLost();
	}

	/** three re-inits its own GL state on restore, but the composer's render
	 *  targets don't — re-applying pixel ratio + size rebuilds them. */
	handleContextRestored(): void {
		this.renderer.setPixelRatio(cappedPixelRatio());
		this.composer.setPixelRatio(cappedPixelRatio());
		this.resize(this.canvas.clientWidth, this.canvas.clientHeight);
		this.resume();
	}

	/** Respawn orbit workers if the OS killed them (frozen asteroids/spacecraft). */
	recoverWorkersIfDead(): Promise<boolean> {
		return this.pointClouds.recoverWorkersIfDead();
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
		this.gpuPick.dispose();
		this.controls.removeEventListener('end', this.onControlsEnd);
		this.controls.dispose();
		this.haloDebug.dispose();
		// Worker pool + cloud buffers — the biggest per-navigation leak.
		this.pointClouds.dispose();
		// renderer.dispose() frees only its own caches, not our geometries/
		// materials/textures. Env maps aren't scene children — dispose explicitly.
		this.disposeScene(this.scene);
		this.disposeScene(this.modelScene);
		disposeTexture(this.scene.background);
		disposeTexture(this.scene.environment);
		disposeTexture(this.modelScene.environment);
		this.circleTexture.dispose();
		this.bodyObjects.clear();
		// EffectComposer render targets (bloom mips) survive renderer.dispose().
		this.composer.dispose();
		this.renderer.dispose();
	}

	/** Dispose every geometry/material/texture in `scene`; materials deduped. */
	private disposeScene(scene: Scene): void {
		const seen = new Set<Material>();
		scene.traverse((obj) => {
			const mesh = obj as Mesh;
			mesh.geometry?.dispose();
			const mat = mesh.material;
			const mats = Array.isArray(mat) ? mat : mat ? [mat] : [];
			for (const m of mats) {
				if (seen.has(m)) continue;
				seen.add(m);
				for (const v of Object.values(m)) disposeTexture(v);
				m.dispose();
			}
		});
	}
}

/** Dispose `value` if it's a three Texture; no-op otherwise. */
function disposeTexture(value: unknown): void {
	if (value && typeof value === 'object' && (value as { isTexture?: boolean }).isTexture) {
		(value as { dispose(): void }).dispose();
	}
}
