import {
	AmbientLight,
	BufferGeometry,
	CanvasTexture,
	Color,
	Float32BufferAttribute,
	Line,
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
	Vector2,
	Vector3,
	WebGLRenderer,
	Group
} from 'three';
import { CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
	BODY_COLORS,
	BODY_RADII_KM,
	DEFAULT_BODY_COLOR,
	DEFAULT_BODY_RADIUS_KM
} from '$lib/constants';
import { kmToScene } from '$lib/math/units';
import { orbitalElementsToEllipse } from '$lib/math/kepler';
import { cartesianToSpherical, sphericalToCartesian, type MapViewState } from '$lib/url-state';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { VISIBILITY, type ContextManager } from '$lib/context-manager.svelte';
import { createLabel, getLabelVariant } from './label-factory';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

// --- Types ---

interface BodyObjects {
	body: PositionedBody;
	group: Group;
	mesh: Mesh;
	label: CSS2DObject | null;
	labelHalo: HTMLElement | null;
	orbitLine: Line | null;
}

interface Callbacks {
	onFocusChange(body: PositionedBody | undefined): void;
	onFrame(latitude: number, longitude: number, zoom: number): void;
}

// --- Helpers ---

function makeCircleTexture(): CanvasTexture {
	const size = 32;
	const canvas = document.createElement('canvas');
	canvas.width = size;
	canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	ctx.beginPath();
	ctx.arc(size / 2, size / 2, size / 2 - 2, 0, Math.PI * 2);
	ctx.fillStyle = '#aaaaaa';
	ctx.globalAlpha = 0.3;
	ctx.fill();
	return new CanvasTexture(canvas);
}

const NUM_ORBIT_POINTS = 512;

function makeOrbitLine(body: PositionedBody, color: string): Line {
	const { orbitElements, orbitCenter, data } = body;
	if (!orbitElements) throw new Error('makeOrbitLine called without orbitElements');

	const ellipse = orbitalElementsToEllipse(orbitElements, NUM_ORBIT_POINTS);

	// Body position in orbit-local coordinates
	const cx = orbitCenter?.[0] ?? 0;
	const cy = orbitCenter?.[1] ?? 0;
	const cz = orbitCenter?.[2] ?? 0;
	const bodyLocal: [number, number, number] = [
		body.position[0] - cx,
		body.position[1] - cy,
		body.position[2] - cz
	];

	// Find trail start point (behind the body in orbital direction)
	let nearest = 0;
	let best = Infinity;
	for (let j = 0; j < NUM_ORBIT_POINTS; j++) {
		const d =
			(ellipse[j][0] - bodyLocal[0]) ** 2 +
			(ellipse[j][1] - bodyLocal[1]) ** 2 +
			(ellipse[j][2] - bodyLocal[2]) ** 2;
		if (d < best) {
			best = d;
			nearest = j;
		}
	}
	const prev = (nearest - 1 + NUM_ORBIT_POINTS) % NUM_ORBIT_POINTS;
	const next = (nearest + 1) % NUM_ORBIT_POINTS;
	const distPrev =
		(ellipse[prev][0] - bodyLocal[0]) ** 2 +
		(ellipse[prev][1] - bodyLocal[1]) ** 2 +
		(ellipse[prev][2] - bodyLocal[2]) ** 2;
	const distNext =
		(ellipse[next][0] - bodyLocal[0]) ** 2 +
		(ellipse[next][1] - bodyLocal[1]) ** 2 +
		(ellipse[next][2] - bodyLocal[2]) ** 2;
	const trailStart = distPrev < distNext ? prev : nearest;

	const useTrail =
		data.objectType === ObjectType.DWARF_PLANET || data.objectType === ObjectType.MOON;
	const trailFraction = useTrail ? 1 / 3 : undefined;
	const trailLen = trailFraction ? Math.round(trailFraction * NUM_ORBIT_POINTS) : NUM_ORBIT_POINTS;
	const closeLoop = !trailFraction;

	const points: [number, number, number][] = [bodyLocal];
	for (let k = 0; k < trailLen - 1; k++) {
		points.push(
			ellipse[(((trailStart - k) % NUM_ORBIT_POINTS) + NUM_ORBIT_POINTS) % NUM_ORBIT_POINTS]
		);
	}
	if (closeLoop) points.push(bodyLocal);

	const maxAlpha = trailFraction ? 0.6 : 0.9;
	const minAlpha = trailFraction ? 0 : maxAlpha / 3;
	const alphas = new Float32Array(points.length);
	for (let k = 0; k < points.length; k++) {
		alphas[k] = maxAlpha - (k / (points.length - 1)) * (maxAlpha - minAlpha);
	}

	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(new Float32Array(points.flat()), 3));
	geometry.setAttribute('alpha', new Float32BufferAttribute(alphas, 1));

	const material = new ShaderMaterial({
		transparent: true,
		uniforms: { uColor: { value: new Color(color) } },
		vertexShader: `
			attribute float alpha;
			varying float vAlpha;
			void main() {
				vAlpha = alpha;
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}
		`,
		fragmentShader: `
			uniform vec3 uColor;
			varying float vAlpha;
			void main() {
				gl_FragColor = vec4(uColor, vAlpha);
			}
		`
	});

	const line = new Line(geometry, material);
	line.position.set(cx, cy, cz);
	return line;
}

