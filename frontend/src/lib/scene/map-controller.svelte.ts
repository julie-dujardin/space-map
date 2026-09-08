/**
 * One map: its data ({@link ContextManager}), clock, renderer and the DOM
 * they live in, behind a plain API and events. Knows nothing of routes or
 * the page around it — the app's `Scene.svelte` and the SDK both drive it.
 */

import { ContextManager } from './state/context-manager.svelte';
import { SimClock } from './state/clock.svelte';
import { SceneRenderer } from './renderer';
import { calibrationUi } from './perf/calibration-state.svelte';
import { scheduleAtmosphereCalibration } from './perf/atmosphere-calibration';
import { sceneSettings, setSceneSettings, type SceneSettings } from './settings.svelte';
import {
	DEFAULT_FOCUS_ID,
	DEFAULT_FRAMING_LAT,
	DEFAULT_FRAMING_LON,
	DEFAULT_ZOOM
} from './framing';
import type { Callbacks, CameraView, InitialView } from './types';
import type { Notice, NoticeTopic } from './notice';
import { MarkerExtension, type Marker, type MarkerOptions } from './extensions/marker';
import { loadProgress } from './state/load-progress.svelte';
import type { Vec3 } from './animation/math';
import type { OrbitPreview } from './objects/travel/orbit-preview';
import {
	effectiveRadiusKm,
	isSurfaceFeature,
	type FeatureAnchor,
	type PositionedBody
} from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import { dateToJD, jdToDate } from '$lib/time/jd';
import { host } from '$lib/host';
import type { LabelledPath, PathStep } from '$lib/travel/labelled-path';
import type { LabelledHazard } from '$lib/travel/hazards';
import './map.css';

export interface MapControllerOptions {
	/** Display settings for the page; defaults suit a bare embed. */
	settings?: SceneSettings;
	/** Simulation start, wall-clock time when omitted. `live` keeps the clock
	 *  on wall-clock time; defaults to true only when no date is given. */
	date?: Date;
	live?: boolean;
	/** The body to open on, and the camera around it. */
	view?: Partial<InitialView>;
}

export interface FocusChange {
	body: PositionedBody | undefined;
	/** The first settle after boot. */
	initial: boolean;
	/** The camera orbits a surface feature; `body` is its host. */
	feature: boolean;
}

export interface FeatureSelect {
	bodyId: string;
	featureId: number;
	lat: number;
	lon: number;
	diameterM: number;
}

/** The clock as the host sees it, sent whenever any of it changes. */
export interface ClockState {
	/** Simulation time, Julian date and as a `Date`. */
	jd: number;
	date: Date;
	playing: boolean;
	/** Simulated seconds per real second, and which way time runs. */
	timeScale: number;
	direction: 1 | -1;
	/** The clock tracks wall-clock time. */
	live: boolean;
}

export interface MapEvents {
	focuschange: (e: FocusChange) => void;
	/** The camera came to rest around the focused body. */
	camera: (view: CameraView) => void;
	/** A nomenclature label was clicked; carries what a fly-to needs. */
	featureselect: (e: FeatureSelect) => void;
	/** User-promoted bodies that can be cleared (the focused one excluded). */
	userpromoted: (count: number) => void;
	contextlost: () => void;
	contextrestored: () => void;
	/** The clock moved, or its play state, rate or direction changed. */
	clock: (e: ClockState) => void;
	/** Data loading started or finished, the one-off quality benchmark
	 *  included; `false` means the map is ready to look at. */
	loading: (loading: boolean) => void;
	/** Boot progress, 0 to 1, monotonic within one load. */
	progress: (fraction: number) => void;
	/** The data could not be loaded. The map stays mounted and empty. */
	error: (message: string) => void;
	/** The export was republished while this map was open: its data is now a
	 *  version behind, and reloading the page picks the new one up. */
	datastale: () => void;
	/** A condition worth telling the reader about; one live notice per topic. */
	notice: (notice: Notice) => void;
	/** That topic's condition cleared. */
	noticedismiss: (topic: NoticeTopic) => void;
	/** Once per drawn frame, with the bodies at that frame's positions and the
	 *  camera not yet moved. `dtMs` is 0 after a skipped frame. */
	frame: (e: { jd: number; dtMs: number }) => void;
}

