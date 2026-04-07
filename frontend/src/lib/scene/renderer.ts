import {
	AmbientLight,
	Mesh,
	PerspectiveCamera,
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
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { VISIBILITY, type ContextManager } from '$lib/scene/context-manager.svelte';
import { applyLabelDisplay, isOccludedByPlanet, cullOverlappingLabels } from './label/culling';
import {
	buildMajorBodies,
	buildOrbitLines,
	buildPointClouds,
	rebuildMinorPointClouds,
	loadBodyTexture,
	makeCircleTexture
} from './construction';
import type { BodyObjects, Callbacks } from './types';

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

// --- SceneRenderer ---

export class SceneRenderer {
	private renderer: WebGLRenderer;
	private labelRenderer: CSS2DRenderer;
	private scene: Scene;
	private camera: PerspectiveCamera;
	private controls: OrbitControls;
	private raycaster = new Raycaster();
	private pointer = new Vector2();

	private ctx: ContextManager;
	private callbacks: Callbacks;

	private bodyObjects = new Map<string, BodyObjects>();
	private circleTexture = makeCircleTexture();
	private asteroidPoints = new Map<string, Points>();
	private textureLoaded = new Set<string>();
	private spacecraftPoints = new Map<string, Points>();
	private moonPoints = new Map<string, Points>();
	private clickables: Mesh[] = [];
	private meshToBody = new Map<Mesh, PositionedBody>();
	private pendingSceneAdds: Points[] = [];

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
	private focusStartTime = 0;
	private static readonly FOCUS_DURATION_MS = 350;
	private static readonly FLY_DURATION_MS = 1600;
	private focusDurationMs = SceneRenderer.FOCUS_DURATION_MS;
	private rafId = 0;
	private firstFrame = true;
	private pendingUrlWrite = false;
	private readonly textureLoader = new TextureLoader();

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

		// CSS2D label renderer
		this.labelRenderer = new CSS2DRenderer({ element: labelContainer });
		this.labelRenderer.setSize(canvas.clientWidth, canvas.clientHeight);
		ctx.updateViewport(canvas.clientHeight);

		// Scene + lights
		this.scene = new Scene();
		this.scene.add(new AmbientLight(0xffffff, 0.05));

		// Camera
		const aspect = canvas.clientWidth / canvas.clientHeight;
		this.camera = new PerspectiveCamera(60, aspect, 0.000001, 100000);

		// Set initial camera position from URL state
		const sunBody = ctx.majorBodies.find((b) => b.data.id === 'naif-10');
		const allBodies = ctx.allBodies;
		const matchedBody = allBodies.find((b) => b.data.id === initialView.id);
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

		// If focused body has no visual objects (e.g. placeholder from global file), build them.
		// Skip barycenters/Lagrange points — they are structural, not renderable.
		if (
			focusBody &&
			!this.bodyObjects.has(focusBody.data.id) &&
			focusBody.data.objectType !== ObjectType.BARYCENTER &&
			focusBody.data.objectType !== ObjectType.LAGRANGE_POINT
		) {
			buildMajorBodies(
				[focusBody],
				this.scene,
				this.clickables,
				this.meshToBody,
				this.bodyObjects,
				canvas,
				(body) => this.handleFocus(body)
			);
			buildOrbitLines(this.bodyObjects, this.scene);
		}

		// Apply focus-relative positions to all scene objects
		this.repositionAll();

		// Load texture for initial focus (bodyObjects is now populated)
		if (focusBody) this.maybeLoadTexture(focusBody);

		// Click handler
		canvas.addEventListener('pointerdown', this.onPointerDown);

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
			this.renderer.domElement,
			(body) => this.handleFocus(body)
		);
		const pts = buildPointClouds(this.ctx, this.scene, this.circleTexture, this.pointCloudBasisPos);
		this.asteroidPoints = pts.asteroidPoints;
		this.spacecraftPoints = pts.spacecraftPoints;
		this.moonPoints = pts.moonPoints;
		// Defer orbit line geometry (100K+ Kepler solves) to after first paint
		requestIdleCallback(() => buildOrbitLines(this.bodyObjects, this.scene), { timeout: 2000 });
	}

	rebuildMinorPointClouds(): void {
		const newPoints = rebuildMinorPointClouds(
			this.ctx,
			this.circleTexture,
			this.asteroidPoints,
			this.spacecraftPoints,
			this.pointCloudBasisPos
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
			bo.group.position.set(bx - fx, by - fy, bz - fz);
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
		// Reset point cloud object positions since basis matches focus
		for (const pts of this.asteroidPoints.values()) pts.position.set(0, 0, 0);
		for (const pts of this.spacecraftPoints.values()) pts.position.set(0, 0, 0);
		for (const pts of this.moonPoints.values()) pts.position.set(0, 0, 0);
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
			// Skip controls.update() — we're driving the camera directly
			controlsSettled = false;
		} else if (isAnimating) {
			const s = t * t * (3 - 2 * t);
			this.focusTruePos = f64lerp(this.focusOriginWorld, this.focusTargetWorld, s);
			this.repositionAll();
			this.controls.target.set(0, 0, 0);
			controlsSettled = !this.controls.update();
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
				this.camera.position.set(
					this.camTargetWorld[0] - this.focusTruePos[0],
					this.camTargetWorld[1] - this.focusTruePos[1],
					this.camTargetWorld[2] - this.focusTruePos[2]
				);
				this.camOriginWorld = null;
				this.camTargetWorld = null;
				this.flyQ0 = null;
				this.flyQ1 = null;
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

		for (const bo of this.bodyObjects.values()) {
			const { body, group, orbitLine } = bo;
			const dist = f64dist(camTrue, body.position);

			let showLabel: boolean;
			let isClose: boolean;

			if (body.data.objectType === ObjectType.MOON) {
				const vis = this.ctx.getMoonVisibility(body);
				// By default (hideCappedMoonLabels=false), CAPPED moons are demoted to the
				// parent's point cloud. When hideCappedMoonLabels=true, they render individually
				// with dimmed labels instead.
				const capped = vis === VISIBILITY.CAPPED;
				group.visible =
					vis === VISIBILITY.CLOSE ||
					vis === VISIBILITY.FULL ||
					(capped && this.hideCappedMoonLabels);
				if (orbitLine) orbitLine.visible = vis === VISIBILITY.FULL;
				showLabel = vis === VISIBILITY.FULL || (capped && this.hideCappedMoonLabels);
				isClose = vis === VISIBILITY.CLOSE;
			} else if (body.data.objectType === ObjectType.STAR) {
				group.visible = true;
				const screenR = (bo.radiusScene / dist) * projScale;
				isClose = screenR >= 1;
				showLabel = !isClose;
			} else {
				const vis = this.ctx.getPlanetVisibility(body, dist);
				const full = this.ctx.hasFullRendering(body);
				group.visible =
					vis === VISIBILITY.CLOSE || vis === VISIBILITY.FULL || vis === VISIBILITY.FAR;
				if (orbitLine) orbitLine.visible = vis === VISIBILITY.FULL && full;
				showLabel = vis === VISIBILITY.FULL && full;
				isClose = full && vis === VISIBILITY.CLOSE;
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

		// Hide labels of bodies occluded by a planet sphere
		for (const bo of this.bodyObjects.values()) {
			if (!bo.label?.visible) continue;
			if (bo.body.data.objectType === ObjectType.STAR) continue;
			const [bx, by, bz] = bo.body.position;
			const dist = f64dist(camTrue, bo.body.position);
			if (
				isOccludedByPlanet(bx, by, bz, dist, bo.body.data.id, this._camWorldV3, this.bodyObjects)
			) {
				bo.label.visible = false;
			}
		}

		cullOverlappingLabels(
			this.bodyObjects,
			this.renderer.domElement.clientWidth,
			this.renderer.domElement.clientHeight,
			this.camera,
			focusedBodyId,
			this.ctx,
			this.focusTruePos
		);

		// Update camera-relative offset uniforms for trail lines (prevents float32 precision flicker)
		// Also update alpha multiplier for hover/focus highlight
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (!line?.visible) continue;
			const oc = line.userData.orbitCenter as Vector3;
			const mat = line.material as ShaderMaterial;
			// (orbitCenter - focusTruePos) in Float64 first, then subtract camera.position (small)
			mat.uniforms.uCenterOffset.value.set(
				oc.x - this.focusTruePos[0] - this.camera.position.x,
				oc.y - this.focusTruePos[1] - this.camera.position.y,
				oc.z - this.focusTruePos[2] - this.camera.position.z
			);
			const isFocused = bo.body.data.id === focusedBodyId;
			const isHovered = bo.label?.element.matches(':hover') ?? false;
			mat.uniforms.uAlphaMultiplier.value = isFocused ? 2 : isHovered ? 1.75 : 1.0;
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
		const canvas = this.renderer.domElement;
		const rect = canvas.getBoundingClientRect();
		this.pointer.set(
			((e.clientX - rect.left) / rect.width) * 2 - 1,
			-((e.clientY - rect.top) / rect.height) * 2 + 1
		);
		this.raycaster.setFromCamera(this.pointer, this.camera);
		const hits = this.raycaster.intersectObjects(this.clickables);
		if (hits.length > 0) {
			const body = this.meshToBody.get(hits[0].object as Mesh);
			if (body) this.handleFocus(body);
		}
	};

	private maybeLoadTexture(body: PositionedBody): void {
		const id = body.data.id;
		if (this.textureLoaded.has(id)) return;
		this.textureLoaded.add(id);
		const bo = this.bodyObjects.get(id);
		if (bo)
			loadBodyTexture(
				id,
				bo.mesh.material as import('three').MeshStandardMaterial,
				this.textureLoader
			);
	}

	private handleFocus(body: PositionedBody): void {
		this.setFocusTarget(body);
		const camWorld = this.cameraTruePos();
		const { latitude, longitude, distance } = cartesianToSpherical(camWorld, body.position);
		this.callbacks.onCameraPosition?.(latitude, longitude, distance);
	}

	// --- Public API ---

	focusOnBody(id: string, zoom?: number): number {
		const body = this.ctx.allBodies.find((b) => b.data.id === id);
		if (!body) return 0;
		if (zoom !== undefined) {
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
			const camPos: Vec3 = [
				body.position[0] + dir.x * zoom,
				body.position[1] + dir.y * zoom,
				body.position[2] + dir.z * zoom
			];
			this.setFocusTarget(body, camPos);
		} else {
			this.setFocusTarget(body);
		}
		const camWorld = this.cameraTruePos();
		const { latitude, longitude, distance } = cartesianToSpherical(camWorld, body.position);
		this.callbacks.onCameraPosition?.(latitude, longitude, distance);
		return this.focusDurationMs;
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.focusOriginWorld = [...this.focusTruePos];
		this.focusTargetWorld = [...body.position];
		this.focusStartTime = performance.now();
		this.focusedBody = body;
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
		this.maybeLoadTexture(body);
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
			this.camOriginWorld = null;
			this.camTargetWorld = null;
			this.flyQ0 = null;
			this.flyQ1 = null;
			this.focusDurationMs = SceneRenderer.FOCUS_DURATION_MS;
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
		this.controls.removeEventListener('end', this.onControlsEnd);
		this.controls.dispose();
		this.renderer.dispose();
	}
}
