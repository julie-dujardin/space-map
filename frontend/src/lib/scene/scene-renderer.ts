import {
	AmbientLight,
	CanvasTexture,
	Float32BufferAttribute,
	Mesh,
	MeshBasicMaterial,
	MeshStandardMaterial,
	PerspectiveCamera,
	PointLight,
	Points,
	PointsMaterial,
	Raycaster,
	Scene,
	ShaderMaterial,
	SphereGeometry,
	Texture,
	TextureLoader,
	Vector2,
	Vector3,
	WebGLRenderer,
	Group,
	Line
} from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { BODY_COLORS, DEFAULT_BODY_COLOR, DEFAULT_BODY_RADIUS_KM } from '$lib/constants';
import { kmToScene } from '$lib/math/units';
import { cartesianToSpherical, sphericalToCartesian, type MapViewState } from '$lib/url-state';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { VISIBILITY, type ContextManager } from '$lib/scene/context-manager.svelte';
import { createLabel, getLabelVariant } from './label-factory';
import { makeCircleTexture, makeOrbitLine, makePointCloud } from './scene-builders';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';

// For focused objects:
// Body/halo size ratio at which the label should be hidden
const HIDE_LABEL_BODY_HALO_FACTOR = 20;
const HALO_RADIUS_PX = 16; // halo indicator is 32px diameter

function typePriority(type: ObjectType): number {
	switch (type) {
		case ObjectType.STAR:
			return 0;
		case ObjectType.PLANET:
			return 1;
		case ObjectType.DWARF_PLANET:
			return 2;
		case ObjectType.MOON:
			return 3;
		default:
			return 4; // asteroid subtypes, comet, etc.
	}
}

// --- Types ---

interface BodyObjects {
	body: PositionedBody;
	group: Group;
	mesh: Mesh;
	label: CSS2DObject | null;
	labelHalo: HTMLElement | null;
	orbitLine: Line | null;
	radiusScene: number;
}

