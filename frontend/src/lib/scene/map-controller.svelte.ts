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
	readonly ctx = new ContextManager();
	readonly clock: SimClock;
	readonly initialView: InitialView;
	/** Null until {@link mount} builds it, and again after {@link unmount};
	 *  reactive so a host can wait on it. */
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
	private lostPanelTimer: ReturnType<typeof setTimeout> | undefined;
	private initialFocusPending = true;
	private pendingFocusId: string | null = null;
	private readonly listeners: { [K in keyof MapEvents]: Set<MapEvents[K]> } = {
		focuschange: new Set(),
		camera: new Set(),
		featureselect: new Set(),
		userpromoted: new Set(),
		contextlost: new Set(),
		contextrestored: new Set()
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

	/** Fetch the scene's data for the clock's date. */
	load(targetId: string = this.initialView.id): Promise<void> {
		return this.ctx.load(jdToDate(this.clock.jd), targetId);
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

	/** Stop rendering and take the map's DOM back out of the container. */
	unmount(): void {
		const { container, canvas } = this;
		if (!container || !canvas) return;
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

	/** Re-aim at `body` without the focus handshake — for browser history. */
	setFocusTarget(body: PositionedBody, camPos?: Vec3): void {
		this.renderer?.setFocusTarget(body, camPos);
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

	setSelectedFeature(featureId: number | null): void {
		this.renderer?.setSelectedFeature(featureId);
	}

	/** Draw the trip the planner is showing, and whatever it is being chosen from. */
	setTravelPath(
		plan: LabelledPath | null,
		options: readonly LabelledPath[] = [],
		hazards: readonly LabelledHazard[] = [],
		steps: readonly PathStep[] = []
	): void {
		this.renderer?.setTravelPath(plan, options, hazards, steps);
	}

	/** Draw (or clear) the orbits the travel panel's ends are being picked in,
	 *  round their live bodies. `frame` names the ring being interacted with,
	 *  for the camera to put on screen. */
	setOrbitPreview(
		previews: readonly OrbitPreview[],
		frame: { bodyId: string; radiusKm: number } | null
	): void {
		this.renderer?.setOrbitPreview(previews, frame);
	}

	setTravelHover(id: string | null): void {
		this.renderer?.setTravelHover(id);
	}

	/** Look at a place on the trip, which is usually nowhere near a body. */
	focusOnPathPoint(centerId: string, rKm: readonly [number, number, number]): void {
		this.renderer?.focusOnPathPoint(centerId, rKm);
	}

	/** Follow a place along the trip without re-framing — for a dragged clock. */
	trackPathPoint(centerId: string, rKm: readonly [number, number, number]): void {
		this.renderer?.trackPathPoint(centerId, rKm);
	}

	/** Stop drawing while opaque UI covers the map. */
	setCovered(covered: boolean): void {
		this.renderer?.setCovered(covered);
	}
}
