/**
 * The inside of a sphere textured with one panorama, plus the arrows to its
 * neighbours on the traverse. Renders on demand: a frame is drawn only after
 * the view, the texture or the arrows change.
 */

import {
	Color,
	DoubleSide,
	Group,
	Mesh,
	MeshBasicMaterial,
	PerspectiveCamera,
	Raycaster,
	Scene,
	Shape,
	ShapeGeometry,
	SphereGeometry,
	SRGBColorSpace,
	Texture,
	TextureLoader,
	Vector2,
	Vector3,
	WebGLRenderer
} from 'three';

export type ArrowKey = 'previous' | 'next';

export interface ArrowTarget {
	key: ArrowKey;
	bearingDeg: number;
}

export interface ScreenAnchor {
	x: number;
	y: number;
	visible: boolean;
}

const DEG = Math.PI / 180;
const MIN_FOV = 30;
const MAX_FOV = 110;
/** Arrows lie this far below the horizon, at this distance: near enough to
 *  parallax against the sphere as the view turns, like a step to take. */
const ARROW_PITCH_DEG = -22;
const ARROW_DISTANCE = 9;
const CLICK_SLOP_PX = 6;

/** Unit vector for a compass heading and pitch: north is -Z, east +X, up +Y. */
function direction(headingDeg: number, pitchDeg: number, out = new Vector3()): Vector3 {
	const h = headingDeg * DEG;
	const p = pitchDeg * DEG;
	return out.set(Math.sin(h) * Math.cos(p), Math.sin(p), -Math.cos(h) * Math.cos(p));
}

function arrowShape(): Shape {
	const s = new Shape();
	s.moveTo(0, 1);
	s.lineTo(0.85, 0.05);
	s.lineTo(0.38, 0.05);
	s.lineTo(0.38, -0.9);
	s.lineTo(-0.38, -0.9);
	s.lineTo(-0.38, 0.05);
	s.lineTo(-0.85, 0.05);
	s.closePath();
	return s;
}

export class PanoramaScene {
	/** Compass heading of the view, degrees clockwise from north. */
	heading = $state(0);
	pitch = $state(0);
	fov = $state(75);
	anchors = $state<Partial<Record<ArrowKey, ScreenAnchor>>>({});

	private readonly renderer: WebGLRenderer;
	private readonly scene = new Scene();
	private readonly camera: PerspectiveCamera;
	private readonly sphere: Mesh<SphereGeometry, MeshBasicMaterial>;
	private readonly arrows = new Group();
	private readonly arrowGeometry = new ShapeGeometry(arrowShape());
	private readonly raycaster = new Raycaster();
	private readonly resizeObserver: ResizeObserver;
	private readonly loader = new TextureLoader();
	private texture: Texture | null = null;
	private loadToken = 0;
	private frame = 0;
	private readonly pointers = new Map<number, { x: number; y: number }>();
	private pinchDistance = 0;
	private dragStart: { x: number; y: number } | null = null;
	private hovered: ArrowKey | null = null;
	private readonly lookAt = new Vector3();
	private readonly ndc = new Vector3();

	constructor(
		private readonly container: HTMLElement,
		private readonly onArrowClick: (key: ArrowKey) => void
	) {
		this.renderer = new WebGLRenderer({ antialias: true });
		this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		this.renderer.domElement.classList.add('block', 'h-full', 'w-full', 'touch-none');
		this.renderer.domElement.tabIndex = 0;
		container.appendChild(this.renderer.domElement);

		this.scene.background = new Color('#0b0d12');
		this.camera = new PerspectiveCamera(this.fov, 1, 0.1, 1000);

		// Inside-out sphere: the geometry itself is mirrored on X so the faces
		// turn inward and the texture reads correctly from within. Mirroring the
		// mesh instead would keep the outside as the front face and cull it all.
		this.sphere = new Mesh(
			new SphereGeometry(500, 96, 48).scale(-1, 1, 1),
			new MeshBasicMaterial({ transparent: true, visible: false, depthWrite: false })
		);
		// Centred on the camera, the sphere sorts as the nearest transparent
		// object and would paint over the arrows; pin it underneath.
		this.sphere.renderOrder = -1;
		this.scene.add(this.sphere, this.arrows);

		this.resizeObserver = new ResizeObserver(() => this.resize());
		this.resizeObserver.observe(container);
		this.resize();

		const el = this.renderer.domElement;
		el.addEventListener('pointerdown', this.onPointerDown);
		el.addEventListener('pointermove', this.onPointerMove);
		el.addEventListener('pointerup', this.onPointerUp);
		el.addEventListener('pointercancel', this.onPointerUp);
		el.addEventListener('wheel', this.onWheel, { passive: false });
		el.addEventListener('keydown', this.onKeyDown);
	}

