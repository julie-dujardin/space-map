import {
	AmbientLight,
	DirectionalLight,
	Float32BufferAttribute,
	Mesh,
	BasicShadowMap,
	PerspectiveCamera,
	PointLight,
	Points,
	Raycaster,
	Scene,
	TextureLoader,
	Vector2,
	Vector3,
	WebGLRenderer
} from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { cartesianToSpherical, sphericalToCartesian, type MapViewState } from '$lib/url-state';
import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import { AU_SCALE, kmToScene } from '$lib/math/units';
import {
	buildMajorBodies,
	buildOrbitLines,
	buildPointClouds,
	rebuildMinorPointClouds,
	loadBodyTexture,
	loadSystemTextures,
	makeCircleTexture
} from './objects/construction';
import { type BodyObjects, type Callbacks } from './types';
import { DEFAULT_PROMOTED_IDS } from './default-bodies';
import type { Vec3 } from './animation/math';
import {
	type FocusState,
	FOCUS_DURATION_MS,
	stepFocusAnimation,
	prepareFocusTarget,
	prepareFlyToCamera
} from './animation/focus';
import { minCameraDistance } from './visibility/camera-limits';
import { updateBodyVisibility } from './visibility/update';
import { pickPointCloudBody } from './interaction/picking';

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

	// Focus/fly animation state (mutated by animation module)
	private readonly focus: FocusState = {
		focusTruePos: [0, 0, 0],
		focusOriginWorld: [0, 0, 0],
		focusTargetWorld: [0, 0, 0],
		camOriginWorld: null,
		camTargetWorld: null,
		flyQ0: null,
		flyQ1: null,
		orbitFly: false,
		focusStartTime: 0,
		focusDurationMs: FOCUS_DURATION_MS
	};
	private pointCloudBasisPos: Vec3 = [0, 0, 0];

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
		this.focus.focusTruePos = [...focusPos];
		this.focus.focusOriginWorld = [...focusPos];
		this.focus.focusTargetWorld = [...focusPos];
		this.pointCloudBasisPos = [...focusPos];
		this.focus.focusStartTime = -FOCUS_DURATION_MS; // already settled

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
		const [fx, fy, fz] = this.focus.focusTruePos;
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
		const [fx, fy, fz] = this.focus.focusTruePos;
		const [bx, by, bz] = this.pointCloudBasisPos;
		const dx = bx - fx,
			dy = by - fy,
			dz = bz - fz;
		for (const pts of this.asteroidPoints.values()) pts.position.set(dx, dy, dz);
		for (const pts of this.spacecraftPoints.values()) pts.position.set(dx, dy, dz);
		for (const pts of this.moonPoints.values()) pts.position.set(dx, dy, dz);
	}

	private rebuildPointCloudBasis(): void {
		this.pointCloudBasisPos = [...this.focus.focusTruePos];
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
			this.focus.focusTruePos[0] + this.camera.position.x,
			this.focus.focusTruePos[1] + this.camera.position.y,
			this.focus.focusTruePos[2] + this.camera.position.z
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

		// Animate focus/fly
		const controlsSettled = stepFocusAnimation(
			this.focus,
			this.camera,
			this.controls,
			() => this.repositionAll(),
			() => this.rebuildPointCloudBasis()
		);
		if (this.pendingUrlWrite && controlsSettled) {
			this.pendingUrlWrite = false;
			const { latitude, longitude, distance } = this.getCameraState();
			this.callbacks.onCameraPosition?.(latitude, longitude, distance);
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
			this.focusedBody?.data.id,
			this.hideCappedMoonLabels,
			this.hoveredBodyIds,
			this.pointCloudBasisPos,
			this.asteroidPoints,
			this.spacecraftPoints,
			this.moonPoints,
			this.cullFrameCounter,
			this.renderer,
			this._tmpV3
		);

		// Shadow light: swap between PointLight (solar system) and DirectionalLight (sub-system)
		const sysId = this.ctx.activeSystemId;
		if (sysId) {
			// Sun direction in focus-relative coordinates
			const sunPos = this.bodyObjects.get('naif-10')?.body.position;
			const [fx, fy, fz] = this.focus.focusTruePos;
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
			// Depth extent: clamped to camera vicinity so shadow-map depth
			// precision stays high (full system extent causes banding on mobile).
			const lateral = Math.max(distance * 2, 0.001);
			const depthExtent = Math.min(
				this.ctx.getSystemExtent(sysId) * AU_SCALE * 1.2,
				lateral * 4
			);
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
		const pointHit = pickPointCloudBody(
			this.pointer,
			this.camera,
			this.ctx,
			this.focus.focusTruePos,
			canvas.clientWidth,
			canvas.clientHeight,
			this._tmpV3
		);
		if (pointHit && pointHit.distance < bestDist) {
			bestBody = pointHit.body;
		}

		if (bestBody && bestBody.data.id !== this.focusedBody?.data.id) {
			this.handleFocus(bestBody);
		}
	};

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
				this.focus.focusTruePos = [...body.position];
				this.repositionAll();
				this.rebuildPointCloudBasis();
				prepareFlyToCamera(this.focus, this.camera, this.cameraTruePos(), camPos);
			} else {
				this.setFocusTarget(body, camPos);
				if (latitude !== undefined && longitude !== undefined) {
					// Use orbit mode so Earth stays centered during approach
					this.focus.orbitFly = true;
				}
			}
		} else {
			this.setFocusTarget(body);
		}
		const camWorld = this.cameraTruePos();
		const spherical = cartesianToSpherical(camWorld, body.position);
		this.callbacks.onCameraPosition?.(spherical.latitude, spherical.longitude, spherical.distance);
		return this.focus.focusDurationMs;
	}

	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.ensureBodyObjects(body);
		this.focusedBody = body;
		this.controls.minDistance = minCameraDistance(body);
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
		this.maybeLoadTexture(body);
		this.maybeLoadSystemTextures();
		prepareFocusTarget(
			this.focus,
			[...body.position],
			this.camera,
			this.cameraTruePos(),
			camPos
		);
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