/** Renderer state derived from settings. One sink per field, so a reactive
 *  settings object re-runs only the sink whose field changed: `applyRenderTier`
 *  re-applies point budgets unconditionally. */
const SETTING_SINKS: ReadonlyArray<(r: SceneRenderer, s: SceneSettings) => void> = [
	(r, s) => r.setReducedMotion(s.resolvedReducedMotion),
	(r, s) => r.setImmersive(s.viewMode === 'immersive'),
	(r, s) => r.setHaloDebugVisible(s.showHaloDebug),
	// A recalibration can move the render tier.
	(r, s) => {
		void s.atmosphereCalibration;
		r.applyRenderTier();
	}
];

/** Keyboard camera controls: arrows orbit, +/- zoom, Shift speeds up —
 *  OrbitControls' pointer gestures for keyboard-only users. */
const KEY_ROTATE_RAD = 0.05;
const KEY_ZOOM_FACTOR = 1.15;

/** Restore usually lands within a frame or two; the "stopped" panel waits this
 *  long so it does not flash. */
const CONTEXT_LOST_PANEL_DELAY_MS = 2000;
/** The main thread is re-uploading every VBO after a restore, so a live
 *  worker's pong can be slow; a false negative costs a full belt repack. */
const RESTORE_PING_TIMEOUT_MS = 4000;

export class MapController {
	/** @internal The map's data layer: the app drives it directly, a host
	 *  reaches it through {@link getBody}, {@link getChildren} and events. */
	readonly ctx = new ContextManager();
	readonly clock: SimClock;
	/** @internal */
	readonly initialView: InitialView;
	/** @internal Null until {@link mount} builds it, and again after
	 *  {@link unmount}; reactive so the app's debug overlays can wait on it. */
	renderer = $state.raw<SceneRenderer | null>(null);
	/** WebGL could not start: show a panel, not a black canvas. */
	webglError = $state(false);
	/** The GPU context dropped mid-session (common on mobile) and has not come back. */
	contextLost = $state(false);
	/** What the renderer last settled on, a surface feature included. `.raw`:
	 *  the renderer mutates position/satrec internals every frame. */
	focusedBody = $state.raw<PositionedBody | undefined>();

	private container: HTMLElement | null = null;
	private canvas: HTMLCanvasElement | null = null;
	private labelLayer: HTMLDivElement | null = null;
	private stopWatching: (() => void) | null = null;
	private readonly controls: (() => void)[] = [];
	private lostPanelTimer: ReturnType<typeof setTimeout> | undefined;
	private initialFocusPending = true;
	private pendingFocusId: string | null = null;
	private readonly listeners: { [K in keyof MapEvents]: Set<MapEvents[K]> } = {
		focuschange: new Set(),
		camera: new Set(),
		featureselect: new Set(),
		userpromoted: new Set(),
		contextlost: new Set(),
		contextrestored: new Set(),
		clock: new Set(),
		loading: new Set(),
		progress: new Set(),
		error: new Set(),
		datastale: new Set(),
		notice: new Set(),
		noticedismiss: new Set(),
		frame: new Set()
	};

	constructor(options: MapControllerOptions = {}) {
		if (options.settings) setSceneSettings(options.settings);
		this.clock = new SimClock(
			dateToJD(options.date ?? new Date()),
			options.live ?? options.date === undefined
		);
		this.initialView = {
			id: DEFAULT_FOCUS_ID,
			latitude: DEFAULT_FRAMING_LAT,
			longitude: DEFAULT_FRAMING_LON,
			zoom: DEFAULT_ZOOM,
			...options.view
		};
		this.ctx.onDataStale = () => this.emit('datastale');
		// Starts now so the bench overlaps the whole boot — clock snapping and
		// data loads included — behind the host's loading screen, never the
		// live scene. A stored result for this device returns at once.
		scheduleAtmosphereCalibration();
	}

