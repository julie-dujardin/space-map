/**
 * One body's surface panoramas, seen from inside: a sphere textured with the
 * panorama on screen, arrows on the ground toward the neighbours on its
 * traverse, and the camera the reader turns. This is the whole of the three-
 * dimensional part; the host draws its own chrome over it and reads the
 * list, the neighbours and the view through the class.
 *
 * Frames are drawn on demand: after the view, the texture or the arrows
 * change, never on a timer.
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
import { versionedUrl } from '$lib/fetch/data-base';
import { fetchObjectDetail, type PanoramaEntry } from '$lib/fetch/objects/object-data';
import { meanRadiusKm } from '$lib/fetch/objects/physical';
import { ControlHost, type Control, type ControlPosition } from '$lib/scene/controls';
import { findPanorama, initialHeadingDeg, neighboursOf, type Neighbours } from './traverse';

export type ArrowKey = 'previous' | 'next';

/** Where an arrow sits on screen, for a label the host hangs beside it. */
export interface ScreenAnchor {
	x: number;
	y: number;
	/** In front of the camera and inside the frame. */
	visible: boolean;
}

export interface PanoramaViewState {
	/** Compass heading, degrees clockwise from north. */
	heading: number;
	/** Degrees above the horizon. */
	pitch: number;
	/** Vertical field of view, degrees. */
	fov: number;
}

/** How far the reader may look and zoom. Headings run clockwise from the
 *  first to the second, so `[300, 60]` is the arc across north; a pair of
 *  equal values locks that axis. Each pair sits inside the view's own range. */
export interface PanoramaViewLimits {
	heading?: [from: number, to: number];
	pitch?: [min: number, max: number];
	fov?: [min: number, max: number];
}

export interface PanoramaViewOptions {
	/** Body whose panoramas to show, by export id — `"naif-499"` for Mars. */
	body: string;
	/** The panorama to open first: its id, or its `time,lat,lon` key. The
	 *  body's first when left out. */
	at?: string;
	/** Where to look first. Without them the view faces the middle of a
	 *  partial sweep, else north. */
	heading?: number;
	pitch?: number;
	fov?: number;
	/** Whether the reader may turn the view: drag, pinch, wheel and the arrow
	 *  keys. True unless said otherwise. */
	interactive?: boolean;
	/** Bounds on the view; none unless said otherwise. */
	limits?: PanoramaViewLimits;
	/** Draw the arrows to the previous and next panorama. True unless said
	 *  otherwise. */
	arrows?: boolean;
	/** Whether pressing an arrow opens the panorama it points at. True unless
	 *  said otherwise; a host that keeps the panorama in its own URL turns it
	 *  off and opens the target itself on `step`. */
	followArrows?: boolean;
}

export interface PanoramaViewEvents {
	/** The body's list is in; the first panorama is being fetched. */
	ready: () => void;
	/** This panorama is on screen. */
	load: (entry: PanoramaEntry) => void;
	error: (error: Error) => void;
	viewchange: (view: PanoramaViewState) => void;
	/** An arrow was pressed. */
	step: (target: { key: ArrowKey; entry: PanoramaEntry }) => void;
	/** Where the arrows landed on screen, after each frame. */
	arrows: (anchors: Partial<Record<ArrowKey, ScreenAnchor>>) => void;
}

const DEG = Math.PI / 180;
const MIN_FOV = 30;
const MAX_FOV = 110;
const MAX_PITCH = 85;
const DEFAULT_FOV = 75;
/** Arrows lie this far below the horizon, at this distance: near enough to
 *  parallax against the sphere as the view turns, like a step to take. */
const ARROW_PITCH_DEG = -22;
const ARROW_DISTANCE = 9;
const CLICK_SLOP_PX = 6;
const ANGLE_STEP_DEG = 10;
const ANGLE_SAMPLE_STEP_DEG = 1;
/** A neighbour closer than this stands on the same spot; there is no
 *  direction to point an arrow in. */
const MIN_ARROW_DISTANCE_M = 1;