function makePointCloud(bodies: PositionedBody[], texture: CanvasTexture): Points {
	const positions = new Float32Array(bodies.flatMap((b) => b.position));
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
	const material = new PointsMaterial({
		map: texture,
		transparent: true,
		size: 4,
		sizeAttenuation: false,
		depthTest: false
	});
	return new Points(geometry, material);
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

	private bodyObjects = new Map<number, BodyObjects>();
	private asteroidPoints: Points | null = null;
	private spacecraftPoints = new Map<number, Points>();
	private moonPoints = new Map<number, Points>();
	private clickables: Mesh[] = [];
	private meshToBody = new Map<Mesh, PositionedBody>();

	private focusedBody: PositionedBody | undefined;
	private focusTarget = new Vector3();
	private readonly _tmpV3 = new Vector3();
	private rafId = 0;
	private firstFrame = true;

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

		// Scene + lights
		this.scene = new Scene();
		this.scene.add(new AmbientLight(0xffffff, 0.4));

		// Camera
		const aspect = canvas.clientWidth / canvas.clientHeight;
		this.camera = new PerspectiveCamera(60, aspect, 0.0001, 100000);

		// Set initial camera position from URL state
		const sunBody = ctx.majorBodies.find((b) => b.data.id === 10);
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

		// Sync context initial state
		if (focusBody) ctx.setFocused(focusBody);
		ctx.updateCamera(initialView.zoom);

		// Notify initial focus
		callbacks.onFocusChange(focusBody);

		// Build all scene objects
		this.buildScene();

		// Click handler
		canvas.addEventListener('pointerdown', this.onPointerDown);

		// Start loop
		this.tick();
	}

	// --- Scene construction ---

	private buildScene(): void {
		const circleTexture = makeCircleTexture();

		for (const body of this.ctx.majorBodies) {
			const id = body.data.id;
			const color = BODY_COLORS[id] ?? DEFAULT_BODY_COLOR;
			const rawRadiusKm =
				BODY_RADII_KM[id] ??
				(Number.isFinite(body.data.radiusKm) ? body.data.radiusKm : DEFAULT_BODY_RADIUS_KM);
			const radius = kmToScene(rawRadiusKm);
			const isStar = body.data.objectType === ObjectType.STAR;

			const group = new Group();
			group.position.set(...body.position);

			if (isStar) {
				group.add(new PointLight(0xffffff, 2));
			}

			const segments = isStar ? 32 : 16;
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
			const label = createLabel(color, body.data.name ?? '', variant, () => this.handleFocus(body));
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
			this.bodyObjects.set(id, { body, group, mesh, label, labelHalo, orbitLine });
		}

		// Asteroid point cloud
		if (this.ctx.asteroidBodies.length > 0) {
			this.asteroidPoints = makePointCloud(this.ctx.asteroidBodies, circleTexture);
			this.scene.add(this.asteroidPoints);
		}

		// Spacecraft point clouds
		for (const [groupParentId, bodies] of this.ctx.spacecraftByParent.entries()) {
			const points = makePointCloud(bodies, circleTexture);
			this.spacecraftPoints.set(groupParentId, points);
			this.scene.add(points);
		}

		// Moon point clouds (one per parent body, initially hidden)
		const moonsByParent = new Map<number, PositionedBody[]>();
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

		// Camera state → visibility decisions + URL sync
		const cam = this.camera.position;
		const tgt = this.controls.target;
		const { latitude, longitude, distance } = cartesianToSpherical(
			[cam.x, cam.y, cam.z],
			[tgt.x, tgt.y, tgt.z]
		);
		this.ctx.updateCamera(distance);

		// Visibility updates
		for (const { body, group, label, orbitLine } of this.bodyObjects.values()) {
			if (body.data.objectType === ObjectType.MOON) {
				const vis = this.ctx.getMoonVisibility(body);
				group.visible =
					vis === VISIBILITY.CLOSE || vis === VISIBILITY.FULL || vis === VISIBILITY.CAPPED;
				if (label) label.visible = vis === VISIBILITY.FULL || vis === VISIBILITY.CAPPED;
				if (orbitLine) orbitLine.visible = vis === VISIBILITY.FULL;
			} else if (body.data.objectType === ObjectType.STAR) {
				group.visible = true;
				if (label) label.visible = true;
			} else {
				this._tmpV3.set(body.position[0], body.position[1], body.position[2]);
				const distToBody = this.camera.position.distanceTo(this._tmpV3);
				const vis = this.ctx.getPlanetVisibility(body, distToBody);
				const full = this.ctx.hasFullRendering(body);
				group.visible = vis !== VISIBILITY.HIDE;
				if (label) label.visible = vis === VISIBILITY.FULL && full;
				if (orbitLine) orbitLine.visible = vis === VISIBILITY.FULL && full;
			}
		}
		for (const [gid, pts] of this.spacecraftPoints) {
			pts.visible = this.ctx.isSpacecraftGroupVisible(gid);
		}
		for (const [parentId, pts] of this.moonPoints) {
			pts.visible = this.ctx.isMoonGroupVisible(parentId);
		}

		this.cullOverlappingLabels();

		if (!isAnimating) {
			this.callbacks.onFrame(latitude, longitude, distance);
		}

		this.renderer.render(this.scene, this.camera);
		this.labelRenderer.render(this.scene, this.camera);
	};

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
			screenX: number;
			screenY: number;
			dist: number;
		};

		// Sun always wins — seed accepted with its screen position
		const accepted: { x: number; y: number }[] = [];
		for (const { body, label } of this.bodyObjects.values()) {
			if (body.data.objectType !== ObjectType.STAR || !label?.visible) continue;
			this._tmpV3.set(body.position[0], body.position[1], body.position[2]);
			this._tmpV3.project(this.camera);
			if (this._tmpV3.z <= 1)
				accepted.push({ x: (this._tmpV3.x * 0.5 + 0.5) * w, y: (-this._tmpV3.y * 0.5 + 0.5) * h });
		}

		const planetCandidates: Candidate[] = [];
		const moonCandidates: Candidate[] = [];

		for (const { body, label, labelHalo } of this.bodyObjects.values()) {
			if (body.data.objectType === ObjectType.STAR || !label?.visible) continue;
			this._tmpV3.set(body.position[0], body.position[1], body.position[2]);
			const dist = this.camera.position.distanceTo(this._tmpV3);
			this._tmpV3.project(this.camera);
			if (this._tmpV3.z > 1) continue;
			const candidate: Candidate = {
				body,
				label,
				labelHalo,
				isCapped:
					body.data.objectType === ObjectType.MOON
						? this.ctx.getMoonVisibility(body) === VISIBILITY.CAPPED
						: false,
				screenX: (this._tmpV3.x * 0.5 + 0.5) * w,
				screenY: (-this._tmpV3.y * 0.5 + 0.5) * h,
				dist
			};
			if (body.data.objectType === ObjectType.MOON) moonCandidates.push(candidate);
			else planetCandidates.push(candidate);
		}

		// Helper: apply or restore dimming
		const dim = (labelHalo: HTMLElement | null, nameSpan: HTMLElement | null) => {
			if (labelHalo) {
				labelHalo.style.transform = 'scale(0.3)';
				labelHalo.style.border = 'none';
			}
			if (nameSpan) nameSpan.style.display = 'none';
		};
		const restore = (
			labelHalo: HTMLElement | null,
			nameSpan: HTMLElement | null,
			isHovered: boolean
		) => {
			if (labelHalo) {
				if (!isHovered) labelHalo.style.transform = '';
				labelHalo.style.border = labelHalo.dataset.origBorder ?? '';
			}
			if (nameSpan) nameSpan.style.display = '';
		};

		// Planets: closest wins over farther ones
		planetCandidates.sort((a, b) => a.dist - b.dist);
		for (const { body, label, labelHalo, screenX, screenY } of planetCandidates) {
			const isFocused = body.data.id === this.focusedBody?.data.id;
			const isHovered = label.element.matches(':hover');
			const forceShow = isFocused || isHovered;
			const nameSpan = labelHalo?.nextElementSibling as HTMLElement | null;
			const overlaps =
				!forceShow &&
				accepted.some(({ x, y }) => Math.abs(screenX - x) < LW && Math.abs(screenY - y) < LH);
			if (!overlaps) {
				accepted.push({ x: screenX, y: screenY });
				restore(labelHalo, nameSpan, isHovered);
			} else {
				dim(labelHalo, nameSpan);
			}
		}

		// Moons: FULL by distance first, CAPPED after (never block FULL ones)
		moonCandidates.sort((a, b) => {
			if (a.isCapped !== b.isCapped) return a.isCapped ? 1 : -1;
			return a.dist - b.dist;
		});
		for (const { body, label, labelHalo, isCapped, screenX, screenY } of moonCandidates) {
			const isFocused = body.data.id === this.focusedBody?.data.id;
			const isHovered = label.element.matches(':hover');
			const forceShow = isFocused || isHovered;
			const nameSpan = labelHalo?.nextElementSibling as HTMLElement | null;
			if (isCapped && !forceShow) {
				dim(labelHalo, nameSpan);
				continue;
			}
			const overlaps =
				!forceShow &&
				accepted.some(({ x, y }) => Math.abs(screenX - x) < LW && Math.abs(screenY - y) < LH);
			if (!overlaps) {
				accepted.push({ x: screenX, y: screenY });
				restore(labelHalo, nameSpan, isHovered);
			} else {
				dim(labelHalo, nameSpan);
			}
		}
	}

	// --- Interaction ---

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

	private handleFocus(body: PositionedBody): void {
		this.focusedBody = body;
		this.focusTarget.set(...body.position);
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
	}

	// --- Public API ---

	setFocusTarget(body: PositionedBody, camPos?: [number, number, number]): void {
		this.focusedBody = body;
		this.focusTarget.set(...body.position);
		this.ctx.setFocused(body);
		this.callbacks.onFocusChange(body);
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
	}

	dispose(): void {
		cancelAnimationFrame(this.rafId);
		this.renderer.domElement.removeEventListener('pointerdown', this.onPointerDown);
		this.controls.dispose();
		this.renderer.dispose();
	}
}