	on<K extends keyof MapEvents>(event: K, listener: MapEvents[K]): () => void {
		this.listeners[event].add(listener);
		return () => this.listeners[event].delete(listener);
	}

	private emit<K extends keyof MapEvents>(event: K, ...args: Parameters<MapEvents[K]>): void {
		for (const listener of this.listeners[event]) {
			(listener as (...a: Parameters<MapEvents[K]>) => void)(...args);
		}
	}

	/** A loaded object by id, with its current position. */
	getBody(id: string): PositionedBody | undefined {
		return this.ctx.getBody(id);
	}

	/** Ids of the objects orbiting `id` that this map has loaded. Loading is
	 *  driven by focus and by the clock, so the list grows as the reader moves. */
	getChildren(id: string): string[] {
		return [...(this.ctx.bodies.getChildren(id) ?? [])];
	}

	/** Fetch the scene's data for the clock's date. Resolves when all of it is
	 *  in, small bodies included, which is well after there is something to
	 *  look at — {@link open} is what a caller opening a map wants. */
	load(targetId: string = this.initialView.id): Promise<void> {
		return this.ctx.load(jdToDate(this.clock.jd), targetId);
	}

	/**
	 * Load the scene and resolve as soon as it is worth looking at: the opening
	 * body placed, with a renderer to draw it. That is the end of the load's
	 * first phase; the small bodies behind it go on streaming for a second or
	 * two, under a map the reader can already move.
	 *
	 * Rejects only if the load fails before there is anything to look at. Past
	 * that point a failure has nowhere left to reject to, and reaches the host
	 * as an `error` event instead.
	 */
	async open(targetId: string = this.initialView.id): Promise<void> {
		const loaded = this.load(targetId);
		loaded.catch(() => {
			/* reported by the error effect, and logged by the data layer */
		});
		let watching = true;
		const framable = new Promise<void>((resolve) => {
			const check = (): void => {
				if (!watching) return;
				if (this.renderer && this.ctx.getBody(targetId)) resolve();
				// A timer alongside the frame: a backgrounded tab fires no rAF, and
				// the poll would never come back.
				else if (document.hidden) setTimeout(check, 100);
				else requestAnimationFrame(check);
			};
			check();
		});
		try {
			await Promise.race([loaded, framable]);
		} finally {
			// The body may never arrive — a probe whose record streams in later —
			// and then the load wins the race and the poll has to be called off.
			watching = false;
		}
	}

	/** Settle the camera on the opening view. The renderer could not do it when
	 *  it was built: no data had loaded yet, so it framed nothing and reported
	 *  no focus. Call it once {@link open} resolves. */
	applyInitialView(): void {
		const { id, latitude, longitude, zoom } = this.initialView;
		if (this.focusedBody || !this.ctx.getBody(id)) return;
		this.renderer?.snapToBody(id, latitude, longitude, zoom);
	}

	/** Build the canvas and label layer inside `container` and start rendering. */
	mount(container: HTMLElement): void {
		if (this.container) throw new Error('MapController is already mounted');
		this.container = container;
		container.classList.add('sm-map');

		const canvas = document.createElement('canvas');
		canvas.className = 'sm-map__canvas';
		// role="application" hands arrow keys through screen readers to the map.
		canvas.tabIndex = 0;
		canvas.setAttribute('role', 'application');
		canvas.setAttribute('aria-label', host().messages.scene_canvas_label());
		const labels = document.createElement('div');
		labels.className = 'scene-overlay';
		container.append(canvas, labels);
		this.canvas = canvas;
		this.labelLayer = labels;

		canvas.addEventListener('keydown', this.onKeyDown);
		canvas.addEventListener('webglcontextlost', this.onContextLost, false);
		canvas.addEventListener('webglcontextrestored', this.onContextRestored, false);
		document.addEventListener('visibilitychange', this.onVisibility);

		let renderer: SceneRenderer;
		try {
			renderer = new SceneRenderer(
				canvas,
				labels,
				this.ctx,
				this.clock,
				this.initialView,
				this.callbacks()
			);
		} catch (e) {
			console.error('[scene] renderer init failed:', e);
			this.webglError = true;
			return;
		}
		this.renderer = renderer;
		if (this.pendingFocusId !== null) {
			renderer.focusOnBody(this.pendingFocusId);
			this.pendingFocusId = null;
		}
		// Dev-only handle for headless render diagnostics (CDP scripts).
		if (import.meta.env.DEV || import.meta.env.VITE_BENCH_HOOK) {
			const w = window as unknown as Record<string, unknown>;
			w.__smRenderer = renderer;
			w.__smCtx = this.ctx;
		}

		const resize = new ResizeObserver(() =>
			renderer.resize(canvas.clientWidth, canvas.clientHeight)
		);
		resize.observe(canvas);
		const stopEffects = $effect.root(() => this.watch(renderer));
		this.stopWatching = () => {
			resize.disconnect();
			stopEffects();
		};
	}