function wrapHeading(deg: number): number {
	return ((deg % 360) + 360) % 360;
}

/** @internal The heading itself when it lies on the clockwise arc from `from` to `to`,
 *  else the arc's nearer end. */
export function clampHeading(deg: number, [from, to]: [number, number]): number {
	const span = wrapHeading(to - from);
	const offset = wrapHeading(deg - from);
	if (offset <= span) return wrapHeading(deg);
	return offset - span < 360 - offset ? wrapHeading(to) : wrapHeading(from);
}

function clamp(value: number, min: number, max: number): number {
	return Math.max(min, Math.min(max, value));
}

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

export class PanoramaView {
	private readonly bodyId: string;
	private readonly openAt: string | undefined;
	/** The host's opening direction, spent on the first panorama. */
	private openingView: Pick<PanoramaViewOptions, 'heading' | 'pitch'> | null;
	private readonly interactive: boolean;
	private readonly followArrows: boolean;
	private limits: PanoramaViewLimits = {};

	/** @internal The credit line, which the archives' terms keep on screen;
	 *  set by the host that adds it. */
	attribution: Control<PanoramaView> | null = null;

	private container: HTMLElement | null = null;
	private readonly root = document.createElement('div');
	private renderer: WebGLRenderer | null = null;
	private controls: ControlHost<PanoramaView> | null = null;
	private resizeObserver: ResizeObserver | null = null;
	private readonly scene = new Scene();
	private readonly camera = new PerspectiveCamera(DEFAULT_FOV, 1, 0.1, 1000);
	private readonly sphere: Mesh<SphereGeometry, MeshBasicMaterial>;
	/** The heading and elevation grid, drawn over the canvas in 2D so its
	 *  lines and labels keep one weight at every zoom. */
	private readonly angleCanvas = document.createElement('canvas');
	private readonly angleContext = this.angleCanvas.getContext('2d')!;
	private angleGridVisible = false;
	private readonly arrows = new Group();
	private readonly arrowGeometry = new ShapeGeometry(arrowShape());
	private readonly raycaster = new Raycaster();
	private readonly loader = new TextureLoader();
	private texture: Texture | null = null;
	private loadToken = 0;
	private frame = 0;
	private disposed = false;

	private entries: PanoramaEntry[] = [];
	private radiusKm = 0;
	private current: PanoramaEntry | null = null;
	private neighbours: Neighbours | null = null;

	private view: PanoramaViewState;
	private readonly pointers = new Map<number, { x: number; y: number }>();
	private pinchDistance = 0;
	private dragStart: { x: number; y: number } | null = null;
	private hovered: ArrowKey | null = null;
	private readonly lookAt = new Vector3();
	private readonly ndc = new Vector3();
	private readonly gridPoint = new Vector3();
	private readonly viewDirection = new Vector3();

	private readonly listeners: { [K in keyof PanoramaViewEvents]: Set<PanoramaViewEvents[K]> } = {
		ready: new Set(),
		load: new Set(),
		error: new Set(),
		viewchange: new Set(),
		step: new Set(),
		arrows: new Set()
	};

	constructor(options: PanoramaViewOptions) {
		this.bodyId = options.body;
		this.openAt = options.at;
		this.interactive = options.interactive ?? true;
		this.arrows.visible = options.arrows ?? true;
		this.followArrows = options.followArrows ?? true;
		this.openingView =
			options.heading !== undefined || options.pitch !== undefined
				? { heading: options.heading, pitch: options.pitch }
				: null;
		this.view = {
			heading: options.heading ?? 0,
			pitch: options.pitch ?? 0,
			fov: options.fov ?? DEFAULT_FOV
		};
		if (options.limits) this.setLimits(options.limits);

		this.root.className = 'sm-panorama';
		this.root.style.cssText = 'position:relative;width:100%;height:100%;overflow:hidden';
		this.scene.background = new Color('#0b0d12');
		// Mirrored geometry, not a mirrored mesh: the front faces must point in.
		this.sphere = new Mesh(
			new SphereGeometry(500, 96, 48).scale(-1, 1, 1),
			new MeshBasicMaterial({ transparent: true, visible: false, depthWrite: false })
		);
		this.sphere.renderOrder = -2;
		this.scene.add(this.sphere, this.arrows);
	}