interface Callbacks {
	onFocusChange(body: PositionedBody | undefined): void;
	onDragStart?(latitude: number, longitude: number, zoom: number): void;
	onDragEnd?(latitude: number, longitude: number, zoom: number): void;
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
	private circleTexture: CanvasTexture | null = null;
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
	private readonly _tmpV3b = new Vector3();
	private rafId = 0;
	private firstFrame = true;
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
		this.controls.addEventListener('start', this.onControlsStart);
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
		this.circleTexture = makeCircleTexture();
		this.buildMajorBodies();
		this.buildPointClouds(this.circleTexture);
	}

	rebuildMinorPointClouds(): void {
		if (!this.circleTexture) return;

		// Asteroid cloud — reuse existing Points, just replace the position attribute
		if (this.ctx.asteroidBodies.length > 0) {
			const positions = new Float32BufferAttribute(
				new Float32Array(this.ctx.asteroidBodies.flatMap((b) => b.position)),
				3
			);
			if (this.asteroidPoints) {
				this.asteroidPoints.geometry.setAttribute('position', positions);
			} else {
				this.asteroidPoints = makePointCloud(this.ctx.asteroidBodies, this.circleTexture);
				this.scene.add(this.asteroidPoints);
			}
		}

		// Spacecraft clouds — update existing groups, create new ones
		for (const [groupParentId, bodies] of this.ctx.spacecraftByParent.entries()) {
			const existing = this.spacecraftPoints.get(groupParentId);
			if (existing) {
				existing.geometry.setAttribute(
					'position',
					new Float32BufferAttribute(new Float32Array(bodies.flatMap((b) => b.position)), 3)
				);
			} else {
				const points = makePointCloud(bodies, this.circleTexture);
				this.spacecraftPoints.set(groupParentId, points);
				this.scene.add(points);
			}
		}
	}

	private buildMajorBodies(): void {
		for (const body of this.ctx.majorBodies) {
			const id = body.data.id;
			const color = BODY_COLORS[id] ?? DEFAULT_BODY_COLOR;
			const rawRadiusKm = Number.isFinite(body.data.radiusKm)
				? body.data.radiusKm
				: DEFAULT_BODY_RADIUS_KM;
			const radius = kmToScene(rawRadiusKm);
			const isStar = body.data.objectType === ObjectType.STAR;

			const group = new Group();
			group.position.set(...body.position);

			if (isStar) {
				group.add(new PointLight(0xffffff, 3, 0, 0));
			}

			const segments = isStar ? 32 : 64;
			const geometry = new SphereGeometry(radius, segments, segments);
			const material = isStar
				? new MeshBasicMaterial({ color })
				: new MeshStandardMaterial({ color });
			const mesh = new Mesh(geometry, material);
			group.add(mesh);

			this.clickables.push(mesh);
			this.meshToBody.set(mesh, body);

			// CSS2D label
			const variant = getLabelVariant(body);
			const isLarge = isStar || body.data.objectType === ObjectType.PLANET;
			const label = createLabel(
				color,
				body.data.name ?? '',
				variant,
				() => this.handleFocus(body),
				isLarge
			);
			if (label) {
				// Forward wheel events so OrbitControls zoom still works when hovering a label
				label.element.addEventListener(
					'wheel',
					(e: Event) => {
						const we = e as WheelEvent;
						this.renderer.domElement.dispatchEvent(
							new WheelEvent('wheel', {
								deltaY: we.deltaY,
								deltaMode: we.deltaMode,
								bubbles: true,
								cancelable: true
							})
						);
						we.preventDefault();
					},
					{ passive: false }
				);
				// Forward touch pointerdown events so OrbitControls sees every finger for pinch-zoom.
				// Both fingers must reach the canvas — in crowded areas both may land on labels.
				// Mouse events are NOT forwarded: setPointerCapture would steal the pointerup from
				// the label and prevent its click from firing. Touch-taps are fine because the
				// browser synthesizes click from touch location regardless of pointer capture.
				label.element.addEventListener('pointerdown', (e: PointerEvent) => {
					if (e.pointerType === 'touch') {
						this.renderer.domElement.dispatchEvent(new PointerEvent('pointerdown', e));
					}
				});
				group.add(label);
			}

			// Orbit line
			let orbitLine: Line | null = null;
			if (body.orbitElements && !isStar) {
				orbitLine = makeOrbitLine(body, color);
				this.scene.add(orbitLine);
			}

			this.scene.add(group);
			const labelHalo = label ? (label.element.firstElementChild as HTMLElement) : null;
			if (labelHalo) {
				labelHalo.dataset.origBorder = labelHalo.style.border;
			}
			this.bodyObjects.set(id, {
				body,
				group,
				mesh,
				label,
				labelHalo,
				orbitLine,
				radiusScene: radius
			});
		}
	}

	private async loadBodyTexture(fileId: string, material: MeshStandardMaterial): Promise<void> {
		const detail = await fetchObjectDetail(fileId);
		if (!detail.global?.map_texture_available) return;
		const texture = await new Promise<Texture>((resolve, reject) => {
			this.textureLoader.load(`/data/v1/textures/${fileId}/low.webp`, resolve, undefined, reject);
		});
		material.map = texture;
		material.color.set(0xffffff);
		material.needsUpdate = true;
	}

	private buildPointClouds(circleTexture: CanvasTexture): void {
		// Asteroid point cloud
		if (this.ctx.asteroidBodies.length > 0) {
			this.asteroidPoints = makePointCloud(this.ctx.asteroidBodies, circleTexture);
			this.scene.add(this.asteroidPoints);
		}

		// Spacecraft point clouds (one per parent body)
		for (const [groupParentId, bodies] of this.ctx.spacecraftByParent.entries()) {
			const points = makePointCloud(bodies, circleTexture);
			this.spacecraftPoints.set(groupParentId, points);
			this.scene.add(points);
		}

		// Moon point clouds (one per parent body, initially hidden)
		const moonsByParent = new Map<string, PositionedBody[]>();
		for (const body of this.ctx.majorBodies) {
			if (body.data.objectType === ObjectType.MOON) {
				const list = moonsByParent.get(body.data.parentId) ?? [];
				list.push(body);
				moonsByParent.set(body.data.parentId, list);
			}
		}
		for (const [parentId, moons] of moonsByParent) {
			const pts = makePointCloud(moons, circleTexture);
			(pts.material as PointsMaterial).depthTest = true;
			pts.visible = false;
			this.moonPoints.set(parentId, pts);
			this.scene.add(pts);
		}
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
		this.controls.update();

		// Camera state → visibility decisions
		const { distance } = this.getCameraState();
		this.ctx.updateCamera(distance);

		// Visibility updates
		const fovRad = (this.camera.fov * Math.PI) / 180;
		const projScale = this.renderer.domElement.clientHeight / (2 * Math.tan(fovRad / 2));

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
				this.applyLabelDisplay(
					bo,
					vis === VISIBILITY.FULL || (capped && this.hideCappedMoonLabels),
					vis === VISIBILITY.CLOSE,
					dist,
					projScale
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
				this.applyLabelDisplay(
					bo,
					vis === VISIBILITY.FULL && full,
					full && vis === VISIBILITY.CLOSE,
					dist,
					projScale
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
			if (this.isOccludedByPlanet(bx, by, bz, dist, bo.body.data.id)) {
				bo.label.visible = false;
			}
		}

		this.cullOverlappingLabels();

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
			const isFocused = bo.body.data.id === this.focusedBody?.data.id;
			const isHovered = bo.label?.element.matches(':hover') ?? false;
			mat.uniforms.uAlphaMultiplier.value = isFocused ? 2 : isHovered ? 1.75 : 1.0;
		}

		this.renderer.render(this.scene, this.camera);
		this.labelRenderer.render(this.scene, this.camera);
	};

	/**
	 * Applies label visibility for a body, handling the close-in case where the
	 * rendered sphere is large enough to replace the halo indicator.
	 */
	private applyLabelDisplay(
		bo: BodyObjects,
		show: boolean,
		isClose: boolean,
		distToBody: number,
		projScale: number
	): void {
		const { label, labelHalo, radiusScene } = bo;
		if (!label) return;

		let hideHaloRing = false;
		let screenR = 0;

		if (!show && isClose) {
			screenR = (radiusScene / distToBody) * projScale;
			// For bodies that entered CLOSE state because the camera is near their parent
			// (e.g. outer moons when zoomed into Saturn), screenR is near-zero even though
			// the body is physically far. Skip the close logic unless we're actually zoomed
			// into this specific body (isFocused) or it's large enough on screen (screenR >= 1).
			const isFocused = bo.body.data.id === this.focusedBody?.data.id;
			if (isFocused || screenR >= 1) {
				show = screenR < HALO_RADIUS_PX * HIDE_LABEL_BODY_HALO_FACTOR;
				hideHaloRing = screenR >= HALO_RADIUS_PX;
				if (bo.orbitLine) bo.orbitLine.visible = !hideHaloRing;
			}
		}

		label.visible = show;
		if (labelHalo) labelHalo.style.visibility = hideHaloRing ? 'hidden' : '';
		label.center.x = hideHaloRing ? 1 - screenR / 32 : 0.5;
	}

	/**
	 * Returns true if the point (bx,by,bz) at distance bodyDist from the camera
	 * lies within the angular cone of any planet sphere (i.e. is occluded by it).
	 * selfId is excluded so a planet doesn't occlude its own label.
	 */
	private isOccludedByPlanet(
		bx: number,
		by: number,
		bz: number,
		bodyDist: number,
		selfId: string
	): boolean {
		const cam = this.camera.position;
		for (const bo of this.bodyObjects.values()) {
			if (bo.body.data.objectType !== ObjectType.PLANET) continue;
			if (bo.body.data.id === selfId) continue;
			this._tmpV3.set(...bo.body.position);
			const planetDist = cam.distanceTo(this._tmpV3);
			if (planetDist >= bodyDist) continue; // planet is behind the body
			// Direction camera → body
			this._tmpV3b.set(bx, by, bz).sub(cam).normalize();
			// Direction camera → planet centre (reuse _tmpV3)
			this._tmpV3.sub(cam).normalize();
			const cosAngle = this._tmpV3b.dot(this._tmpV3);
			if (cosAngle <= 0) continue;
			const sinOcclude = bo.radiusScene / planetDist;
			if (sinOcclude >= 1) continue;
			if (cosAngle >= Math.sqrt(1 - sinOcclude * sinOcclude)) return true;
		}
		return false;
	}

	private cullOverlappingLabels(): void {
		const w = this.renderer.domElement.clientWidth;
		const h = this.renderer.domElement.clientHeight;

		// Estimated label bounding box in CSS pixels
		const LW = 90;
		const LH = 22;

		type Candidate = {
			body: PositionedBody;
			label: CSS2DObject;
			labelHalo: HTMLElement | null;
			isCapped: boolean;
			isFocused: boolean;
			isSelected: boolean;
			screenX: number;
			screenY: number;
			dist: number;
		};

		const candidates: Candidate[] = [];

		for (const { body, label, labelHalo } of this.bodyObjects.values()) {
			if (!label?.visible) continue;
			this._tmpV3.set(...body.position);
			const dist = this.camera.position.distanceTo(this._tmpV3);
			this._tmpV3.project(this.camera);
			if (this._tmpV3.z > 1) continue;
			const isFocused = body.data.id === this.focusedBody?.data.id;
			const isHovered = label.element.matches(':hover');
			candidates.push({
				body,
				label,
				labelHalo,
				isCapped:
					body.data.objectType === ObjectType.MOON
						? this.ctx.getMoonVisibility(body) === VISIBILITY.CAPPED
						: false,
				isFocused,
				isSelected: isFocused || isHovered,
				screenX: (this._tmpV3.x * 0.5 + 0.5) * w,
				screenY: (-this._tmpV3.y * 0.5 + 0.5) * h,
				dist
			});
		}

		// Sort: selected first, then by type priority, then closer first
		candidates.sort((a, b) => {
			if (a.isSelected !== b.isSelected) return a.isSelected ? -1 : 1;
			const pa = typePriority(a.body.data.objectType);
			const pb = typePriority(b.body.data.objectType);
			if (pa !== pb) return pa - pb;
			return a.dist - b.dist;
		});

		const accepted: { x: number; y: number }[] = [];
		for (const {
			label,
			labelHalo,
			isCapped,
			isFocused,
			isSelected,
			screenX,
			screenY
		} of candidates) {
			const nameSpan = labelHalo?.nextElementSibling as HTMLElement | null;
			if (isCapped && !isSelected) {
				this.dimLabel(labelHalo, nameSpan);
				continue;
			}
			const overlaps = accepted.some(
				({ x, y }) => Math.abs(screenX - x) < LW && Math.abs(screenY - y) < LH
			);
			if (!overlaps) {
				accepted.push({ x: screenX, y: screenY });
				this.restoreLabel(labelHalo, nameSpan, label.element.matches(':hover'), isFocused);
			} else {
				this.dimLabel(labelHalo, nameSpan);
			}
		}
	}

	private dimLabel(labelHalo: HTMLElement | null, nameSpan: HTMLElement | null): void {
		if (labelHalo) labelHalo.style.transform = 'scale(0.3)';
		if (nameSpan) {
			nameSpan.style.display = 'none';
			nameSpan.style.fontSize = '';
		}
	}

	private restoreLabel(
		labelHalo: HTMLElement | null,
		nameSpan: HTMLElement | null,
		isHovered: boolean,
		isFocused: boolean
	): void {
		if (labelHalo) {
			if (!isHovered) labelHalo.style.transform = '';
			labelHalo.style.border = labelHalo.dataset.origBorder ?? '';
		}
		if (nameSpan) {
			nameSpan.style.display = '';
			nameSpan.style.fontSize = isFocused ? '18px' : '';
		}
	}

	// --- Interaction ---

	private getCameraState() {
		const cam = this.camera.position;
		const tgt = this.controls.target;
		return cartesianToSpherical([cam.x, cam.y, cam.z], [tgt.x, tgt.y, tgt.z]);
	}

	private onControlsStart = (): void => {
		const { latitude, longitude, distance } = this.getCameraState();
		this.callbacks.onDragStart?.(latitude, longitude, distance);
	};

	private onControlsEnd = (): void => {
		const { latitude, longitude, distance } = this.getCameraState();
		this.callbacks.onDragEnd?.(latitude, longitude, distance);
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
		if (bo) this.loadBodyTexture(id, bo.mesh.material as MeshStandardMaterial);
	}

	private handleFocus(body: PositionedBody): void {
		this.focusedBody = body;
		this.focusTarget.set(...body.position);
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
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
		this.controls.removeEventListener('start', this.onControlsStart);
		this.controls.removeEventListener('end', this.onControlsEnd);
		this.controls.dispose();
		this.renderer.dispose();
	}
}