	/** @internal Attach a control to the mounted map's container; its teardown
	 *  runs with {@link unmount}. */
	addControl(mount: (container: HTMLElement) => () => void): void {
		if (!this.container) throw new Error('MapController is not mounted');
		this.controls.push(mount(this.container));
	}

	/** Stop rendering and take the map's DOM back out of the container. */
	unmount(): void {
		const { container, canvas } = this;
		if (!container || !canvas) return;
		for (const teardown of this.controls.splice(0)) teardown();
		this.stopWatching?.();
		this.stopWatching = null;
		clearTimeout(this.lostPanelTimer);
		canvas.removeEventListener('keydown', this.onKeyDown);
		canvas.removeEventListener('webglcontextlost', this.onContextLost);
		canvas.removeEventListener('webglcontextrestored', this.onContextRestored);
		document.removeEventListener('visibilitychange', this.onVisibility);
		this.renderer?.dispose();
		this.renderer = null;
		canvas.remove();
		this.labelLayer?.remove();
		container.classList.remove('sm-map');
		this.container = this.canvas = this.labelLayer = null;
	}

	/** Reactions that outlive any one caller. Each reads its signal before the
	 *  renderer call so the dependency is tracked from the first run. */
	private watch(renderer: SceneRenderer): void {
		$effect(() => {
			void this.ctx.bodies.minorBodyVersion;
			renderer.rebuildMinorPointClouds();
		});
		const s = sceneSettings();
		for (const sink of SETTING_SINKS) $effect(() => sink(renderer, s));
		const clock = this.clock;
		$effect(() => {
			// Every field is read before anything is decided: an effect only
			// follows what it reads, and the clock ticks about sixty times a
			// second, so the date and the event are built for a host that is
			// listening and skipped for one that is not.
			const { jd, playing, timeScale, direction, live } = clock;
			if (this.listeners.clock.size === 0) return;
			this.emit('clock', { jd, date: jdToDate(jd), playing, timeScale, direction, live });
		});
		$effect(() => {
			// The boot benchmark counts as loading: it is the rest of what
			// `createMap` waits for, and a host watching this would otherwise be
			// told the map was ready and then left waiting with no signal.
			const loading = this.ctx.loading;
			const benching = calibrationUi.bootPending;
			this.emit('loading', loading || benching);
		});
		$effect(() => this.emit('progress', loadProgress.value));
		$effect(() => {
			const error = this.ctx.error;
			if (error !== null) this.emit('error', error);
		});
		// A benchmark re-run needs an uncontended GPU. Resume must not race the
		// context-lost pause.
		$effect(() => {
			const benchRunning = calibrationUi.progress !== null;
			if (benchRunning) renderer.pause();
			else if (!renderer.isContextLost()) renderer.resume();
		});
	}

	/** Re-read the settings into the renderer. The effects above do this on
	 *  their own for a reactive settings object; a plain one calls it after
	 *  each change. */
	applySettings(): void {
		const r = this.renderer;
		if (!r) return;
		const s = sceneSettings();
		for (const sink of SETTING_SINKS) sink(r, s);
	}