	/** Swap in a panorama. Resolves once it is on screen; rejects on a failed
	 *  fetch. A newer call supersedes an older one still in flight. */
	load(url: string, northOffsetDeg: number): Promise<void> {
		const token = ++this.loadToken;
		return new Promise((resolve, reject) => {
			this.loader.load(
				url,
				(texture) => {
					if (token !== this.loadToken) {
						texture.dispose();
						return;
					}
					texture.colorSpace = SRGBColorSpace;
					texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
					this.texture?.dispose();
					this.texture = texture;
					this.sphere.material.map = texture;
					this.sphere.material.visible = true;
					this.sphere.material.needsUpdate = true;
					// The left texture edge sits at +X after the mirror; a quarter
					// turn brings it to -Z (north). The offset then turns the column
					// that is really north into that place.
					this.sphere.rotation.y = Math.PI / 2 + northOffsetDeg * DEG;
					this.invalidate();
					resolve();
				},
				undefined,
				() => {
					if (token === this.loadToken) reject(new Error(`Panorama failed to load: ${url}`));
				}
			);
		});
	}

	setArrows(targets: ArrowTarget[]): void {
		for (const child of [...this.arrows.children]) {
			this.arrows.remove(child);
			child.traverse((o) => {
				if (o instanceof Mesh) (o.material as MeshBasicMaterial).dispose();
			});
		}
		for (const target of targets) {
			const group = new Group();
			group.name = target.key;
			const halo = new Mesh(
				this.arrowGeometry,
				new MeshBasicMaterial({
					color: '#000000',
					transparent: true,
					opacity: 0.45,
					side: DoubleSide,
					depthWrite: false
				})
			);
			halo.scale.setScalar(1.3);
			const face = new Mesh(
				this.arrowGeometry,
				new MeshBasicMaterial({
					color: '#ffffff',
					transparent: true,
					opacity: 0.85,
					side: DoubleSide,
					depthWrite: false
				})
			);
			face.position.y = 0.02;
			// Flat on the ground with its tip toward north, then turned to bear.
			for (const mesh of [halo, face]) mesh.rotation.x = -Math.PI / 2;
			group.add(halo, face);
			group.position
				.copy(direction(target.bearingDeg, ARROW_PITCH_DEG))
				.multiplyScalar(ARROW_DISTANCE);
			group.rotation.y = -target.bearingDeg * DEG;
			this.arrows.add(group);
		}
		this.invalidate();
	}

	setView(headingDeg: number, pitchDeg = 0): void {
		this.heading = ((headingDeg % 360) + 360) % 360;
		this.pitch = Math.max(-85, Math.min(85, pitchDeg));
		this.invalidate();
	}

	dispose(): void {
		cancelAnimationFrame(this.frame);
		this.resizeObserver.disconnect();
		const el = this.renderer.domElement;
		el.removeEventListener('pointerdown', this.onPointerDown);
		el.removeEventListener('pointermove', this.onPointerMove);
		el.removeEventListener('pointerup', this.onPointerUp);
		el.removeEventListener('pointercancel', this.onPointerUp);
		el.removeEventListener('wheel', this.onWheel);
		el.removeEventListener('keydown', this.onKeyDown);
		this.loadToken++;
		this.setArrows([]);
		this.texture?.dispose();
		this.sphere.geometry.dispose();
		this.sphere.material.dispose();
		this.arrowGeometry.dispose();
		this.renderer.dispose();
		el.remove();
	}

	private invalidate(): void {
		if (this.frame) return;
		this.frame = requestAnimationFrame(() => {
			this.frame = 0;
			this.render();
		});
	}

	private resize(): void {
		const { clientWidth: w, clientHeight: h } = this.container;
		if (!w || !h) return;
		this.renderer.setSize(w, h, false);
		this.camera.aspect = w / h;
		this.camera.updateProjectionMatrix();
		this.invalidate();
	}