	// -- lifecycle ------------------------------------------------------------

	/** Put the view's own box inside `container`. */
	mount(container: HTMLElement): void {
		this.container = container;
		container.append(this.root);
		this.renderer = new WebGLRenderer({ antialias: true });
		this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		const el = this.renderer.domElement;
		el.style.cssText = 'display:block;width:100%;height:100%;touch-action:none';
		el.tabIndex = 0;
		this.root.append(el);
		this.angleCanvas.style.cssText =
			'position:absolute;inset:0;display:block;width:100%;height:100%;pointer-events:none';
		this.angleCanvas.setAttribute('aria-hidden', 'true');
		this.angleCanvas.hidden = true;
		this.root.append(this.angleCanvas);
		this.controls = new ControlHost(this, this.root);
		this.resizeObserver = new ResizeObserver(() => this.resize());
		this.resizeObserver.observe(this.root);
		this.resize();
		if (this.interactive) {
			el.addEventListener('pointerdown', this.onPointerDown);
			el.addEventListener('pointermove', this.onPointerMove);
			el.addEventListener('pointerup', this.onPointerUp);
			el.addEventListener('pointercancel', this.onPointerCancel);
			el.addEventListener('wheel', this.onWheel, { passive: false });
			el.addEventListener('keydown', this.onKeyDown);
		} else {
			el.addEventListener('pointermove', this.onPointerMove);
			el.addEventListener('pointerup', this.onPointerUp);
		}
	}

	/** Fetch the body's list and open the panorama asked for, or its first. */
	async load(): Promise<void> {
		const detail = await fetchObjectDetail(this.bodyId, false);
		if (this.disposed) return;
		this.entries = detail.global?.panoramas ?? [];
		this.radiusKm = meanRadiusKm(detail.global) ?? 0;
		this.emit('ready');
		const first = this.openAt ? this.byKey(this.openAt) : (this.entries[0] ?? null);
		if (!first) {
			const error = new Error(
				this.openAt
					? `spacemap: no panorama ${this.openAt} on ${this.bodyId}`
					: `spacemap: no panoramas on ${this.bodyId}`
			);
			this.emit('error', error);
			throw error;
		}
		await this.open(first);
	}

	addControl(control: Control<PanoramaView>, position?: ControlPosition): this {
		this.controls?.add(control, position);
		return this;
	}

	removeControl(control: Control<PanoramaView>): this {
		if (control === this.attribution)
			throw new Error('spacemap: the attribution control cannot be removed');
		this.controls?.remove(control);
		return this;
	}

	/** Take the view down and let go of everything it holds. */
	remove(): void {
		this.disposed = true;
		this.loadToken++;
		cancelAnimationFrame(this.frame);
		this.frame = 0;
		this.controls?.clear();
		this.resizeObserver?.disconnect();
		const el = this.renderer?.domElement;
		if (el) {
			el.removeEventListener('pointerdown', this.onPointerDown);
			el.removeEventListener('pointermove', this.onPointerMove);
			el.removeEventListener('pointerup', this.onPointerUp);
			el.removeEventListener('pointercancel', this.onPointerCancel);
			el.removeEventListener('wheel', this.onWheel);
			el.removeEventListener('keydown', this.onKeyDown);
		}
		this.setArrowTargets([]);
		this.texture?.dispose();
		this.sphere.geometry.dispose();
		this.sphere.material.dispose();
		this.arrowGeometry.dispose();
		this.renderer?.dispose();
		this.renderer = null;
		this.root.remove();
		this.container = null;
	}

	// -- the panoramas --------------------------------------------------------

	/** Every panorama of the body, mission by mission in time order. */
	getPanoramas(): readonly PanoramaEntry[] {
		return this.entries;
	}

	getCurrent(): PanoramaEntry | null {
		return this.current;
	}