	private callbacks(): Callbacks {
		return {
			notices: {
				notify: (notice) => this.emit('notice', notice),
				dismiss: (topic) => this.emit('noticedismiss', topic)
			},
			onFocusChange: (body) => {
				const initial = this.initialFocusPending;
				this.initialFocusPending = false;
				this.focusedBody = body;
				const feature = body !== undefined && isSurfaceFeature(body);
				this.emit('focuschange', {
					body: feature ? this.ctx.getBody(body.featureAnchor!.hostId) : body,
					initial,
					feature
				});
			},
			onFrame: (jd, dtMs) => {
				if (this.listeners.frame.size > 0) this.emit('frame', { jd, dtMs });
			},
			onCameraPosition: (latitude, longitude, zoom) =>
				this.emit('camera', { latitude, longitude, zoom }),
			onUserPromotedChange: (count) => this.emit('userpromoted', count),
			onFeatureSelect: (bodyId, featureId, lat, lon, diameterM) =>
				this.emit('featureselect', { bodyId, featureId, lat, lon, diameterM })
		};
	}

	private readonly onKeyDown = (e: KeyboardEvent): void => {
		if (e.ctrlKey || e.metaKey || e.altKey) return;
		const step = (e.shiftKey ? 4 : 1) * KEY_ROTATE_RAD;
		let azimuth = 0;
		let polar = 0;
		let dolly = 1;
		switch (e.key) {
			case 'ArrowLeft':
				azimuth = step;
				break;
			case 'ArrowRight':
				azimuth = -step;
				break;
			case 'ArrowUp':
				polar = step;
				break;
			case 'ArrowDown':
				polar = -step;
				break;
			case '+':
			case '=':
				dolly = KEY_ZOOM_FACTOR;
				break;
			case '-':
			case '_':
				dolly = 1 / KEY_ZOOM_FACTOR;
				break;
			default:
				return;
		}
		e.preventDefault();
		this.renderer?.nudgeCamera(azimuth, polar, dolly);
	};

	// Reclaiming a backgrounded mobile tab drops the GL context (and can kill
	// workers). preventDefault opts into the browser's own restore on tab return.
	private readonly onContextLost = (e: Event): void => {
		e.preventDefault();
		console.warn('[scene] WebGL context lost');
		this.renderer?.pause();
		clearTimeout(this.lostPanelTimer);
		this.lostPanelTimer = setTimeout(() => {
			this.contextLost = true;
			this.emit('contextlost');
		}, CONTEXT_LOST_PANEL_DELAY_MS);
	};

	private readonly onContextRestored = (): void => {
		console.warn('[scene] WebGL context restored');
		clearTimeout(this.lostPanelTimer);
		this.contextLost = false;
		this.renderer?.handleContextRestored();
		// Context loss often coincides with dead workers, which onVisibility
		// skips while the context is lost — so probe here too.
		void this.renderer?.recoverWorkersIfDead(RESTORE_PING_TIMEOUT_MS);
		this.emit('contextrestored');
	};

	// OS-killed workers fire no event; probe on tab-return to recover frozen clouds.
	private readonly onVisibility = (): void => {
		if (document.visibilityState !== 'visible') return;
		if (this.renderer?.isContextLost()) return;
		void this.renderer?.recoverWorkersIfDead();
	};

	focusOnBody(id: string, zoom?: number, latitude?: number, longitude?: number): number {
		// A deep link on a body the renderer will not settle on itself (an
		// unplaceable one) can ask for focus while the scene is still mounting;
		// hold the ask rather than dropping it, and mount applies it.
		if (!this.renderer) {
			this.pendingFocusId = id;
			return 0;
		}
		return this.renderer.focusOnBody(id, zoom, latitude, longitude);
	}

	/** Instantly focus + frame a body (no fly) — for deep links whose target
	 *  loaded after the initial render settled on the placeholder parent. */
	snapToBody(id: string, latitude: number, longitude: number, zoom: number): void {
		this.renderer?.snapToBody(id, latitude, longitude, zoom);
	}

