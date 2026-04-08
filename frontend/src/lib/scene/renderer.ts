import {
	AmbientLight,
	Float32BufferAttribute,
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
	private pointerDownPos = new Vector2();

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
		if (focusBody) this.ensureBodyObjects(focusBody);

		// Apply focus-relative positions to all scene objects
		this.repositionAll();

		// Load texture for initial focus (bodyObjects is now populated)
		if (focusBody) this.maybeLoadTexture(focusBody);

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
			this.renderer.domElement,
			(body) => this.handleFocus(body)
		);
		const pts = buildPointClouds(this.ctx, this.scene, this.circleTexture, this.pointCloudBasisPos);
		this.asteroidPoints = pts.asteroidPoints;
		this.spacecraftPoints = pts.spacecraftPoints;
		this.moonPoints = pts.moonPoints;
		// Defer orbit line geometry (100K+ Kepler solves) to after first paint
		const basis = this.pointCloudBasisPos;
		requestIdleCallback(() => buildOrbitLines(this.bodyObjects, this.scene, basis), {
			timeout: 2000
		});
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

			if (
				body.data.objectType === ObjectType.BARYCENTER ||
				body.data.objectType === ObjectType.LAGRANGE_POINT
			) {
				// Virtual bodies promoted via URL navigation: always visible once built
				group.visible = true;
				if (orbitLine) orbitLine.visible = true;
				showLabel = true;
				isClose = false;
			} else if (body.data.objectType === ObjectType.MOON) {
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
			this.renderer.domElement,
			(b) => this.handleFocus(b)
		);
		buildOrbitLines(this.bodyObjects, this.scene, this.pointCloudBasisPos);
		this.repositionAll();
	}

	// --- Public API ---

	focusOnBody(id: string, zoom?: number): number {
		const body = this.ctx.getBody(id);
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
		this.ensureBodyObjects(body);
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