	/** The panoramas before and after the current one on its traverse. */
	getNeighbours(): Neighbours | null {
		return this.neighbours;
	}

	/** Show a panorama: an entry from the list, its id, or its `time,lat,lon`
	 *  key. Resolves once it is on screen; a newer call supersedes one still
	 *  in flight. */
	async open(target: PanoramaEntry | string): Promise<void> {
		const entry = typeof target === 'string' ? this.byKey(target) : target;
		if (!entry) {
			const error = new Error(`spacemap: no panorama ${String(target)} on ${this.bodyId}`);
			this.emit('error', error);
			throw error;
		}
		this.current = entry;
		this.neighbours = this.radiusKm ? neighboursOf(this.entries, entry, this.radiusKm) : null;
		this.setView({
			heading: this.openingView?.heading ?? initialHeadingDeg(entry),
			pitch: this.openingView?.pitch ?? 0
		});
		this.openingView = null;
		this.setArrowTargets(
			this.neighbours
				? (['previous', 'next'] as const)
						.map((key) => ({ key, n: this.neighbours?.[key] ?? null }))
						.filter((a) => a.n && a.n.distanceM >= MIN_ARROW_DISTANCE_M)
						.map((a) => ({ key: a.key, bearingDeg: a.n!.bearingDeg }))
				: []
		);
		await this.loadTexture(
			versionedUrl(`/v1/panoramas/${entry.id}.webp`, 'panoramas'),
			entry.north_offset_deg
		);
		if (this.current === entry) this.emit('load', entry);
	}

	/** Open the previous or next panorama on the traverse, when there is one. */
	async step(key: ArrowKey): Promise<void> {
		const n = this.neighbours?.[key];
		if (n) await this.open(n.entry);
	}

	private byKey(key: string): PanoramaEntry | null {
		return this.entries.find((e) => e.id === key) ?? findPanorama(this.entries, key);
	}

	// -- the view -------------------------------------------------------------

	getView(): PanoramaViewState {
		return { ...this.view };
	}

	/** Turn or zoom the view, within its limits. */
	setView(view: Partial<PanoramaViewState>): void {
		const heading = view.heading ?? this.view.heading;
		const pitch = view.pitch ?? this.view.pitch;
		const fov = view.fov ?? this.view.fov;
		const { limits } = this;
		this.view = {
			heading: limits.heading ? clampHeading(heading, limits.heading) : wrapHeading(heading),
			pitch: clamp(pitch, limits.pitch?.[0] ?? -MAX_PITCH, limits.pitch?.[1] ?? MAX_PITCH),
			fov: clamp(fov, limits.fov?.[0] ?? MIN_FOV, limits.fov?.[1] ?? MAX_FOV)
		};
		this.invalidate();
		this.emit('viewchange', this.getView());
	}

	getLimits(): PanoramaViewLimits {
		return structuredClone(this.limits);
	}

	/** Bound the view; the current one moves inside the bounds at once. An
	 *  empty object frees it. */
	setLimits(limits: PanoramaViewLimits): void {
		const within = (pair: [number, number] | undefined, min: number, max: number) =>
			pair && ([clamp(pair[0], min, max), clamp(pair[1], min, max)] as [number, number]);
		this.limits = {
			heading: limits.heading && [wrapHeading(limits.heading[0]), wrapHeading(limits.heading[1])],
			pitch: within(limits.pitch, -MAX_PITCH, MAX_PITCH),
			fov: within(limits.fov, MIN_FOV, MAX_FOV)
		};
		this.setView({});
	}

	// -- events ---------------------------------------------------------------

	on<K extends keyof PanoramaViewEvents>(event: K, listener: PanoramaViewEvents[K]): () => void {
		this.listeners[event].add(listener);
		return () => this.off(event, listener);
	}

	once<K extends keyof PanoramaViewEvents>(event: K, listener: PanoramaViewEvents[K]): () => void {
		const wrapped = ((...args: Parameters<PanoramaViewEvents[K]>) => {
			off();
			(listener as (...a: Parameters<PanoramaViewEvents[K]>) => void)(...args);
		}) as PanoramaViewEvents[K];
		const off = this.on(event, wrapped);
		return off;
	}

