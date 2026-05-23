import {
	type DirectionalLight,
	Mesh,
	type PerspectiveCamera,
	PointLight,
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
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import type { SimClock } from '$lib/scene/clock.svelte';
import { AU_SCALE, kmToScene } from '$lib/math/units';
import { bootThree } from './setup/three-boot';
import { PointerInteraction } from './interaction/pointer';
import { CameraUpController } from './camera/up-controller';
import { jdToDate } from '$lib/format/date';
import {
	isMeshUpgradable,
	loadBodyTexture,
	makeCircleTexture,
	upgradeBodyMesh,
	buildMajorBodies,
	buildOrbitLines
} from './objects/construction';
import { SystemDataLoader } from './system-data/loader';
import { loadSkybox } from './objects/skybox';
import { SkyboxAdjuster } from './debug/skybox-adjust';
import { SkyDebugMarkers } from './debug/sky-markers';
import { collectDebugStats, type DebugStats } from './debug/stats';
import { PointCloudSystem } from './pointclouds/system';
import { rebaseOrbitLineLocals, setOrbitLineResolution } from './objects/builders';
import { updatePositions, refreshDeferredOrbitLines } from './position/update-positions';
import { PositionDiagnostics } from './position/diagnostics';
import { updateRingShaders } from './shaders/ring-uniforms';
import { updateAtmosphereShaders } from './shaders/atmosphere-uniforms';
import { updateEclipseUniforms } from './shaders/eclipse-uniforms';
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

// --- SceneRenderer ---

export class SceneRenderer {
	private renderer: WebGLRenderer;
	private composer: EffectComposer;
	private bloomPass: UnrealBloomPass;
	private labelRenderer: ThrottledCSS2DRenderer;
	private scene: Scene;
	private camera: PerspectiveCamera;
	private controls: OrbitControls;
	private pointerInteraction!: PointerInteraction;

	private ctx: ContextManager;
	private clock: SimClock;
	private callbacks: Callbacks;

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

	private cameraUp!: CameraUpController;
	private skyboxAdjuster!: SkyboxAdjuster;
	private skyDebugMarkers!: SkyDebugMarkers;

	// Focus/fly animation state (mutated by animation module)
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
		focusStartTime: 0,
		focusDurationMs: FOCUS_DURATION_MS
	};
	/** JD at which per-frame body positions were last computed. */
	private lastUpdatedJd = NaN;
	// Per-frame position-map scratch — reused to avoid Map churn on every tick.
	// Cleared at the start of updatePositions; never escapes the call.
	private readonly _positionMapScratch = new Map<string, Vec3>();

	private rafId = 0;
	private firstFrame = true;
	private pendingUrlWrite = false;
	// FPS ring buffer: timestamps of the last `FPS_SAMPLE_FRAMES` ticks. fps =
	// (n - 1) / (last - first) seconds, which stays stable down to ~5 fps.
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
	 * Layer used for "map UI": orbit lines + point clouds. Immersive mode
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

		// Skybox: seed rotation synchronously so it's correct from frame 1 (so a
		// debug-overlay setSkyboxAdjust can't be clobbered by the async load).
		this.skyboxAdjuster = new SkyboxAdjuster(this.scene);
		this.skyDebugMarkers = new SkyDebugMarkers(this.scene);
		this.skyboxAdjuster.set(0, 0, 0);
		void loadSkybox(this.scene, this.renderer, ctx);

		// Set initial camera position from URL state
		const sunBody = ctx.majorBodies.find((b) => b.data.id === 'naif-10');
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
			() => this.rebuildOrbitLineBasis()
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
				assignMapLayerToOrbitLines: () => this.assignMapLayerToOrbitLines()
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

		// Sync context initial state
		if (focusBody) ctx.setFocused(focusBody);
		ctx.updateCamera(initialView.zoom);

		// Notify initial focus
		callbacks.onFocusChange(focusBody);

		// Build all scene objects
		this.buildScene();

		// Grab reference to Sun's PointLight for shadow swap
		const sunBo = this.bodyObjects.get('naif-10');
		this.sunPointLight = sunBo?.extraObjects.find((o): o is PointLight => o instanceof PointLight);

		// If focused body has no visual objects (e.g. placeholder from global file), build them.
		if (focusBody) this.focusController.promotion.ensureBodyObjects(focusBody);

		// Initial focus on a halo-only type (asteroid/comet/probe) needs its
		// mesh built immediately — setFocusTarget handles this on subsequent
		// focus changes, but the init path skips that helper.
		if (focusBody && isMeshUpgradable(focusBody)) {
			const bo = this.bodyObjects.get(focusBody.data.id);
			if (bo) {
				upgradeBodyMesh(bo, this.scene, this.clickables, this.meshToBody);
				buildOrbitLines(this.bodyObjects, this.scene, this.pointClouds.basis(), this.clock.jd);
				this.assignMapLayerToOrbitLines();
			}
		}

		// Apply focus-relative positions to all scene objects
		this.repositionAll();

		// Load textures for initial focus (bodyObjects is now populated)
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

		// Start loop
		this.tick();
	}

	// --- Scene construction ---

	private buildScene(): void {
		buildMajorBodies(
			this.ctx.majorBodies,
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
		// Defer orbit line geometry (100K+ Kepler solves) to after first paint.
		const basis = this.pointClouds.basis();
		const scheduleIdle = globalThis.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 0));
		scheduleIdle(() => {
			buildOrbitLines(this.bodyObjects, this.scene, basis, this.clock.jd);
			this.assignMapLayerToOrbitLines();
		});
	}

	/** Assign all current orbit lines to MAP_LAYER so they can be hidden together by immersive mode. */
	private assignMapLayerToOrbitLines(): void {
		for (const bo of this.bodyObjects.values()) {
			if (bo.orbitLine) bo.orbitLine.layers.set(SceneRenderer.MAP_LAYER);
		}
	}

	/**
	 * Map vs immersive view. Immersive hides CSS2D labels (DOM), orbit lines,
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

	// --- Focus-relative positioning ---

	private repositionAll(): void {
		this.repositionBodies();
		this.rebuildOrbitLineBasis();
	}

	/** Like {@link repositionAll} but skips the orbit-line rewrite — for callers that already refreshed lines per-body. */
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
	 * Rebase the cached orbit-local vertices against the current focus (no
	 * Kepler recompute). Used by focus animation paths; the per-jd path goes
	 * through {@link refreshOrbitLineGeometry} instead.
	 */
	private rebuildOrbitLineBasis(): void {
		const [fx, fy, fz] = this.focus.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			// Don't gate on line.visible — newly-built lines are visible=false
			// but will be flipped visible later this frame by updateBodyVisibility;
			// their vertices must be rebased against the new focus before first render.
			if (!line) continue;
			const localPositions = line.userData.orbitLocalPositions as
				| [number, number, number][]
				| undefined;
			if (!localPositions) continue;
			const oc = line.userData.orbitCenter as Vector3;
			rebaseOrbitLineLocals(line, localPositions, oc.x - fx, oc.y - fy, oc.z - fz);
		}
	}

	// --- RAF loop ---

	private tick = (): void => {
		this.rafId = requestAnimationFrame(this.tick);

		// FPS ring buffer — ~16 bytes per sample, only read when the debug
		// overlay is open. Cheap enough to always keep current.
		const nowMs = performance.now();
		if (this.fpsSamples.length < SceneRenderer.FPS_SAMPLE_FRAMES) {
			this.fpsSamples.push(nowMs);
		} else {
			this.fpsSamples[this.fpsSampleHead] = nowMs;
			this.fpsSampleHead = (this.fpsSampleHead + 1) % SceneRenderer.FPS_SAMPLE_FRAMES;
		}

		this.cameraUp.update(this.clock.jd);

		// Snap controls target on first frame
		if (this.firstFrame) {
			this.firstFrame = false;
			this.controls.target.set(0, 0, 0);
			this.controls.update();
		}

		// Gate body updates on jd actually changing — fires for play, pause→now,
		// and manual setJD alike; skips work while paused.
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
			// When animating, stepFocusAnimation below does repositionAll already.
			const elapsed = performance.now() - this.focus.focusStartTime;
			if (elapsed >= this.focus.focusDurationMs) {
				this.repositionBodies();
				this.pointClouds.maybeRebase();
			}
		}

		// Animate focus/fly
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

		// Once the most recent focus animation has run its course, release the
		// textures of any system the user navigated away from. Deferred (rather
		// than disposed at click time) so a fly that gets reversed mid-way
		// doesn't thrash the GPU.
		if (
			this.systemData.hasPendingUnloads() &&
			performance.now() - this.focus.focusStartTime >= this.focus.focusDurationMs
		) {
			this.systemData.drainPendingUnloads();
		}

		// Camera state → visibility decisions
		const { distance } = this.getCameraState();
		this.ctx.updateCamera(distance);

		// Per-frame visibility, label, and orbit line updates
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

		// Catch lines that updatePositions skipped (visible=false last frame)
		// but updateBodyVisibility just flipped on, so they don't render at a
		// stale basis for one frame.
		refreshDeferredOrbitLines(this.bodyObjects, this.focus, this.lastUpdatedJd);

		updateRingShaders(this.bodyObjects, this.focus.focusTruePos);
		updateAtmosphereShaders(this.bodyObjects);
		updateEclipseUniforms(this.bodyObjects, this.focus.focusTruePos);

		// Hide the user-location dot when it rotates around to Earth's far side.
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

		// Auto-promote one default-important minor body per frame.
		this.focusController.promotion.drainOneAutoPromote();

		// Stagger new point cloud additions: one per frame to spread GPU upload cost.
		this.pointClouds.drainOnePendingSceneAdd();

		this.composer.render();
		this.labelRenderer.render(this.scene, this.camera);
	};

	// --- Interaction ---

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
		if (bo) loadBodyTexture(bo, this.textureLoader, this.clock.jd, this.ctx);
	}

	// --- Public API ---

	clearUserPromoted(): void {
		this.focusController.promotion.clearUserPromoted();
	}

	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		return this.focusController.focusOnBody(id, zoom, latitude, longitude);
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.focusController.setFocusTarget(body, camPos);
	}

	getFocusedBody(): PositionedBody | undefined {
		return this.focusController.current;
	}

	/**
	 * Snapshot of internals for the debug overlay. Read on demand; nothing
	 * here is hot, but the call lives behind a settings toggle so the
	 * GC-pressure of one allocation per frame is fine.
	 *
	 * `fps` is averaged across the ring buffer (~0.5s at 60Hz); when the tab
	 * is backgrounded RAF is throttled and the buffer ages out — that's
	 * accurate, not stale.
	 */
	getDebugStats(): DebugStats {
		const samples = this.fpsSamples;
		let fps = 0;
		if (samples.length >= 2) {
			// Reassemble the ring buffer in chronological order.
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

	/**
	 * Drop a "you are here" pin at lat/lon on Earth. Re-pins if already set.
	 * Parented to Earth's mesh, so it inherits Earth's rotation and the dot
	 * stays glued to the same ground point as the planet spins.
	 */
	setUserLocation(latitude: number, longitude: number): void {
		const earth = this.bodyObjects.get('naif-399');
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
		this.ctx.updateViewport(height);
		setOrbitLineResolution(width, height);
	}

	dispose(): void {
		cancelAnimationFrame(this.rafId);
		this.pointerInteraction.detach();
		this.controls.removeEventListener('end', this.onControlsEnd);
		this.controls.dispose();
		this.renderer.dispose();
	}
}
