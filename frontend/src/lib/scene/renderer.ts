import {
	AmbientLight,
	DirectionalLight,
	Float32BufferAttribute,
	Mesh,
	BasicShadowMap,
	PerspectiveCamera,
	PointLight,
	Points,
	Quaternion,
	Raycaster,
	Scene,
	ShaderMaterial,
	TextureLoader,
	Vector2,
	Vector3,
	WebGLRenderer
} from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { cartesianToSpherical, sphericalToCartesian, type MapViewState } from '$lib/url-state';
import { ObjectType, effectiveRadiusKm, isAsteroid, type PositionedBody } from '$lib/types/objects';
import { VISIBILITY } from '$lib/scene/context-manager.svelte';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import { AU_SCALE, kmToScene } from '$lib/math/units';
import {
	applyLabelDisplay,
	isScreenOccluded,
	cullOverlappingLabels,
	type ScreenOccluder
} from './label/culling';
import {
	buildMajorBodies,
	buildOrbitLines,
	buildPointClouds,
	rebuildMinorPointClouds,
	loadBodyTexture,
	loadSystemTextures,
	makeCircleTexture
} from './construction';
import { HALO_RADIUS_PX, type BodyObjects, type Callbacks } from './types';
import { DEFAULT_PROMOTED_IDS } from './default-bodies';

type Vec3 = [number, number, number];