	/** Snap focus onto a body, framed looking toward another body (e.g. the Sun) above the ecliptic. */
	snapToBodyFacing(id: string, towardId: string, elevationDeg: number, distance: number): void {
		this.renderer?.snapToBodyFacing(id, towardId, elevationDeg, distance);
	}

	/** Focus a surface feature as a real orbitable body seated on its host.
	 *  Standoff scales with feature size, floored and capped so it never
	 *  collapses or overshoots.
	 *
	 *  `mode`: `pan` re-aims in place (label click); `frame` flies to it
	 *  (search/sidebar); `snap` places it instantly for deep links, where
	 *  `view` overrides the diameter-based framing. */
	focusOnFeature(
		bodyId: string,
		featureId: number,
		lat: number,
		lon: number,
		diameterM: number,
		name: string | null,
		mode: 'pan' | 'frame' | 'snap' = 'frame',
		view: CameraView | null = null
	): number {
		const hostBody = this.ctx.getBody(bodyId);
		if (!hostBody) return 0;
		const idealScene = kmToScene((diameterM * 4) / 1000);
		const minScene = kmToScene(0.02);
		const maxScene = kmToScene(effectiveRadiusKm(hostBody.data) * 5);
		const zoom = Math.min(Math.max(idealScene, minScene), maxScene);
		const anchor: FeatureAnchor = { hostId: bodyId, featureId, lat, lon, diameterM };
		return this.renderer?.focusOnFeature(anchor, name, zoom, mode, view) ?? 0;
	}

	/** @internal Re-aim at `body` without the focus handshake — for browser history. */
	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.renderer?.setFocusTarget(body, camPos);
	}

	/** Pin the host's own element to a place on the map. It is drawn in the
	 *  map's label layer, so it pans with the scene and is removed with it. */
	addMarker(options: MarkerOptions): Marker {
		const renderer = this.renderer;
		const canvas = this.canvas;
		if (!renderer || !canvas) throw new Error('MapController is not mounted');
		const marker = new MarkerExtension(options, canvas);
		marker.bind(() => renderer.extensions.remove(marker));
		renderer.extensions.add(marker);
		return marker;
	}

	setNorthReference(id: string | null): void {
		this.renderer?.setNorthReference(id);
	}

	setUserLocation(latitude: number, longitude: number): void {
		this.renderer?.setUserLocation(latitude, longitude);
	}

	clearUserPromoted(): void {
		this.renderer?.clearUserPromoted();
	}

	/** @internal */
	setSelectedFeature(featureId: number | null): void {
		this.renderer?.setSelectedFeature(featureId);
	}

	/** @internal Draw the trip the planner is showing, and whatever it is being
	 *  chosen from. */
	setTravelPath(
		plan: LabelledPath | null,
		options: readonly LabelledPath[] = [],
		hazards: readonly LabelledHazard[] = [],
		steps: readonly PathStep[] = []
	): void {
		this.renderer?.setTravelPath(plan, options, hazards, steps);
	}

	/** @internal Draw (or clear) the orbits the travel panel's ends are being
	 *  picked in, round their live bodies. `frame` names the ring being
	 *  interacted with, for the camera to put on screen. */
	setOrbitPreview(
		previews: readonly OrbitPreview[],
		frame: { bodyId: string; radiusKm: number } | null
	): void {
		this.renderer?.setOrbitPreview(previews, frame);
	}

	/** @internal */
	setTravelHover(id: string | null): void {
		this.renderer?.setTravelHover(id);
	}

	/** @internal Look at a place on the trip, which is usually nowhere near a body. */
	focusOnPathPoint(centerId: string, rKm: readonly [number, number, number]): void {
		this.renderer?.focusOnPathPoint(centerId, rKm);
	}

	/** @internal Follow a place along the trip without re-framing — for a
	 *  dragged clock. */
	trackPathPoint(centerId: string, rKm: readonly [number, number, number]): void {
		this.renderer?.trackPathPoint(centerId, rKm);
	}

	/** Stop drawing while opaque UI covers the map. */
	setCovered(covered: boolean): void {
		this.renderer?.setCovered(covered);
	}
}