	private render(): void {
		this.camera.fov = this.fov;
		this.camera.updateProjectionMatrix();
		this.camera.lookAt(direction(this.heading, this.pitch, this.lookAt));
		this.renderer.render(this.scene, this.camera);

		const anchors: Partial<Record<ArrowKey, ScreenAnchor>> = {};
		const { clientWidth: w, clientHeight: h } = this.container;
		for (const group of this.arrows.children) {
			this.ndc.copy(group.position).project(this.camera);
			anchors[group.name as ArrowKey] = {
				x: ((this.ndc.x + 1) / 2) * w,
				y: ((1 - this.ndc.y) / 2) * h,
				visible: this.ndc.z < 1 && Math.abs(this.ndc.x) < 0.98 && Math.abs(this.ndc.y) < 0.98
			};
		}
		this.anchors = anchors;
	}

	/** Degrees of view per pixel dragged, so a drag follows the finger at any zoom. */
	private degreesPerPixel(): number {
		return this.fov / Math.max(1, this.container.clientHeight);
	}

	private arrowAt(x: number, y: number): ArrowKey | null {
		const rect = this.renderer.domElement.getBoundingClientRect();
		const point = new Vector2(
			((x - rect.left) / rect.width) * 2 - 1,
			-((y - rect.top) / rect.height) * 2 + 1
		);
		this.raycaster.setFromCamera(point, this.camera);
		const hit = this.raycaster.intersectObjects(this.arrows.children, true)[0];
		return hit ? (hit.object.parent!.name as ArrowKey) : null;
	}

	private readonly onPointerDown = (e: PointerEvent): void => {
		try {
			this.renderer.domElement.setPointerCapture(e.pointerId);
		} catch {
			// A synthetic pointer has no capture to take.
		}
		this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
		if (this.pointers.size === 1) this.dragStart = { x: e.clientX, y: e.clientY };
		else this.dragStart = null;
		if (this.pointers.size === 2) this.pinchDistance = this.pinchSpan();
	};

	private readonly onPointerMove = (e: PointerEvent): void => {
		const prev = this.pointers.get(e.pointerId);
		if (!prev) {
			const over = this.arrowAt(e.clientX, e.clientY);
			if (over !== this.hovered) {
				this.hovered = over;
				this.renderer.domElement.style.cursor = over ? 'pointer' : '';
			}
			return;
		}
		const dx = e.clientX - prev.x;
		const dy = e.clientY - prev.y;
		this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
		if (this.pointers.size === 1) {
			const k = this.degreesPerPixel();
			this.setView(this.heading - dx * k, this.pitch + dy * k);
		} else if (this.pointers.size === 2) {
			const span = this.pinchSpan();
			if (this.pinchDistance > 0) this.zoom(this.pinchDistance / span);
			this.pinchDistance = span;
		}
	};

	private readonly onPointerUp = (e: PointerEvent): void => {
		this.pointers.delete(e.pointerId);
		const start = this.dragStart;
		this.dragStart = null;
		if (
			start &&
			this.pointers.size === 0 &&
			Math.hypot(e.clientX - start.x, e.clientY - start.y) < CLICK_SLOP_PX
		) {
			const key = this.arrowAt(e.clientX, e.clientY);
			if (key) this.onArrowClick(key);
		}
	};

	private pinchSpan(): number {
		const [a, b] = [...this.pointers.values()];
		return Math.hypot(a.x - b.x, a.y - b.y);
	}

	private zoom(factor: number): void {
		this.fov = Math.max(MIN_FOV, Math.min(MAX_FOV, this.fov * factor));
		this.invalidate();
	}

	private readonly onWheel = (e: WheelEvent): void => {
		e.preventDefault();
		this.zoom(Math.exp(e.deltaY * 0.0015));
	};

	private readonly onKeyDown = (e: KeyboardEvent): void => {
		const step = this.fov / 10;
		const moves: Record<string, () => void> = {
			ArrowLeft: () => this.setView(this.heading - step, this.pitch),
			ArrowRight: () => this.setView(this.heading + step, this.pitch),
			ArrowUp: () => this.setView(this.heading, this.pitch + step),
			ArrowDown: () => this.setView(this.heading, this.pitch - step),
			'+': () => this.zoom(0.8),
			'-': () => this.zoom(1.25)
		};
		const move = moves[e.key];
		if (!move) return;
		e.preventDefault();
		move();
	};
}