	off<K extends keyof PanoramaViewEvents>(event: K, listener: PanoramaViewEvents[K]): void {
		this.listeners[event].delete(listener);
	}

	private emit<K extends keyof PanoramaViewEvents>(
		event: K,
		...args: Parameters<PanoramaViewEvents[K]>
	): void {
		for (const listener of this.listeners[event]) {
			(listener as (...a: Parameters<PanoramaViewEvents[K]>) => void)(...args);
		}
	}

	// -- drawing --------------------------------------------------------------

	private loadTexture(url: string, northOffsetDeg: number): Promise<void> {
		const token = ++this.loadToken;
		return new Promise((resolve, reject) => {
			this.loader.load(
				url,
				(texture) => {
					if (token !== this.loadToken) {
						texture.dispose();
						resolve();
						return;
					}
					texture.colorSpace = SRGBColorSpace;
					if (this.renderer) texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
					this.texture?.dispose();
					this.texture = texture;
					this.sphere.material.map = texture;
					this.sphere.material.visible = true;
					this.sphere.material.needsUpdate = true;
					// A quarter turn puts the left edge at north; the offset then brings
					// the column that is really north there.
					this.sphere.rotation.y = Math.PI / 2 + northOffsetDeg * DEG;
					this.invalidate();
					resolve();
				},
				undefined,
				() => {
					if (token !== this.loadToken) return resolve();
					const error = new Error(`spacemap: panorama failed to load: ${url}`);
					this.emit('error', error);
					reject(error);
				}
			);
		});
	}