function f64lerp(a: Vec3, b: Vec3, t: number): Vec3 {
	return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function f64dist(a: Vec3, b: Vec3): number {
	const dx = a[0] - b[0],
		dy = a[1] - b[1],
		dz = a[2] - b[2];
	return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

type VisibilityFlags = {
	groupVisible: boolean;
	orbitVisible: boolean;
	showLabel: boolean;
	isClose: boolean;
};

function moonVisFlags(
	vis: VISIBILITY,
	hideCappedLabels: boolean,
	isFocused: boolean
): VisibilityFlags {
	const capped = vis === VISIBILITY.CAPPED;
	return {
		groupVisible:
			vis === VISIBILITY.CLOSE || vis === VISIBILITY.FULL || (capped && hideCappedLabels),
		// Focused body keeps orbit visible at CLOSE; applyLabelDisplay hides it when the sphere fills the screen.
		orbitVisible: vis === VISIBILITY.FULL || (vis === VISIBILITY.CLOSE && isFocused),
		showLabel: vis === VISIBILITY.FULL || (capped && hideCappedLabels),
		isClose: vis === VISIBILITY.CLOSE
	};
}

function bodyVisFlags(
	vis: VISIBILITY,
	fullRendering: boolean,
	isFocused: boolean
): VisibilityFlags {
	return {
		// No FAR — mesh is sub-pixel at that distance, point cloud suffices.
		groupVisible: vis === VISIBILITY.CLOSE || vis === VISIBILITY.FULL,
		orbitVisible:
			(vis === VISIBILITY.FULL && fullRendering) || (vis === VISIBILITY.CLOSE && isFocused),
		showLabel: vis === VISIBILITY.FULL && fullRendering,
		isClose: fullRendering && vis === VISIBILITY.CLOSE
	};
}

/** Default surface clearance in km, by object type. */
const SURFACE_CLEARANCE_KM: Partial<Record<ObjectType, number>> = {
	[ObjectType.STAR]: 1000,
	[ObjectType.PLANET]: 100,
	[ObjectType.DWARF_PLANET]: 10,
	[ObjectType.ASTEROID]: 0.1,
	[ObjectType.ASTEROID_INNER]: 0.1,
	[ObjectType.ASTEROID_MAIN_BELT]: 0.1,
	[ObjectType.ASTEROID_CENTAUR]: 1,
	[ObjectType.ASTEROID_TROJAN]: 1,
	[ObjectType.ASTEROID_TNO]: 1,
	[ObjectType.COMET]: 1,
	[ObjectType.MOON]: 1,
	[ObjectType.SPACECRAFT]: 0.01
};
const DEFAULT_CLEARANCE_KM = 0.01; // 10 m

/** Per-body overrides for surface clearance (km). Keyed by body id (e.g. "naif-10"). */
const BODY_CLEARANCE_OVERRIDES: Record<string, number> = {};

function minCameraDistance(body: PositionedBody): number {
	const radiusKm = effectiveRadiusKm(body.data);
	const clearance =
		BODY_CLEARANCE_OVERRIDES[body.data.id] ??
		SURFACE_CLEARANCE_KM[body.data.objectType] ??
		DEFAULT_CLEARANCE_KM;
	return kmToScene(radiusKm + clearance);
}

// --- SceneRenderer ---

export class SceneRenderer {
	private renderer: WebGLRenderer;
	private labelRenderer: CSS2DRenderer;
	private scene: Scene;
	private camera: PerspectiveCamera;
	private controls: OrbitControls;
	private raycaster = new Raycaster();
	private pointer = new Vector2();
	private pointerDownPos = new Vector2();

	private ctx: ContextManager;
	private callbacks: Callbacks;

	private bodyObjects = new Map<string, BodyObjects>();
	private circleTexture = makeCircleTexture();
	private asteroidPoints = new Map<string, Points>();
	private textureLoaded = new Set<string>();
	private lastSystemTextureBarycenter: string | null = null;
	private spacecraftPoints = new Map<string, Points>();
	private moonPoints = new Map<string, Points>();
	private clickables: Mesh[] = [];
	private meshToBody = new Map<Mesh, PositionedBody>();
	private pendingSceneAdds: Points[] = [];
	private pendingDefaultPromotions = new Set(DEFAULT_PROMOTED_IDS);
	private hoveredBodyIds = new Set<string>();
	private cullFrameCounter = 0;

	// TODO: expose via UI settings
	hideCappedMoonLabels = false;

	private focusedBody: PositionedBody | undefined;
	private readonly _tmpV3 = new Vector3();
	private readonly _camWorldV3 = new Vector3();

	// Float64 world positions for focus-relative rendering
	private focusTruePos: Vec3 = [0, 0, 0];
	private focusOriginWorld: Vec3 = [0, 0, 0];
	private focusTargetWorld: Vec3 = [0, 0, 0];
	private camOriginWorld: Vec3 | null = null;
	private camTargetWorld: Vec3 | null = null;
	private pointCloudBasisPos: Vec3 = [0, 0, 0];

	private flyQ0: Quaternion | null = null;
	private flyQ1: Quaternion | null = null;
	private orbitFly = false;
	private focusStartTime = 0;
	private static readonly FOCUS_DURATION_MS = 350;
	private static readonly FLY_DURATION_MS = 1600;
	private focusDurationMs = SceneRenderer.FOCUS_DURATION_MS;
	private rafId = 0;
	private firstFrame = true;
	private pendingUrlWrite = false;
	private readonly textureLoader = new TextureLoader();
	private readonly shadowLight: DirectionalLight;
	private sunPointLight: PointLight | undefined;

	constructor(
		canvas: HTMLCanvasElement,
		labelContainer: HTMLElement,
		ctx: ContextManager,
		initialView: MapViewState,
		callbacks: Callbacks
	) {
		this.ctx = ctx;
		this.callbacks = callbacks;

		// Renderer
		this.renderer = new WebGLRenderer({ canvas, logarithmicDepthBuffer: true, antialias: true });
		this.renderer.setPixelRatio(window.devicePixelRatio);
		this.renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		this.renderer.shadowMap.enabled = true;
		this.renderer.shadowMap.type = BasicShadowMap;

		// CSS2D label renderer
		this.labelRenderer = new CSS2DRenderer({ element: labelContainer });
		this.labelRenderer.setSize(canvas.clientWidth, canvas.clientHeight);
		ctx.updateViewport(canvas.clientHeight);

		// Scene + lights
		this.scene = new Scene();
		this.scene.add(new AmbientLight(0xffffff, 0.05));

		// Shadow-casting directional light (swapped in when zoomed into a sub-system)
		this.shadowLight = new DirectionalLight(0xffffff, 0);
		this.shadowLight.castShadow = true;
		this.shadowLight.shadow.mapSize.set(4096, 4096);
		this.shadowLight.shadow.bias = -0.00001;
		this.scene.add(this.shadowLight);
		this.scene.add(this.shadowLight.target);

		// Camera
		const aspect = canvas.clientWidth / canvas.clientHeight;
		this.camera = new PerspectiveCamera(60, aspect, kmToScene(0.001), 100000);

		// Set initial camera position from URL state
		const sunBody = ctx.majorBodies.find((b) => b.data.id === 'naif-10');
		const matchedBody = ctx.getBody(initialView.id);
		const focusBody = matchedBody ?? sunBody;
		const focusPos: Vec3 = focusBody?.position ?? [0, 0, 0];

		this.focusedBody = focusBody;
		this.focusTruePos = [...focusPos];
		this.focusOriginWorld = [...focusPos];
		this.focusTargetWorld = [...focusPos];
		this.pointCloudBasisPos = [...focusPos];
		this.focusStartTime = -SceneRenderer.FOCUS_DURATION_MS; // already settled

		// Camera position: focus-relative (small offset from origin)
		const camPos = sphericalToCartesian(
			[0, 0, 0],
			initialView.latitude,
			initialView.longitude,
			initialView.zoom
		);
		this.camera.position.set(...camPos);

		// OrbitControls — target always at origin
		this.controls = new OrbitControls(this.camera, canvas);
		this.controls.enableDamping = true;
		this.controls.minDistance = focusBody ? minCameraDistance(focusBody) : kmToScene(0.01);
		this.controls.maxDistance = 31_620.5 * AU_SCALE; // 0.5 light-year
		this.controls.target.set(0, 0, 0);
		this.controls.update();
		this.controls.addEventListener('end', this.onControlsEnd);

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
		if (focusBody) this.ensureBodyObjects(focusBody);

		// Apply focus-relative positions to all scene objects
		this.repositionAll();

		// Load textures for initial focus (bodyObjects is now populated)
		if (focusBody) this.maybeLoadTexture(focusBody);
		this.maybeLoadSystemTextures();

		// Click handler
		canvas.addEventListener('pointerdown', this.onPointerDown);
		canvas.addEventListener('pointerup', this.onPointerUp);

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
			(body) => this.handleFocus(body),
			(id, hovered) => (hovered ? this.hoveredBodyIds.add(id) : this.hoveredBodyIds.delete(id))
		);
		const promotedIds = new Set(this.bodyObjects.keys());
		const pts = buildPointClouds(
			this.ctx,
			this.scene,
			this.circleTexture,
			this.pointCloudBasisPos,
			promotedIds
		);
		this.asteroidPoints = pts.asteroidPoints;
		this.spacecraftPoints = pts.spacecraftPoints;
		this.moonPoints = pts.moonPoints;
		// Defer orbit line geometry (100K+ Kepler solves) to after first paint
		const basis = this.pointCloudBasisPos;
		// requestIdleCallback isn't available in Safari
		const scheduleIdle = globalThis.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 0));
		scheduleIdle(() => buildOrbitLines(this.bodyObjects, this.scene, basis));
	}

	rebuildMinorPointClouds(): void {
		const newPoints = rebuildMinorPointClouds(
			this.ctx,
			this.circleTexture,
			this.asteroidPoints,
			this.spacecraftPoints,
			this.pointCloudBasisPos,
			new Set(this.bodyObjects.keys())
		);
		if (newPoints.length > 0) {
			this.pendingSceneAdds.push(...newPoints);
		}
	}

	// --- Focus-relative positioning ---

	private repositionAll(): void {
		const [fx, fy, fz] = this.focusTruePos;
		for (const bo of this.bodyObjects.values()) {
			const [bx, by, bz] = bo.body.position;
			const rx = bx - fx,
				ry = by - fy,
				rz = bz - fz;
			bo.group.position.set(rx, ry, rz);
			for (const obj of bo.extraObjects) obj.position.set(rx, ry, rz);
		}
		this.repositionPointClouds();
	}

	private repositionPointClouds(): void {
		const [fx, fy, fz] = this.focusTruePos;
		const [bx, by, bz] = this.pointCloudBasisPos;
		const dx = bx - fx,
			dy = by - fy,
			dz = bz - fz;
		for (const pts of this.asteroidPoints.values()) pts.position.set(dx, dy, dz);
		for (const pts of this.spacecraftPoints.values()) pts.position.set(dx, dy, dz);
		for (const pts of this.moonPoints.values()) pts.position.set(dx, dy, dz);
	}

	private rebuildPointCloudBasis(): void {
		this.pointCloudBasisPos = [...this.focusTruePos];
		// Re-trigger dirty flags for all zones so they rebuild with new basis
		for (const zone of this.asteroidPoints.keys()) this.ctx.dirtyAsteroidZones.add(zone);
		for (const gid of this.spacecraftPoints.keys()) this.ctx.dirtySpacecraftGroups.add(gid);
		this.rebuildMinorPointClouds();
		// Rebuild moon point cloud vertex buffers with new basis
		this.rebuildMoonPointClouds();
		// Rebuild orbit line vertex buffers with new basis
		this.rebuildOrbitLineBasis();
		// Reset point cloud object positions since basis matches focus
		for (const pts of this.asteroidPoints.values()) pts.position.set(0, 0, 0);
		for (const pts of this.spacecraftPoints.values()) pts.position.set(0, 0, 0);
		for (const pts of this.moonPoints.values()) pts.position.set(0, 0, 0);
	}

	private rebuildMoonPointClouds(): void {
		const basis = this.pointCloudBasisPos;
		const moonsByParent = new Map<string, PositionedBody[]>();
		for (const body of this.ctx.majorBodies) {
			if (body.data.objectType === ObjectType.MOON) {
				const list = moonsByParent.get(body.data.parentId) ?? [];
				list.push(body);
				moonsByParent.set(body.data.parentId, list);
			}
		}
		for (const [parentId, moons] of moonsByParent) {
			const existing = this.moonPoints.get(parentId);
			if (!existing) continue;
			const positions = new Float32Array(moons.length * 3);
			for (let i = 0; i < moons.length; i++) {
				positions[i * 3] = moons[i].position[0] - basis[0];
				positions[i * 3 + 1] = moons[i].position[1] - basis[1];
				positions[i * 3 + 2] = moons[i].position[2] - basis[2];
			}
			existing.geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
		}
	}

	private rebuildOrbitLineBasis(): void {
		const [bx, by, bz] = this.pointCloudBasisPos;
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (!line) continue;
			const localPositions = line.userData.orbitLocalPositions as
				| [number, number, number][]
				| undefined;
			if (!localPositions) continue;
			const oc = line.userData.orbitCenter as Vector3;
			// orbitCenter - basisPos in Float64, then add each orbit-local point
			const ox = oc.x - bx,
				oy = oc.y - by,
				oz = oc.z - bz;
			const posAttr = line.geometry.getAttribute('position');
			const arr = posAttr.array as Float32Array;
			for (let i = 0; i < localPositions.length; i++) {
				arr[i * 3] = localPositions[i][0] + ox;
				arr[i * 3 + 1] = localPositions[i][1] + oy;
				arr[i * 3 + 2] = localPositions[i][2] + oz;
			}
			posAttr.needsUpdate = true;
		}
	}

	// Reconstruct camera true world position (Float64)
	private cameraTruePos(): Vec3 {
		return [
			this.focusTruePos[0] + this.camera.position.x,
			this.focusTruePos[1] + this.camera.position.y,
			this.focusTruePos[2] + this.camera.position.z
		];
	}

	// --- RAF loop ---

	private tick = (): void => {
		this.rafId = requestAnimationFrame(this.tick);

		// Snap controls target on first frame
		if (this.firstFrame) {
			this.firstFrame = false;
			this.controls.target.set(0, 0, 0);
			this.controls.update();
		}

		// Animate focus position (and optionally camera position) with smoothstep over fixed duration
		const elapsed = performance.now() - this.focusStartTime;
		const t = Math.min(elapsed / this.focusDurationMs, 1);
		const isAnimating = t < 1;
		const isFlying = !!(this.camOriginWorld && this.camTargetWorld && this.flyQ0 && this.flyQ1);
		let controlsSettled: boolean;
		if (isAnimating && isFlying) {
			const s = t * t * (3 - 2 * t); // smoothstep
			// Lerp focus position in Float64
			this.focusTruePos = f64lerp(this.focusOriginWorld, this.focusTargetWorld, s);
			this.repositionAll();
			if (this.orbitFly) {
				const focusChanging =
					this.focusOriginWorld[0] !== this.focusTargetWorld[0] ||
					this.focusOriginWorld[1] !== this.focusTargetWorld[1] ||
					this.focusOriginWorld[2] !== this.focusTargetWorld[2];
				// Ease-in position when approaching from afar, smoothstep when orbiting
				const sCam = focusChanging ? t * t * t : s;
				const camWorld = f64lerp(this.camOriginWorld!, this.camTargetWorld!, sCam);
				this.camera.position.set(
					camWorld[0] - this.focusTruePos[0],
					camWorld[1] - this.focusTruePos[1],
					camWorld[2] - this.focusTruePos[2]
				);
				if (focusChanging) {
					// Approaching: blend from slerp (turn) to lookAt (keep centered)
					this.camera.quaternion.slerpQuaternions(this.flyQ0!, this.flyQ1!, s);
					const slerpQ = this.camera.quaternion.clone();
					this.camera.lookAt(
						this.focusTargetWorld[0] - this.focusTruePos[0],
						this.focusTargetWorld[1] - this.focusTruePos[1],
						this.focusTargetWorld[2] - this.focusTruePos[2]
					);
					const lookAtQ = this.camera.quaternion.clone();
					this.camera.quaternion.slerpQuaternions(slerpQ, lookAtQ, s);
				} else {
					// Already focused: pure lookAt
					this.camera.lookAt(
						this.focusTargetWorld[0] - this.focusTruePos[0],
						this.focusTargetWorld[1] - this.focusTruePos[1],
						this.focusTargetWorld[2] - this.focusTruePos[2]
					);
				}
			} else {
				// Slerp camera orientation for uniform angular velocity
				this.camera.quaternion.slerpQuaternions(this.flyQ0!, this.flyQ1!, s);
				// Camera world position eases in so rotation is visible first
				const sCam = t * t * t; // cubic ease-in
				const camWorld = f64lerp(this.camOriginWorld!, this.camTargetWorld!, sCam);
				this.camera.position.set(
					camWorld[0] - this.focusTruePos[0],
					camWorld[1] - this.focusTruePos[1],
					camWorld[2] - this.focusTruePos[2]
				);
			}
			// Skip controls.update() — we're driving the camera directly
			controlsSettled = false;
		} else {
			if (
				this.focusTruePos[0] !== this.focusTargetWorld[0] ||
				this.focusTruePos[1] !== this.focusTargetWorld[1] ||
				this.focusTruePos[2] !== this.focusTargetWorld[2]
			) {
				this.focusTruePos = [...this.focusTargetWorld];
				this.repositionAll();
				// Rebuild point cloud vertex buffers relative to new focus
				this.rebuildPointCloudBasis();
			}
			this.controls.target.set(0, 0, 0);
			if (this.camTargetWorld) {
				const cx = this.camTargetWorld[0] - this.focusTruePos[0];
				const cy = this.camTargetWorld[1] - this.focusTruePos[1];
				const cz = this.camTargetWorld[2] - this.focusTruePos[2];
				this.camera.position.set(cx, cy, cz);
				// Flush stale OrbitControls damping delta accumulated during the fly
				this.controls.enableDamping = false;
				this.controls.update();
				this.controls.enableDamping = true;
				this.camera.position.set(cx, cy, cz);
				this.camOriginWorld = null;
				this.camTargetWorld = null;
				this.flyQ0 = null;
				this.flyQ1 = null;
				this.orbitFly = false;
			}
			controlsSettled = !this.controls.update();
		}
		if (this.pendingUrlWrite && controlsSettled) {
			this.pendingUrlWrite = false;
			const { latitude, longitude, distance } = this.getCameraState();
			this.callbacks.onCameraPosition?.(latitude, longitude, distance);
		}

		// Camera state → visibility decisions
		const { distance } = this.getCameraState();
		this.ctx.updateCamera(distance);

		// Camera true world position for Float64 distance calculations
		const camTrue = this.cameraTruePos();
		this._camWorldV3.set(camTrue[0], camTrue[1], camTrue[2]);

		// Visibility updates
		const fovRad = (this.camera.fov * Math.PI) / 180;
		const projScale = this.renderer.domElement.clientHeight / (2 * Math.tan(fovRad / 2));
		const focusedBodyId = this.focusedBody?.data.id;

		// Build screen-space occluder list: bodies whose sphere fills enough of
		// the screen to hide labels behind them (only when zoomed in close).
		const screenW = this.renderer.domElement.clientWidth;
		const screenH = this.renderer.domElement.clientHeight;
		const fp = this.focusTruePos;
		const screenOccluders: ScreenOccluder[] = [];
		for (const bo of this.bodyObjects.values()) {
			if (!bo.radiusScene) continue;
			const dist = f64dist(camTrue, bo.body.position);
			const screenR = (bo.radiusScene / dist) * projScale;
			if (screenR < HALO_RADIUS_PX) continue;
			const [bx, by, bz] = bo.body.position;
			this._tmpV3.set(bx - fp[0], by - fp[1], bz - fp[2]);
			this._tmpV3.project(this.camera);
			if (this._tmpV3.z > 1) continue;
			screenOccluders.push({
				sx: (this._tmpV3.x * 0.5 + 0.5) * screenW,
				sy: (-this._tmpV3.y * 0.5 + 0.5) * screenH,
				r: screenR,
				id: bo.body.data.id,
				dist
			});
		}

		for (const bo of this.bodyObjects.values()) {
			const { body, group, orbitLine } = bo;
			const dist = f64dist(camTrue, body.position);
			bo.cachedDist = dist;

			let showLabel: boolean;
			let isClose: boolean;
			const isFocused = body.data.id === focusedBodyId;

			if (
				body.data.objectType === ObjectType.BARYCENTER ||
				body.data.objectType === ObjectType.LAGRANGE_POINT
			) {
				// Virtual bodies promoted via URL navigation: always visible once built
				group.visible = true;
				if (orbitLine) orbitLine.visible = true;
				showLabel = true;
				isClose = false;
			} else if (body.data.objectType === ObjectType.STAR) {
				const full = this.ctx.hasFullRendering(body);
				group.visible = true;
				const screenR = (bo.radiusScene / dist) * projScale;
				isClose = full && screenR >= 1;
				showLabel = full && !isClose;
				if (bo.starPoint) bo.starPoint.visible = screenR < 1;
				// Hide corona/lensflare when star is occluded on screen
				this._tmpV3.set(
					body.position[0] - fp[0],
					body.position[1] - fp[1],
					body.position[2] - fp[2]
				);
				this._tmpV3.project(this.camera);
				let starOccluded = false;
				if (this._tmpV3.z <= 1) {
					starOccluded = isScreenOccluded(
						(this._tmpV3.x * 0.5 + 0.5) * screenW,
						(-this._tmpV3.y * 0.5 + 0.5) * screenH,
						dist,
						body.data.id,
						screenOccluders
					);
				}
				bo.isOccluded = starOccluded;
				if (starOccluded) showLabel = false;
				if (bo.corona) bo.corona.visible = !starOccluded;
				if (bo.lensflare) bo.lensflare.visible = !starOccluded;
			} else {
				// Moons, planets, spacecraft, asteroids, comets, dwarf planets
				const isMoon = body.data.objectType === ObjectType.MOON;
				const vis = isMoon
					? this.ctx.getMoonVisibility(body)
					: this.ctx.getPlanetVisibility(body, dist);
				const vf = isMoon
					? moonVisFlags(vis, this.hideCappedMoonLabels, isFocused)
					: bodyVisFlags(vis, this.ctx.hasFullRendering(body), isFocused);
				group.visible = vf.groupVisible;
				if (orbitLine) orbitLine.visible = vf.orbitVisible;
				showLabel = vf.showLabel;
				isClose = vf.isClose;
			}

			// Detach labels from hidden groups so CSS2DRenderer's recursive
			// renderObject() doesn't visit them and write display:'none' every frame.
			// Re-attach when the group becomes visible — CSS2DRenderer re-appends
			// the DOM element automatically on next render.
			// Required for good safari performance
			const { label } = bo;
			if (!group.visible && label && label.parent === group) {
				group.remove(label);
				label.element.remove();
			} else if (group.visible && label && label.parent !== group) {
				group.add(label);
			}

			applyLabelDisplay(bo, showLabel, isClose, dist, projScale, focusedBodyId);
		}

		for (const [zone, pts] of this.asteroidPoints) {
			pts.visible = this.ctx.isAsteroidGroupVisible(zone);
		}
		for (const [gid, pts] of this.spacecraftPoints) {
			pts.visible = this.ctx.isSpacecraftGroupVisible(gid);
		}
		for (const [parentId, pts] of this.moonPoints) {
			pts.visible = this.ctx.isMoonGroupVisible(parentId);
		}

		// Screen-space label occlusion runs every frame (cheap: typically 0-2 occluders).
		// Overlap culling is throttled to every 3rd frame.
		if (screenOccluders.length > 0) {
			for (const bo of this.bodyObjects.values()) {
				if (!bo.label?.visible) continue;
				if (bo.isOccluded !== undefined) continue; // stars handled above
				const [bx, by, bz] = bo.body.position;
				this._tmpV3.set(bx - fp[0], by - fp[1], bz - fp[2]);
				this._tmpV3.project(this.camera);
				if (this._tmpV3.z > 1) continue;
				if (
					isScreenOccluded(
						(this._tmpV3.x * 0.5 + 0.5) * screenW,
						(-this._tmpV3.y * 0.5 + 0.5) * screenH,
						bo.cachedDist,
						bo.body.data.id,
						screenOccluders
					)
				) {
					bo.label.visible = false;
				}
			}
		}

		if (++this.cullFrameCounter >= 3) {
			this.cullFrameCounter = 0;
			cullOverlappingLabels(
				this.bodyObjects,
				screenW,
				screenH,
				this.camera,
				focusedBodyId,
				this.ctx,
				this.hoveredBodyIds,
				screenOccluders,
				this.focusTruePos
			);
		}

		// Update camera-relative offset uniforms for trail lines (prevents float32 precision flicker)
		// Also update alpha multiplier for hover/focus highlight
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (!line?.visible) continue;
			const mat = line.material as ShaderMaterial;
			// Vertices are stored relative to pointCloudBasisPos, so offset = (basis - focus) - cam
			// (basis - focus) computed in Float64; when basis == focus, offset is just -cam (tiny)
			const [bpx, bpy, bpz] = this.pointCloudBasisPos;
			mat.uniforms.uCenterOffset.value.set(
				bpx - this.focusTruePos[0] - this.camera.position.x,
				bpy - this.focusTruePos[1] - this.camera.position.y,
				bpz - this.focusTruePos[2] - this.camera.position.z
			);
			const isFocused = bo.body.data.id === focusedBodyId;
			const isHovered = this.hoveredBodyIds.has(bo.body.data.id);
			mat.uniforms.uAlphaMultiplier.value = isHovered ? 2 : isFocused ? 1.75 : 1.0;
			mat.uniforms.uAlphaMin.value = isFocused ? 0.15 : 0.0;
			mat.uniforms.uShowFull.value = isFocused ? 1.0 : 0.0;
		}

		// Shadow light: swap between PointLight (solar system) and DirectionalLight (sub-system)
		const sysId = this.ctx.activeSystemId;
		if (sysId) {
			// Sun direction in focus-relative coordinates
			const sunPos = this.bodyObjects.get('naif-10')?.body.position;
			const [fx, fy, fz] = this.focusTruePos;
			const sunRelX = (sunPos?.[0] ?? 0) - fx;
			const sunRelY = (sunPos?.[1] ?? 0) - fy;
			const sunRelZ = (sunPos?.[2] ?? 0) - fz;
			const sunDir = this._tmpV3.set(sunRelX, sunRelY, sunRelZ).normalize();

			const lightDist = 10;
			this.shadowLight.position.copy(sunDir).multiplyScalar(lightDist);
			this.shadowLight.target.position.set(0, 0, 0);
			this.shadowLight.intensity = 2;
			if (this.sunPointLight) this.sunPointLight.intensity = 0;

			// Lateral extent: tight to camera view for high texel density.
			// Depth extent: full system so off-screen casters still produce shadows.
			const lateral = Math.max(distance * 2, 0.001);
			const depthExtent = this.ctx.getSystemExtent(sysId) * AU_SCALE * 1.2;
			const shadowCam = this.shadowLight.shadow.camera;
			shadowCam.left = shadowCam.bottom = -lateral;
			shadowCam.right = shadowCam.top = lateral;
			shadowCam.near = lightDist - depthExtent;
			shadowCam.far = lightDist + depthExtent;
			shadowCam.updateProjectionMatrix();
		} else {
			this.shadowLight.intensity = 0;
			if (this.sunPointLight) this.sunPointLight.intensity = 2;
		}

		// Auto-promote one default-important minor body per frame
		if (this.pendingDefaultPromotions.size > 0) {
			for (const id of this.pendingDefaultPromotions) {
				if (this.bodyObjects.has(id)) {
					this.pendingDefaultPromotions.delete(id);
					continue;
				}
				const body = this.ctx.getBody(id);
				if (!body) continue; // not in exported data, skip
				this.pendingDefaultPromotions.delete(id);
				this.ensureBodyObjects(body);
				break; // one per frame to spread GPU work
			}
		}

		// Stagger new point cloud additions: one per frame to spread GPU upload cost
		if (this.pendingSceneAdds.length > 0) {
			this.scene.add(this.pendingSceneAdds.shift()!);
		}

		this.renderer.render(this.scene, this.camera);
		this.labelRenderer.render(this.scene, this.camera);
	};

	// --- Interaction ---

	private getCameraState() {
		const cam = this.camera.position;
		return cartesianToSpherical([cam.x, cam.y, cam.z], [0, 0, 0]);
	}

	private onControlsEnd = (): void => {
		this.pendingUrlWrite = true;
	};

	private onPointerDown = (e: PointerEvent): void => {
		this.pointerDownPos.set(e.clientX, e.clientY);
	};

	private onPointerUp = (e: PointerEvent): void => {
		const dx = e.clientX - this.pointerDownPos.x;
		const dy = e.clientY - this.pointerDownPos.y;
		if (dx * dx + dy * dy > 9) return;

		const canvas = this.renderer.domElement;
		const rect = canvas.getBoundingClientRect();
		this.pointer.set(
			((e.clientX - rect.left) / rect.width) * 2 - 1,
			-((e.clientY - rect.top) / rect.height) * 2 + 1
		);
		this.raycaster.setFromCamera(this.pointer, this.camera);

		// Check mesh hits (planets, stars, etc.)
		const hits = this.raycaster.intersectObjects(this.clickables);
		let bestBody: PositionedBody | undefined;
		let bestDist = Infinity;
		if (hits.length > 0) {
			const body = this.meshToBody.get(hits[0].object as Mesh);
			if (body) {
				bestBody = body;
				bestDist = hits[0].distance;
			}
		}

		// Check point cloud bodies (asteroids, spacecraft, moons shown as dots)
		const pointHit = this.pickPointCloudBody();
		if (pointHit && pointHit.distance < bestDist) {
			bestBody = pointHit.body;
		}

		if (bestBody && bestBody.data.id !== this.focusedBody?.data.id) {
			this.handleFocus(bestBody);
		}
	};

	/** Find the closest visible point-cloud body to the current pointer (NDC). */
	private pickPointCloudBody(): { body: PositionedBody; distance: number } | null {
		const SCREEN_THRESHOLD = 8; // pixels
		const w = this.renderer.domElement.clientWidth;
		const h = this.renderer.domElement.clientHeight;
		// Convert NDC pointer to pixel coords
		const px = (this.pointer.x + 1) * 0.5 * w;
		const py = (1 - this.pointer.y) * 0.5 * h;

		const v = this._tmpV3;
		const [fx, fy, fz] = this.focusTruePos;
		let bestBody: PositionedBody | undefined;
		let bestScreenDist = SCREEN_THRESHOLD;
		let bestWorldDist = Infinity;

		const testBody = (body: PositionedBody): void => {
			// Project body position into camera-relative coordinates
			v.set(body.position[0] - fx, body.position[1] - fy, body.position[2] - fz);
			v.project(this.camera);
			// Behind camera
			if (v.z < 0 || v.z > 1) return;
			const sx = (v.x + 1) * 0.5 * w;
			const sy = (1 - v.y) * 0.5 * h;
			const screenDist = Math.hypot(sx - px, sy - py);
			if (screenDist < bestScreenDist) {
				bestScreenDist = screenDist;
				bestWorldDist = v.length();
				bestBody = body;
			} else if (screenDist === bestScreenDist && v.length() < bestWorldDist) {
				bestWorldDist = v.length();
				bestBody = body;
			}
		};

		// Visible asteroid zones
		for (const [zone, bodies] of this.ctx.asteroidBodiesByZone) {
			if (!this.ctx.isAsteroidGroupVisible(zone)) continue;
			for (const body of bodies) testBody(body);
		}

		// Visible spacecraft groups
		for (const [gid, bodies] of this.ctx.spacecraftByParent) {
			if (!this.ctx.isSpacecraftGroupVisible(gid)) continue;
			for (const body of bodies) testBody(body);
		}

		// Visible moon point-cloud groups (moons shown as dots when zoomed out)
		for (const body of this.ctx.majorBodies) {
			if (body.data.objectType !== ObjectType.MOON) continue;
			if (!this.ctx.isMoonGroupVisible(body.data.parentId)) continue;
			testBody(body);
		}

		if (!bestBody) return null;
		return { body: bestBody, distance: bestWorldDist };
	}

	/** Preload low-res textures for all bodies in the focused system (if changed). */
	private maybeLoadSystemTextures(): void {
		const sysId = this.ctx.focusedSystemId;
		if (!sysId) return;
		// Resolve to barycenter: if sysId is a planet (e.g. naif-599), its parent is the barycenter
		const body = this.ctx.getBody(sysId);
		const baryId =
			body?.data.objectType === ObjectType.BARYCENTER ? sysId : (body?.data.parentId ?? sysId);
		if (baryId === this.lastSystemTextureBarycenter) return;
		this.lastSystemTextureBarycenter = baryId;
		loadSystemTextures(baryId, this.bodyObjects, this.textureLoader, this.textureLoaded);
	}

	private maybeLoadTexture(body: PositionedBody): void {
		const id = body.data.id;
		if (this.textureLoaded.has(id)) return;
		this.textureLoaded.add(id);
		const bo = this.bodyObjects.get(id);
		if (bo?.mesh)
			loadBodyTexture(
				id,
				bo.mesh.material as import('three').MeshStandardMaterial,
				this.textureLoader,
				body.data.objectFileFlag
			);
	}

	private handleFocus(body: PositionedBody): void {
		this.setFocusTarget(body);
		const camWorld = this.cameraTruePos();
		const { latitude, longitude, distance } = cartesianToSpherical(camWorld, body.position);
		this.callbacks.onCameraPosition?.(latitude, longitude, distance);
	}

	/** Build mesh, label, halo, and orbit line for a body that only existed as a point-cloud dot. */
	private ensureBodyObjects(body: PositionedBody): void {
		if (this.bodyObjects.has(body.data.id)) return;
		// Minor bodies from chunks lack orbitElements; populate from data so orbit lines can be built
		if (!body.orbitElements) {
			body.orbitElements = body.data;
			const parent = this.bodyObjects.get(body.data.parentId);
			if (parent) body.orbitCenter = [...parent.body.position];
		}
		buildMajorBodies(
			[body],
			this.scene,
			this.clickables,
			this.meshToBody,
			this.bodyObjects,
			this.circleTexture,
			this.renderer.domElement,
			(b) => this.handleFocus(b),
			(id, hovered) => (hovered ? this.hoveredBodyIds.add(id) : this.hoveredBodyIds.delete(id))
		);
		buildOrbitLines(this.bodyObjects, this.scene, this.pointCloudBasisPos);
		this.repositionAll();

		// Rebuild the point cloud for this body's group so the promoted dot is removed
		if (body.data.objectType === ObjectType.SPACECRAFT) {
			this.ctx.dirtySpacecraftGroups.add(body.data.parentId);
		} else if (isAsteroid(body.data.objectType) || body.data.objectType === ObjectType.COMET) {
			for (const [zone, bodies] of this.ctx.asteroidBodiesByZone) {
				if (bodies.some((b) => b.data.id === body.data.id)) {
					this.ctx.dirtyAsteroidZones.add(zone);
					break;
				}
			}
		}
		this.rebuildMinorPointClouds();
	}

	// --- Public API ---

	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		const body = this.ctx.getBody(id);
		if (!body) return 0;
		if (zoom !== undefined) {
			let camPos: Vec3;
			if (latitude !== undefined && longitude !== undefined) {
				camPos = sphericalToCartesian(body.position, latitude, longitude, zoom);
			} else {
				// Place camera at `zoom` distance, arriving from the current camera direction
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
			if (this.focusedBody?.data.id === id) {
				// Snap focus in case a prior fly animation hasn't fully settled
				this.focusTruePos = [...body.position];
				this.repositionAll();
				this.rebuildPointCloudBasis();
				this.flyToCamera(camPos);
			} else {
				this.setFocusTarget(body, camPos);
				if (latitude !== undefined && longitude !== undefined) {
					// Use orbit mode so Earth stays centered during approach
					this.orbitFly = true;
				}
			}
		} else {
			this.setFocusTarget(body);
		}
		const camWorld = this.cameraTruePos();
		const spherical = cartesianToSpherical(camWorld, body.position);
		this.callbacks.onCameraPosition?.(spherical.latitude, spherical.longitude, spherical.distance);
		return this.focusDurationMs;
	}

	/** Animate camera around the current focus body (orbit), keeping it centered. */
	private flyToCamera(camPos: Vec3): void {
		this.camOriginWorld = this.cameraTruePos();
		this.camTargetWorld = camPos;
		this.focusOriginWorld = [...this.focusTruePos];
		this.focusTargetWorld = [...this.focusTruePos];
		this.focusStartTime = performance.now();
		this.focusDurationMs = SceneRenderer.FLY_DURATION_MS;
		this.orbitFly = true;
		// Set dummy quaternions so isFlying is true
		this.flyQ0 = this.camera.quaternion.clone();
		this.flyQ1 = this.camera.quaternion.clone();
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.ensureBodyObjects(body);
		this.focusOriginWorld = [...this.focusTruePos];
		this.focusTargetWorld = [...body.position];
		this.focusStartTime = performance.now();
		this.focusedBody = body;
		this.controls.minDistance = minCameraDistance(body);
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
		this.maybeLoadTexture(body);
		this.maybeLoadSystemTextures();
		if (camPos) {
			this.camOriginWorld = this.cameraTruePos();
			this.camTargetWorld = camPos;
			this.focusDurationMs = SceneRenderer.FLY_DURATION_MS;
			// Capture start orientation, compute end orientation for slerp
			this.flyQ0 = this.camera.quaternion.clone();
			const savedPos = this.camera.position.clone();
			// Temporarily place camera at target in focus-relative space (using CURRENT focusTruePos)
			this.camera.position.set(
				camPos[0] - this.focusTruePos[0],
				camPos[1] - this.focusTruePos[1],
				camPos[2] - this.focusTruePos[2]
			);
			// lookAt target body in focus-relative space
			const bodyRel = this._tmpV3.set(
				body.position[0] - this.focusTruePos[0],
				body.position[1] - this.focusTruePos[1],
				body.position[2] - this.focusTruePos[2]
			);
			this.camera.lookAt(bodyRel);
			this.flyQ1 = this.camera.quaternion.clone();
			this.camera.position.copy(savedPos);
			this.camera.quaternion.copy(this.flyQ0);
		} else {
			// Camera stays at current world position, only rotates toward new focus
			const camWorld = this.cameraTruePos();
			this.camOriginWorld = camWorld;
			this.camTargetWorld = [...camWorld];
			this.focusDurationMs = SceneRenderer.FOCUS_DURATION_MS;
			// Compute orientation slerp: current → looking at new focus body
			this.flyQ0 = this.camera.quaternion.clone();
			const savedPos = this.camera.position.clone();
			const savedQ = this.camera.quaternion.clone();
			// Temporarily place camera at final focus-relative position to compute lookAt
			this.camera.position.set(
				camWorld[0] - body.position[0],
				camWorld[1] - body.position[1],
				camWorld[2] - body.position[2]
			);
			this.camera.lookAt(0, 0, 0);
			this.flyQ1 = this.camera.quaternion.clone();
			this.camera.position.copy(savedPos);
			this.camera.quaternion.copy(savedQ);
		}
	}

	getFocusedBody(): PositionedBody | undefined {
		return this.focusedBody;
	}

	resize(width: number, height: number): void {
		this.renderer.setSize(width, height, false);
		this.labelRenderer.setSize(width, height);
		this.camera.aspect = width / height;
		this.camera.updateProjectionMatrix();
		this.ctx.updateViewport(height);
	}

	dispose(): void {
		cancelAnimationFrame(this.rafId);
		this.renderer.domElement.removeEventListener('pointerdown', this.onPointerDown);
		this.renderer.domElement.removeEventListener('pointerup', this.onPointerUp);
		this.controls.removeEventListener('end', this.onControlsEnd);
		this.controls.dispose();
		this.renderer.dispose();
	}
}
