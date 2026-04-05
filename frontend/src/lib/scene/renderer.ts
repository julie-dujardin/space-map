import {
	AmbientLight,
	Mesh,
	PerspectiveCamera,
	Points,
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
	private asteroidPoints: Points | null = null;
	private textureLoaded = new Set<string>();
	private spacecraftPoints = new Map<string, Points>();
	private moonPoints = new Map<string, Points>();
	private clickables: Mesh[] = [];
	private meshToBody = new Map<Mesh, PositionedBody>();

	// TODO: expose via UI settings
	hideCappedMoonLabels = false;

	private focusedBody: PositionedBody | undefined;
	private focusTarget = new Vector3();
	private readonly _tmpV3 = new Vector3();
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
		const focusPos: [number, number, number] = focusBody?.position ?? [0, 0, 0];

		this.focusedBody = focusBody;
		this.focusTarget.set(...focusPos);

		const camPos = sphericalToCartesian(
			focusPos,
			initialView.latitude,
			initialView.longitude,
			initialView.zoom
		);
		this.camera.position.set(...camPos);

		// OrbitControls
		this.controls = new OrbitControls(this.camera, canvas);
		this.controls.enableDamping = true;
		this.controls.target.set(...focusPos);
		this.controls.update();
		this.controls.addEventListener('end', this.onControlsEnd);

		// Sync context initial state
		if (focusBody) ctx.setFocused(focusBody);
		ctx.updateCamera(initialView.zoom);

		// Notify initial focus
		callbacks.onFocusChange(focusBody);

		// Build all scene objects
		this.buildScene();

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
		const pts = buildPointClouds(this.ctx, this.scene, this.circleTexture);
		this.asteroidPoints = pts.asteroidPoints;
		this.spacecraftPoints = pts.spacecraftPoints;
		this.moonPoints = pts.moonPoints;
		// Defer orbit line geometry (100K+ Kepler solves) to after first paint
		requestIdleCallback(() => buildOrbitLines(this.bodyObjects, this.scene), { timeout: 2000 });
	}

	rebuildMinorPointClouds(): void {
		this.asteroidPoints = rebuildMinorPointClouds(
			this.ctx,
			this.circleTexture,
			this.asteroidPoints,
			this.spacecraftPoints,
			this.scene
		);
	}

	// --- RAF loop ---

	private tick = (): void => {
		this.rafId = requestAnimationFrame(this.tick);

		// Snap controls target on first frame
		if (this.firstFrame) {
			this.firstFrame = false;
			this.controls.target.copy(this.focusTarget);
			this.controls.update();
		}

		// Lerp controls target
		const isAnimating = this.controls.target.distanceToSquared(this.focusTarget) > 0.0001;
		if (isAnimating) {
			this.controls.target.lerp(this.focusTarget, 0.08);
		} else {
			this.controls.target.copy(this.focusTarget);
		}
		const controlsSettled = !this.controls.update();
		if (this.pendingUrlWrite && controlsSettled) {
			this.pendingUrlWrite = false;
			const { latitude, longitude, distance } = this.getCameraState();
			this.callbacks.onCameraPosition?.(latitude, longitude, distance);
		}

		// Camera state → visibility decisions
		const { distance } = this.getCameraState();
		this.ctx.updateCamera(distance);

		// Visibility updates
		const fovRad = (this.camera.fov * Math.PI) / 180;
		const projScale = this.renderer.domElement.clientHeight / (2 * Math.tan(fovRad / 2));
		const focusedBodyId = this.focusedBody?.data.id;

		for (const bo of this.bodyObjects.values()) {
			const { body, group, orbitLine } = bo;

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
				this._tmpV3.set(...body.position);
				const dist = this.camera.position.distanceTo(this._tmpV3);
				if (orbitLine) orbitLine.visible = vis === VISIBILITY.FULL;
				applyLabelDisplay(
					bo,
					vis === VISIBILITY.FULL || (capped && this.hideCappedMoonLabels),
					vis === VISIBILITY.CLOSE,
					dist,
					projScale,
					focusedBodyId
				);
			} else if (body.data.objectType === ObjectType.STAR) {
				group.visible = true;
				if (bo.label) bo.label.visible = true;
			} else {
				this._tmpV3.set(...body.position);
				const dist = this.camera.position.distanceTo(this._tmpV3);
				const vis = this.ctx.getPlanetVisibility(body, dist);
				const full = this.ctx.hasFullRendering(body);
				group.visible =
					vis === VISIBILITY.CLOSE || vis === VISIBILITY.FULL || vis === VISIBILITY.FAR;
				if (orbitLine) orbitLine.visible = vis === VISIBILITY.FULL && full;
				applyLabelDisplay(
					bo,
					vis === VISIBILITY.FULL && full,
					full && vis === VISIBILITY.CLOSE,
					dist,
					projScale,
					focusedBodyId
				);
			}
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
			this._tmpV3.set(bx, by, bz);
			const dist = this.camera.position.distanceTo(this._tmpV3);
			if (
				isOccludedByPlanet(
					bx,
					by,
					bz,
					dist,
					bo.body.data.id,
					this.camera.position,
					this.bodyObjects
				)
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
			this.ctx
		);

		// Update camera-relative offset uniforms for trail lines (prevents float32 precision flicker)
		// Also update alpha multiplier for hover/focus highlight
		for (const bo of this.bodyObjects.values()) {
			const line = bo.orbitLine;
			if (!line?.visible) continue;
			const oc = line.userData.orbitCenter as Vector3;
			const mat = line.material as ShaderMaterial;
			mat.uniforms.uCenterOffset.value.set(
				oc.x - this.camera.position.x,
				oc.y - this.camera.position.y,
				oc.z - this.camera.position.z
			);
			const isFocused = bo.body.data.id === focusedBodyId;
			const isHovered = bo.label?.element.matches(':hover') ?? false;
			mat.uniforms.uAlphaMultiplier.value = isFocused ? 2 : isHovered ? 1.75 : 1.0;
		}

		this.renderer.render(this.scene, this.camera);
		this.labelRenderer.render(this.scene, this.camera);
	};

	// --- Interaction ---

	private getCameraState(target = this.controls.target) {
		const cam = this.camera.position;
		return cartesianToSpherical([cam.x, cam.y, cam.z], [target.x, target.y, target.z]);
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
		this.focusedBody = body;
		this.focusTarget.set(...body.position);
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
		const { latitude, longitude, distance } = this.getCameraState(this.focusTarget);
		this.callbacks.onCameraPosition?.(latitude, longitude, distance);
		this.maybeLoadTexture(body);
	}

	// --- Public API ---

	setFocusTarget(body: PositionedBody, camPos?: [number, number, number]): void {
		this.focusedBody = body;
		this.focusTarget.set(...body.position);
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
		this.maybeLoadTexture(body);
		if (camPos) this.camera.position.set(...camPos);
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