	private setArrowTargets(targets: { key: ArrowKey; bearingDeg: number }[]): void {
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

	private invalidate(): void {
		if (this.disposed || this.frame || !this.renderer) return;
		this.frame = requestAnimationFrame(() => {
			this.frame = 0;
			this.render();
		});
	}

	/** Lay a grid of headings and elevations over the view, every ten degrees. */
	setAngleGridVisible(visible: boolean): void {
		if (visible === this.angleGridVisible) return;
		this.angleGridVisible = visible;
		this.angleCanvas.hidden = !visible;
		this.invalidate();
	}

	/** Show or hide the arrows to the neighbouring panoramas. */
	setArrowsVisible(visible: boolean): void {
		if (visible === this.arrows.visible) return;
		this.arrows.visible = visible;
		if (!visible) {
			this.hovered = null;
			if (this.renderer) this.renderer.domElement.style.cursor = '';
		}
		this.invalidate();
	}

	private resize(): void {
		const { clientWidth: w, clientHeight: h } = this.root;
		if (!w || !h || !this.renderer) return;
		this.renderer.setSize(w, h, false);
		const pixelRatio = Math.min(window.devicePixelRatio, 2);
		this.angleCanvas.width = Math.round(w * pixelRatio);
		this.angleCanvas.height = Math.round(h * pixelRatio);
		this.angleContext.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
		this.camera.aspect = w / h;
		this.camera.updateProjectionMatrix();
		this.invalidate();
	}

	private render(): void {
		if (!this.renderer) return;
		this.camera.fov = this.view.fov;
		this.camera.updateProjectionMatrix();
		this.camera.lookAt(direction(this.view.heading, this.view.pitch, this.lookAt));
		this.renderer.render(this.scene, this.camera);
		const { clientWidth: w, clientHeight: h } = this.root;
		this.drawAngleGrid(w, h);

		if (this.listeners.arrows.size === 0) return;
		const anchors: Partial<Record<ArrowKey, ScreenAnchor>> = {};
		for (const group of this.arrows.visible ? this.arrows.children : []) {
			this.ndc.copy(group.position).project(this.camera);
			anchors[group.name as ArrowKey] = {
				x: ((this.ndc.x + 1) / 2) * w,
				y: ((1 - this.ndc.y) / 2) * h,
				visible: this.ndc.z < 1 && Math.abs(this.ndc.x) < 0.98 && Math.abs(this.ndc.y) < 0.98
			};
		}
		this.emit('arrows', anchors);
	}

	/** Drawn after projection so grid weight and type stay constant across the view. */
	private drawAngleGrid(w: number, h: number): void {
		const ctx = this.angleContext;
		ctx.clearRect(0, 0, w, h);
		if (!this.angleGridVisible) return;
		this.camera.getWorldDirection(this.viewDirection);

		ctx.strokeStyle = 'rgba(255, 255, 255, 0.24)';
		ctx.lineWidth = 1;
		ctx.beginPath();
		for (let heading = 0; heading < 360; heading += ANGLE_STEP_DEG) {
			this.traceAngleLine(ctx, w, h, heading, true);
		}
		for (let elevation = -80; elevation <= 80; elevation += ANGLE_STEP_DEG) {
			this.traceAngleLine(ctx, w, h, elevation, false);
		}
		ctx.stroke();

		ctx.font = '12px system-ui, sans-serif';
		ctx.lineWidth = 3;
		ctx.strokeStyle = 'rgba(0, 0, 0, 0.7)';
		ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
		ctx.textAlign = 'center';
		ctx.textBaseline = 'bottom';
		for (let heading = 0; heading < 360; heading += ANGLE_STEP_DEG) {
			if (!this.projectAngle(heading, 0, w, h, true)) continue;
			const label = `${heading}°`;
			ctx.strokeText(label, this.gridPoint.x, this.gridPoint.y - 3);
			ctx.fillText(label, this.gridPoint.x, this.gridPoint.y - 3);
		}

		ctx.textAlign = 'left';
		ctx.textBaseline = 'middle';
		for (const heading of [0, 90, 180, 270]) {
			for (let elevation = -80; elevation <= 80; elevation += ANGLE_STEP_DEG) {
				if (elevation === 0 || !this.projectAngle(heading, elevation, w, h, true)) continue;
				const label = `${elevation > 0 ? '+' : ''}${elevation}°`;
				ctx.strokeText(label, this.gridPoint.x + 4, this.gridPoint.y);
				ctx.fillText(label, this.gridPoint.x + 4, this.gridPoint.y);
			}
		}
	}

	private traceAngleLine(
		ctx: CanvasRenderingContext2D,
		w: number,
		h: number,
		fixedAngle: number,
		meridian: boolean
	): void {
		let drawing = false;
		let previousX = 0;
		let previousY = 0;
		const maxJump = Math.max(w, h) * 2;
		const from = meridian ? -90 : 0;
		const to = meridian ? 90 : 360;
		for (let angle = from; angle <= to; angle += ANGLE_SAMPLE_STEP_DEG) {
			const heading = meridian ? fixedAngle : angle;
			const elevation = meridian ? angle : fixedAngle;
			if (!this.projectAngle(heading, elevation, w, h)) {
				drawing = false;
				continue;
			}
			const { x, y } = this.gridPoint;
			if (!drawing || Math.hypot(x - previousX, y - previousY) > maxJump) ctx.moveTo(x, y);
			else ctx.lineTo(x, y);
			drawing = true;
			previousX = x;
			previousY = y;
		}
	}

	private projectAngle(
		heading: number,
		elevation: number,
		w: number,
		h: number,
		insideViewport = false
	): boolean {
		direction(heading, elevation, this.gridPoint);
		if (this.gridPoint.dot(this.viewDirection) <= 0.001) return false;
		this.gridPoint.project(this.camera);
		if (!Number.isFinite(this.gridPoint.x) || !Number.isFinite(this.gridPoint.y)) return false;
		if (
			insideViewport &&
			(Math.abs(this.gridPoint.x) >= 0.98 || Math.abs(this.gridPoint.y) >= 0.98)
		)
			return false;
		if (Math.abs(this.gridPoint.x) > 4 || Math.abs(this.gridPoint.y) > 4) return false;
		this.gridPoint.x = ((this.gridPoint.x + 1) / 2) * w;
		this.gridPoint.y = ((1 - this.gridPoint.y) / 2) * h;
		return true;
	}

	// -- input ----------------------------------------------------------------

	/** Degrees of view per pixel dragged, so a drag follows the finger at any zoom. */
	private degreesPerPixel(): number {
		return this.view.fov / Math.max(1, this.root.clientHeight);
	}

	private arrowAt(x: number, y: number): ArrowKey | null {
		if (!this.renderer || !this.arrows.visible || this.arrows.children.length === 0) return null;
		const rect = this.renderer.domElement.getBoundingClientRect();
		const point = new Vector2(
			((x - rect.left) / rect.width) * 2 - 1,
			-((y - rect.top) / rect.height) * 2 + 1
		);
		this.raycaster.setFromCamera(point, this.camera);
		const hit = this.raycaster.intersectObjects(this.arrows.children, true)[0];
		return hit ? (hit.object.parent!.name as ArrowKey) : null;
	}

	private pressArrow(key: ArrowKey): void {
		const n = this.neighbours?.[key];
		if (!n) return;
		this.emit('step', { key, entry: n.entry });
		// A failed load has already gone out as an `error` event.
		if (this.followArrows) this.open(n.entry).catch(() => {});
	}

	private readonly onPointerDown = (e: PointerEvent): void => {
		try {
			this.renderer?.domElement.setPointerCapture(e.pointerId);
		} catch {
			// A synthetic pointer has no capture to take.
		}
		this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
		this.dragStart = this.pointers.size === 1 ? { x: e.clientX, y: e.clientY } : null;
		if (this.pointers.size === 2) this.pinchDistance = this.pinchSpan();
	};

	private readonly onPointerMove = (e: PointerEvent): void => {
		const prev = this.pointers.get(e.pointerId);
		if (!prev) {
			const over = this.arrowAt(e.clientX, e.clientY);
			if (over !== this.hovered && this.renderer) {
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
			this.setView({ heading: this.view.heading - dx * k, pitch: this.view.pitch + dy * k });
		} else if (this.pointers.size === 2) {
			const span = this.pinchSpan();
			if (this.pinchDistance > 0) this.zoom(this.pinchDistance / span);
			this.pinchDistance = span;
		}
	};

	/** A press is a click when one pointer went down and barely moved. A
	 *  non-interactive view takes no pointer down, so every release is one. */
	private readonly onPointerUp = (e: PointerEvent): void => {
		this.pointers.delete(e.pointerId);
		const start = this.dragStart;
		this.dragStart = null;
		if (this.pointers.size > 0) return;
		const isClick = this.interactive
			? start !== null && Math.hypot(e.clientX - start.x, e.clientY - start.y) < CLICK_SLOP_PX
			: true;
		if (!isClick) return;
		const key = this.arrowAt(e.clientX, e.clientY);
		if (key) this.pressArrow(key);
	};

	private readonly onPointerCancel = (e: PointerEvent): void => {
		this.pointers.delete(e.pointerId);
		this.dragStart = null;
	};

	private pinchSpan(): number {
		const [a, b] = [...this.pointers.values()];
		return Math.hypot(a.x - b.x, a.y - b.y);
	}

	private zoom(factor: number): void {
		this.setView({ fov: this.view.fov * factor });
	}

	private readonly onWheel = (e: WheelEvent): void => {
		e.preventDefault();
		this.zoom(Math.exp(e.deltaY * 0.0015));
	};

	private readonly onKeyDown = (e: KeyboardEvent): void => {
		const step = this.view.fov / 10;
		const { heading, pitch } = this.view;
		const moves: Record<string, () => void> = {
			ArrowLeft: () => this.setView({ heading: heading - step }),
			ArrowRight: () => this.setView({ heading: heading + step }),
			ArrowUp: () => this.setView({ pitch: pitch + step }),
			ArrowDown: () => this.setView({ pitch: pitch - step }),
			'+': () => this.zoom(0.8),
			'-': () => this.zoom(1.25)
		};
		const move = moves[e.key];
		if (!move) return;
		e.preventDefault();
		move();
	};
}
