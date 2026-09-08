/**
 * The flat map: one body's surface drawn into a container, in a projection of
 * the host's choosing, with layers it can switch and drawings of its own on
 * top.
 *
 * It is a canvas under an SVG. The canvas carries the pictures, which have to
 * be resampled pixel by pixel to change projection; the SVG carries everything
 * described by coordinates, which stays sharp at any zoom and can be clicked.
 * Both are driven from one viewport, so they never disagree about where a
 * place is.
 */

import { host } from '$lib/host';
import { dateToJD } from '$lib/time/jd';
import {
	creditOf,
	graticuleLayer,
	layerInfo,
	nomenclatureLayer,
	SVG_NS,
	type Layer,
	type LayerCredit,
	type LayerInfo,
	type RasterLayer,
	type VectorLayer
} from './layers';
import { Overlay, type FlatMarker, type FlatShape } from './overlay';
import {
	createProjection,
	PROJECTION_IDS,
	type Projection,
	type ProjectionId,
	type ProjectionOptions
} from './projection';
import {
	compositeLayers,
	drawEquirect,
	imageToRaster,
	InverseLookup,
	type RasterImage
} from './raster';
import { bestTier, bundleUrl, loadBodySources, type BodySources } from './sources';
import { clampView, Viewport, type ViewState } from './view';
import type { LonLat } from './geometry';
import './flat-map.css';

export interface FlatMapOptions {
	/** Body to draw, by export id — `"naif-399"` for Earth, `"naif-499"` for
	 *  Mars. Earth when left out. */
	body?: string;
	projection?: ProjectionId;
	/** Meridian and parallel the map is centred on. The parallel only turns the
	 *  two globe projections; the others are always centred on the equator. */
	centerLon?: number;
	centerLat?: number;
	/** How far from the centre a globe projection reaches, in degrees. */
	clipAngle?: number;
	/** 1 shows the whole world. */
	zoom?: number;
	/** The moment the map is of, which picks the cloud snapshot and the month
	 *  of a seasonal surface. Now when left out. */
	jd?: number;
	/** Which layers start switched on, by id. The surface always is. */
	layers?: Record<string, boolean>;
	/** Let the reader pan and zoom. On by default. */
	interactive?: boolean;
	maxZoom?: number;
}

export interface FlatViewState {
	projection: ProjectionId;
	zoom: number;
	centerLon: number;
	centerLat: number;
}

export interface FlatMapEvents {
	/** The first surface picture is on screen. */
	ready: () => void;
	error: (error: Error) => void;
	viewchange: (view: FlatViewState) => void;
	layerschange: (layers: LayerInfo[]) => void;
	/** Where the reader clicked, or null for a click off the world. */
	click: (at: LonLat | null, event: PointerEvent) => void;
	pointermove: (at: LonLat | null, event: PointerEvent) => void;
}

/** Past this the low tier is mush and the next one is worth its download. */
const TIER_BY_ZOOM: [number, string][] = [
	[6, 'high'],
	[2.5, 'medium']
];

/**
 * Resampling costs per pixel, so the canvas is capped rather than left to
 * follow a large container on a dense screen. Most projections resolve a whole
 * row of it at once and stay well inside a frame at this size; the ones that
 * cannot are drawn coarsely while they move, so the full cost is only ever
 * paid once a gesture ends.
 */
const MAX_RASTER_PIXELS = 2_200_000;

/** Ceiling on how much of a texture is read back for sampling. Beyond this the
 *  decode and the read cost more than the detail is worth. */
const MAX_WORKING_WIDTH = 4096;

/** How long a frame drawn during a gesture may take. A softer map that keeps
 *  up reads better than a sharp one that does not, so a projection whose
 *  resampling costs more than this is drawn at a fraction of its resolution
 *  until the movement stops. Most projections resolve a whole row at once,
 *  come in far under the budget and so stay sharp throughout. */
const MOVING_BUDGET_MS = 11;

/** How far the resolution may be cut to meet that budget. Past this the map is
 *  too soft to read, and a dropped frame is the better trade. */
const MIN_INTERACTION_SCALE = 0.4;

/** And the other end: a frame a little over the budget drops from sixty to
 *  fifty a second, which passes unnoticed, where a map drawn a little softer
 *  does not. So a projection only coarsens once the cut is worth making. */
const WORTH_COARSENING = 0.8;

/** How long after the last movement the map is redrawn in full. */
const SETTLE_MS = 140;

const DEFAULT_BODY = 'naif-399';

function isRaster(layer: Layer): layer is RasterLayer {
	return layer.kind === 'raster';
}

export class FlatMap {
	private container: HTMLElement | null = null;
	private readonly root = document.createElement('div');
	private readonly canvas = document.createElement('canvas');
	private readonly svg = document.createElementNS(SVG_NS, 'svg');
	private readonly layerGroup = document.createElementNS(SVG_NS, 'g');
	private readonly shapeGroup = document.createElementNS(SVG_NS, 'g');
	private readonly markerLayer = document.createElement('div');
	private readonly ctx: CanvasRenderingContext2D | null;

	readonly overlay: Overlay;

	private bodyId: string;
	private sources: BodySources = {};
	private layerList: Layer[] = [];
	private projection: Projection;
	private projectionId: ProjectionId;
	private projectionOptions: ProjectionOptions;
	private view: ViewState;
	private readonly maxZoom: number;
	private jd: number;
	private interactive: boolean;
	/** The body's mean radius, so a circle can be drawn in kilometres. */
	bodyRadiusKm: number | null = null;

	/** Decoded pictures by URL, and the readable copies the resampler needs. */
	private readonly bitmaps = new Map<string, ImageBitmap>();
	private readonly rasters = new Map<string, RasterImage>();
	private readonly pending = new Set<string>();
	/** Pictures the export does not have. Remembered, or every pan would ask
	 *  for them again and report the same failure. */
	private readonly missing = new Set<string>();
	/** Bumped whenever the map moves to another body, so work started for the
	 *  one being left can tell that it is no longer wanted. */
	private generation = 0;
	/** Teardowns for controls mounted inside the map's box. */
	private readonly controls: (() => void)[] = [];

	private lookup: InverseLookup | null = null;
	private lookupKey = '';
	private buffer: ImageData | null = null;
	private frame = 0;
	private resizeObserver: ResizeObserver | null = null;
	private readonly listeners = new Map<keyof FlatMapEvents, Set<(...args: never[]) => void>>();
	private announcedReady = false;
	private disposed = false;
	/** Set while a gesture is in flight, to draw coarsely until it stops. */
	private moving = false;
	/** Running cost of one drawn pixel, which sets the resolution of a moving
	 *  frame. Zero until the first draw has been timed. */
	private msPerPixel = 0;
	private settleTimer = 0;
	/** Which layers have been asked for, by id — the host's opening choice and
	 *  every change since. Kept apart from the layers themselves, which are
	 *  rebuilt per body: what the reader switched on should outlast a body that
	 *  happens not to have it. */
	private readonly chosenVisibility = new Map<string, boolean>();
	/** Layers the host added itself. Kept aside from the body's own, so
	 *  changing body rebuilds one set without discarding the other. */
	private readonly customLayers: Layer[] = [];

	constructor(options: FlatMapOptions = {}) {
		this.bodyId = options.body ?? DEFAULT_BODY;
		this.projectionId = options.projection ?? 'equirectangular';
		this.projectionOptions = {
			centerLon: options.centerLon ?? 0,
			centerLat: options.centerLat,
			clipAngle: options.clipAngle
		};
		this.projection = createProjection(this.projectionId, this.projectionOptions);
		this.maxZoom = options.maxZoom ?? 16;
		this.view = { zoom: options.zoom ?? 1, centerX: 0, centerY: 0 };
		this.jd = options.jd ?? dateToJD(new Date());
		this.interactive = options.interactive ?? true;

		this.root.className = 'sm-flat';
		this.canvas.className = 'sm-flat__raster';
		this.svg.setAttribute('class', 'sm-flat__vector');
		this.markerLayer.className = 'sm-flat__markers';
		this.svg.append(this.layerGroup, this.shapeGroup);
		this.root.append(this.canvas, this.svg, this.markerLayer);
		this.ctx = this.canvas.getContext('2d');
		this.overlay = new Overlay(this.shapeGroup, this.markerLayer, () => this.render());
		this.setInteractive(this.interactive);
		for (const [id, visible] of Object.entries(options.layers ?? {})) {
			this.chosenVisibility.set(id, visible);
		}
	}

	// -- lifecycle ------------------------------------------------------------

	mount(container: HTMLElement): void {
		this.container = container;
		container.append(this.root);
		this.resizeObserver = new ResizeObserver(() => this.renderMoving());
		this.resizeObserver.observe(this.root);
		this.attachInteraction();
	}

	/** @internal Attach a control inside the map's own box — which is the
	 *  positioned element the container need not be — and tear it down with
	 *  {@link unmount}. */
	addControl(mount: (root: HTMLElement) => () => void): void {
		this.controls.push(mount(this.root));
	}

	unmount(): void {
		this.disposed = true;
		for (const teardown of this.controls.splice(0)) teardown();
		this.resizeObserver?.disconnect();
		this.resizeObserver = null;
		cancelAnimationFrame(this.frame);
		clearTimeout(this.settleTimer);
		for (const layer of this.layerList) if (!isRaster(layer)) layer.dispose?.();
		this.overlay.clear();
		for (const bitmap of this.bitmaps.values()) bitmap.close();
		this.bitmaps.clear();
		this.rasters.clear();
		this.root.remove();
		this.container = null;
	}

	/** Find the body's pictures and get the first one on screen. Resolves once
	 *  there is something to look at, or rejects when the body has no map. */
	async load(): Promise<void> {
		await this.adopt(this.bodyId);
	}

	/**
	 * Take a body on: find out what it has, and only then show it.
	 *
	 * Nothing of the body already on screen is let go until the new one is known
	 * to have a map at all, so asking for a body that has none leaves the map as
	 * it was and rejects, rather than emptying it first.
	 */
	private async adopt(bodyId: string): Promise<void> {
		const sources = await loadBodySources(bodyId);
		if (this.disposed) return;
		if (!sources.surface) {
			const error = new Error(`spacemap: no map texture for ${bodyId}`);
			this.emit('error', error);
			throw error;
		}
		if (bodyId !== this.bodyId) this.release();
		this.bodyId = bodyId;
		this.sources = sources;
		this.bodyRadiusKm = sources.radiusKm ?? null;
		this.overlay.setBodyRadiusKm(this.bodyRadiusKm);
		this.buildLayers();
		await this.loadVisible();
		if (this.disposed) return;
		this.render();
	}

	/** Let go of the pictures and the layers of the body being left behind. The
	 *  generation moves with them, so a fetch still in flight for that body
	 *  drops what it decodes instead of holding it for nothing. */
	private release(): void {
		this.generation++;
		for (const bitmap of this.bitmaps.values()) bitmap.close();
		this.bitmaps.clear();
		this.rasters.clear();
		this.missing.clear();
		for (const layer of this.layerList) {
			if (!isRaster(layer) && !this.customLayers.includes(layer)) layer.dispose?.();
		}
	}

	private buildLayers(): void {
		const { messages } = host();
		const layers: Layer[] = [];
		const { surface, clouds, night } = this.sources;
		if (surface) {
			layers.push({
				kind: 'raster',
				id: 'surface',
				label: messages.layer_surface(),
				visible: true,
				opacity: 1,
				blend: 'normal',
				credit: creditOf(surface),
				tiers: surface.tiers,
				url: (jd, tier) => bundleUrl(surface, tier, jd)
			});
		}
		if (clouds) {
			layers.push({
				kind: 'raster',
				id: 'clouds',
				label: messages.layer_clouds(),
				visible: true,
				opacity: 1,
				blend: 'normal',
				credit: creditOf(clouds),
				tiers: clouds.tiers,
				url: (jd, tier) => bundleUrl(clouds, tier, jd)
			});
		}
		if (night) {
			layers.push({
				kind: 'raster',
				id: 'night',
				label: messages.layer_night(),
				visible: false,
				// Lights only ever add to what is under them; drawn as a normal
				// layer they would black out the daylit surface.
				opacity: 0.85,
				blend: 'add',
				credit: creditOf(night),
				tiers: night.tiers,
				url: (jd, tier) => bundleUrl(night, tier, jd)
			});
		}
		layers.push(graticuleLayer(messages.layer_graticule()));
		layers.push(nomenclatureLayer(this.bodyId, messages.layer_nomenclature()));
		layers.push(...this.customLayers);

		for (const layer of layers) {
			const wanted = this.chosenVisibility.get(layer.id);
			if (wanted !== undefined) layer.visible = wanted;
		}
		this.layerList = layers;
		this.emit('layerschange', this.layers);
	}

	// -- layers ---------------------------------------------------------------

	get layers(): LayerInfo[] {
		return this.layerList.map(layerInfo);
	}

	/** Credits for everything currently drawn — what the embed has to show. */
	get credits(): LayerCredit[] {
		const seen = new Set<string>();
		const out: LayerCredit[] = [];
		for (const layer of this.layerList) {
			if (!layer.visible || !layer.credit) continue;
			if (seen.has(layer.credit.organisation)) continue;
			seen.add(layer.credit.organisation);
			out.push(layer.credit);
		}
		return out;
	}

	setLayerVisible(id: string, visible: boolean): void {
		this.chosenVisibility.set(id, visible);
		const layer = this.layerList.find((l) => l.id === id);
		if (!layer || layer.visible === visible) return;
		layer.visible = visible;
		this.emit('layerschange', this.layers);
		void this.loadVisible();
		this.render();
	}

	setLayerOpacity(id: string, opacity: number): void {
		const layer = this.layerList.find((l) => l.id === id);
		if (!layer || !isRaster(layer)) return;
		layer.opacity = Math.min(1, Math.max(0, opacity));
		this.render();
	}

	/** A picture of the host's own, wrapped round the body the same way the
	 *  export's are: longitude across, latitude down, −180° at the left edge. */
	addRasterLayer(spec: {
		id: string;
		label?: string;
		url: string;
		opacity?: number;
		blend?: 'normal' | 'add';
		visible?: boolean;
		credit?: LayerCredit;
	}): void {
		const layer: Layer = {
			kind: 'raster',
			id: spec.id,
			label: spec.label ?? spec.id,
			visible: spec.visible ?? true,
			opacity: spec.opacity ?? 1,
			blend: spec.blend ?? 'normal',
			credit: spec.credit,
			tiers: ['low'],
			url: () => spec.url
		};
		this.customLayers.push(layer);
		this.layerList.push(layer);
		this.emit('layerschange', this.layers);
		void this.loadVisible();
	}

	/** A layer the host draws itself, given the view to draw for. Where a
	 *  vector terrain map or a coverage grid goes. */
	addVectorLayer(spec: {
		id: string;
		label?: string;
		visible?: boolean;
		credit?: LayerCredit;
		render: VectorLayer['render'];
		prepare?: VectorLayer['prepare'];
	}): void {
		const layer: Layer = {
			kind: 'vector',
			id: spec.id,
			label: spec.label ?? spec.id,
			visible: spec.visible ?? true,
			credit: spec.credit,
			render: spec.render,
			prepare: spec.prepare
		};
		this.customLayers.push(layer);
		this.layerList.push(layer);
		this.emit('layerschange', this.layers);
		void this.loadVisible();
	}

	// -- view -----------------------------------------------------------------

	get projectionName(): ProjectionId {
		return this.projectionId;
	}

	static get projections(): readonly ProjectionId[] {
		return PROJECTION_IDS;
	}

	setProjection(id: ProjectionId, options: ProjectionOptions = {}): void {
		this.projectionId = id;
		this.projectionOptions = { ...this.projectionOptions, ...options };
		this.projection = createProjection(id, this.projectionOptions);
		// The centre is in plane units, which the new projection measures
		// differently; the safe reading of "same view" is the whole world.
		this.view = { ...this.view, centerX: 0, centerY: 0 };
		this.render();
		this.emit('viewchange', this.viewState);
	}

	/** Where the map is, as a place rather than as plane coordinates — the
	 *  middle of the frame. A globe is turned to face it and a rectangle is slid
	 *  to it, so what {@link setView} is given is what this reads back. */
	get viewState(): FlatViewState {
		const viewport = this.viewport();
		const middle = viewport.unproject(viewport.width / 2, viewport.height / 2);
		return {
			projection: this.projectionId,
			zoom: this.view.zoom,
			centerLon: middle?.[0] ?? this.projectionOptions.centerLon ?? 0,
			centerLat: middle?.[1] ?? this.projectionOptions.centerLat ?? 0
		};
	}

	setView(view: Partial<FlatViewState>): void {
		if (view.projection && view.projection !== this.projectionId) {
			this.setProjection(view.projection);
		}
		if (view.zoom !== undefined) this.view = { ...this.view, zoom: view.zoom };
		if (view.centerLon !== undefined || view.centerLat !== undefined) {
			const current = this.viewState;
			const lon = view.centerLon ?? current.centerLon;
			const lat = view.centerLat ?? current.centerLat;
			if (this.projection.azimuthal) {
				// A globe has no middle to slide to: it is turned instead, which is
				// the same thing said in the projection's own terms.
				this.projectionOptions = { ...this.projectionOptions, centerLon: lon, centerLat: lat };
				this.projection = createProjection(this.projectionId, this.projectionOptions);
			} else {
				const plane = this.projection.forward(lon, lat);
				if (plane) this.view = { ...this.view, centerX: plane[0], centerY: plane[1] };
			}
		}
		void this.loadVisible();
		this.render();
		this.emit('viewchange', this.viewState);
	}

	/** The moment the map is of. Moves the clouds and, on Earth, the season. */
	setTime(jd: number): void {
		this.jd = jd;
		void this.loadVisible();
		this.render();
	}

	async setBody(bodyId: string): Promise<void> {
		if (bodyId === this.bodyId) return;
		await this.adopt(bodyId);
	}

	/** Screen pixel for a place, relative to the map's own box. */
	project(lon: number, lat: number): [number, number] | null {
		return this.viewport().project(lon, lat);
	}

	/** The place under a pixel of the map's box, or null off the world. */
	unproject(px: number, py: number): LonLat | null {
		const found = this.viewport().unproject(px, py);
		return found ? { lon: found[0], lat: found[1] } : null;
	}

	// -- drawing --------------------------------------------------------------

	addPolyline(options: Parameters<Overlay['addPolyline']>[0]): FlatShape {
		const shape = this.overlay.addPolyline(options);
		this.render();
		return shape;
	}

	addPolygon(options: Parameters<Overlay['addPolygon']>[0]): FlatShape {
		const shape = this.overlay.addPolygon(options);
		this.render();
		return shape;
	}

	addBox(options: Parameters<Overlay['addBox']>[0]): FlatShape {
		const shape = this.overlay.addBox(options);
		this.render();
		return shape;
	}

	addCircle(options: Parameters<Overlay['addCircle']>[0]): FlatShape {
		const shape = this.overlay.addCircle(options);
		this.render();
		return shape;
	}

	addMarker(options: Parameters<Overlay['addMarker']>[0]): FlatMarker {
		const marker = this.overlay.addMarker(options);
		this.render();
		return marker;
	}

	/** Remove every drawing the host has added, leaving the layers alone. */
	clearDrawings(): void {
		this.overlay.clear();
		this.render();
	}

	// -- events ---------------------------------------------------------------

	on<K extends keyof FlatMapEvents>(event: K, listener: FlatMapEvents[K]): () => void {
		let set = this.listeners.get(event);
		if (!set) {
			set = new Set();
			this.listeners.set(event, set);
		}
		set.add(listener as (...args: never[]) => void);
		return () => set.delete(listener as (...args: never[]) => void);
	}

	private emit<K extends keyof FlatMapEvents>(
		event: K,
		...args: Parameters<FlatMapEvents[K]>
	): void {
		const set = this.listeners.get(event);
		if (!set) return;
		for (const listener of [...set]) (listener as (...a: unknown[]) => void)(...args);
	}

	// -- pictures -------------------------------------------------------------

	private tier(tiers: readonly string[]): string {
		const wanted = TIER_BY_ZOOM.find(([zoom]) => this.view.zoom >= zoom)?.[1] ?? 'low';
		return bestTier(tiers, wanted);
	}

	private urlsInUse(): string[] {
		return this.layerList
			.filter((l): l is RasterLayer => isRaster(l) && l.visible)
			.map((layer) => layer.url(this.jd, this.tier(layer.tiers)));
	}

	/** Fetch and decode whatever the current view needs but has not got. */
	private async loadVisible(): Promise<void> {
		const wanted = this.urlsInUse();
		const prepares = this.layerList
			.filter((l): l is VectorLayer => !isRaster(l) && l.visible && Boolean(l.prepare))
			.map((layer) =>
				layer.prepare!().then(
					() => this.render(),
					() => {
						/* a layer that will not load simply does not draw */
					}
				)
			);
		const fetches = wanted
			.filter((url) => !this.bitmaps.has(url) && !this.pending.has(url) && !this.missing.has(url))
			.map(async (url) => {
				this.pending.add(url);
				const generation = this.generation;
				try {
					const response = await fetch(url);
					if (!response.ok) throw new Error(`HTTP ${response.status}`);
					const bitmap = await createImageBitmap(await response.blob());
					if (this.disposed || generation !== this.generation) {
						bitmap.close();
						return;
					}
					this.bitmaps.set(url, bitmap);
					this.render();
				} catch (cause) {
					if (generation !== this.generation) return;
					this.missing.add(url);
					this.emit('error', new Error(`spacemap: could not load ${url}`, { cause }));
				} finally {
					this.pending.delete(url);
				}
			});
		await Promise.all([...prepares, ...fetches]);
	}

	/** The readable copy the resampler samples, shrunk to about what the view
	 *  can show. Cached per size so panning does not rebuild it. */
	private rasterFor(url: string, workingWidth: number): RasterImage | null {
		const key = `${url}@${workingWidth}`;
		const cached = this.rasters.get(key);
		if (cached) return cached;
		const bitmap = this.bitmaps.get(url);
		if (!bitmap) return null;
		const raster = imageToRaster(bitmap, workingWidth);
		if (!raster) return null;
		// One size per picture is enough; a new zoom replaces the old.
		for (const existing of this.rasters.keys()) {
			if (existing.startsWith(`${url}@`)) this.rasters.delete(existing);
		}
		this.rasters.set(key, raster);
		return raster;
	}

	// -- rendering ------------------------------------------------------------

	private viewport(width?: number, height?: number): Viewport {
		const w = width ?? this.root.clientWidth ?? 1;
		const h = height ?? this.root.clientHeight ?? 1;
		this.view = clampView(this.view, this.projection, w, h, this.maxZoom);
		return new Viewport(this.projection, Math.max(1, w), Math.max(1, h), this.view);
	}

	/** Draw on the next frame. Repeated calls in one frame draw once. */
	render(): void {
		if (this.disposed) return;
		cancelAnimationFrame(this.frame);
		this.frame = requestAnimationFrame(() => this.draw());
	}

	/** Draw coarsely now and sharply when the movement stops. */
	private renderMoving(): void {
		this.moving = true;
		clearTimeout(this.settleTimer);
		this.settleTimer = window.setTimeout(() => {
			this.moving = false;
			this.render();
		}, SETTLE_MS);
		this.render();
	}

	private draw(): void {
		const cssWidth = this.root.clientWidth;
		const cssHeight = this.root.clientHeight;
		if (!this.ctx || cssWidth === 0 || cssHeight === 0) return;

		// The canvas is capped: resampling costs a fixed amount per pixel, so a
		// large container on a dense screen would otherwise drop frames.
		const dpr = Math.min(window.devicePixelRatio || 1, 2);
		const budget = Math.sqrt(MAX_RASTER_PIXELS / (cssWidth * cssHeight * dpr * dpr));
		const sharp = dpr * Math.min(1, budget);
		const full = cssWidth * sharp * cssHeight * sharp;
		const ratio = sharp * (this.moving ? this.interactionScale(full) : 1);
		const width = Math.max(1, Math.round(cssWidth * ratio));
		const height = Math.max(1, Math.round(cssHeight * ratio));
		if (this.canvas.width !== width || this.canvas.height !== height) {
			this.canvas.width = width;
			this.canvas.height = height;
			this.buffer = null;
			this.lookup = null;
		}

		const cssViewport = this.viewport(cssWidth, cssHeight);
		const deviceViewport = new Viewport(this.projection, width, height, this.view);
		this.drawRaster(deviceViewport, width, height);
		this.drawVector(cssViewport);

		if (!this.announcedReady && this.bitmaps.size > 0) {
			this.announcedReady = true;
			this.emit('ready');
		}
	}

	/**
	 * What one pixel of the last few resampled frames cost, in milliseconds.
	 * Kept as a running mean so one slow frame — the browser busy elsewhere —
	 * does not decide the resolution on its own.
	 */
	private record(ms: number, pixels: number): void {
		if (pixels <= 0) return;
		const cost = ms / pixels;
		this.msPerPixel = this.msPerPixel === 0 ? cost : this.msPerPixel * 0.7 + cost * 0.3;
	}

	/**
	 * The fraction of full resolution a moving frame is drawn at, from what the
	 * projection has been measured to cost rather than from a list of which ones
	 * are slow. A projection that fits the budget is left alone.
	 *
	 * `full` is the pixel count the frame would have at full resolution, not the
	 * count the last frame happened to be drawn at — measuring against a canvas
	 * that is already coarse would let the scale chase its own tail.
	 */
	private interactionScale(full: number): number {
		if (this.msPerPixel <= 0 || full <= 0) return 1;
		const scale = Math.sqrt(MOVING_BUDGET_MS / this.msPerPixel / full);
		if (scale > WORTH_COARSENING) return 1;
		return Math.max(MIN_INTERACTION_SCALE, scale);
	}

	private drawRaster(viewport: Viewport, width: number, height: number): void {
		const ctx = this.ctx!;
		ctx.clearRect(0, 0, width, height);
		const layers = this.layerList.filter((l): l is RasterLayer => isRaster(l) && l.visible);
		if (layers.length === 0) return;

		if (this.projectionId === 'equirectangular') {
			// The texture is already in this space, so the browser's own scaler
			// does the whole job — sharper than resampling, and much faster.
			const drawable = layers
				.map((layer) => ({
					image: this.bitmaps.get(layer.url(this.jd, this.tier(layer.tiers))),
					opacity: layer.opacity,
					blend: layer.blend
				}))
				.filter((l): l is { image: ImageBitmap; opacity: number; blend: 'normal' | 'add' } =>
					Boolean(l.image)
				);
			if (drawable.length) drawEquirect(ctx, viewport, drawable);
			return;
		}

		// About twice the detail the view can show, rounded to a power of two so
		// a zoom gesture reuses one working copy rather than rebuilding per step.
		const wanted = width * 2 * this.view.zoom;
		const workingWidth = Math.min(
			MAX_WORKING_WIDTH,
			2 ** Math.ceil(Math.log2(Math.max(256, wanted)))
		);

		// The pictures are read back first and left out of the timing below. A
		// readback is a texture's own one-off cost, tens of milliseconds of it,
		// and nothing to do with how many pixels this frame covers.
		const stack = layers
			.map((layer) => ({
				image: this.rasterFor(layer.url(this.jd, this.tier(layer.tiers)), workingWidth),
				opacity: layer.opacity,
				blend: layer.blend
			}))
			.filter((l): l is { image: RasterImage; opacity: number; blend: 'normal' | 'add' } =>
				Boolean(l.image)
			);
		if (stack.length === 0) return;

		if (!this.buffer || this.buffer.width !== width || this.buffer.height !== height) {
			this.buffer = ctx.createImageData(width, height);
		}
		const key = `${this.projectionId}|${JSON.stringify(this.projectionOptions)}|${
			this.view.zoom
		}|${this.view.centerX}|${this.view.centerY}|${width}x${height}`;
		const resampling = !this.lookup || this.lookupKey !== key;
		const started = performance.now();
		if (resampling) {
			this.lookup = new InverseLookup(viewport, width, height);
			this.lookupKey = key;
		}
		compositeLayers(this.lookup!, stack, this.buffer);
		ctx.putImageData(this.buffer, 0, 0);
		// Only a frame that resampled is worth timing: it is the shape every
		// frame of a gesture has, and the one the budget is set against. A frame
		// that reused the lookup did a fraction of the work and would talk the
		// resolution back up.
		if (resampling) this.record(performance.now() - started, width * height);
	}

	private drawVector(viewport: Viewport): void {
		this.svg.setAttribute('viewBox', `0 0 ${viewport.width} ${viewport.height}`);
		this.layerGroup.replaceChildren();
		for (const layer of this.layerList) {
			if (isRaster(layer) || !layer.visible) continue;
			const group = document.createElementNS(SVG_NS, 'g');
			group.setAttribute('data-layer', layer.id);
			layer.render(viewport, group);
			this.layerGroup.append(group);
		}
		this.overlay.redraw(viewport);
	}

	// -- interaction ----------------------------------------------------------

	setInteractive(interactive: boolean): void {
		this.interactive = interactive;
		this.root.classList.toggle('sm-flat--interactive', interactive);
	}

	private attachInteraction(): void {
		let dragging = false;
		let lastX = 0;
		let lastY = 0;
		let moved = false;

		const localPoint = (event: PointerEvent | WheelEvent): [number, number] => {
			const box = this.root.getBoundingClientRect();
			return [event.clientX - box.left, event.clientY - box.top];
		};

		this.root.addEventListener('pointerdown', (event) => {
			if (!this.interactive || event.button !== 0) return;
			dragging = true;
			moved = false;
			lastX = event.clientX;
			lastY = event.clientY;
			this.root.setPointerCapture(event.pointerId);
			this.root.classList.add('sm-flat--dragging');
		});

		this.root.addEventListener('pointermove', (event) => {
			const [px, py] = localPoint(event);
			if (!dragging) {
				this.emit('pointermove', this.unproject(px, py), event);
				return;
			}
			const dx = event.clientX - lastX;
			const dy = event.clientY - lastY;
			lastX = event.clientX;
			lastY = event.clientY;
			if (Math.abs(dx) > 1 || Math.abs(dy) > 1) moved = true;
			this.drag(dx, dy);
		});

		const end = (event: PointerEvent) => {
			if (!dragging) return;
			dragging = false;
			this.root.releasePointerCapture?.(event.pointerId);
			this.root.classList.remove('sm-flat--dragging');
			if (!moved) {
				const [px, py] = localPoint(event);
				this.emit('click', this.unproject(px, py), event);
			}
		};
		this.root.addEventListener('pointerup', end);
		this.root.addEventListener('pointercancel', end);

		this.root.addEventListener(
			'wheel',
			(event) => {
				if (!this.interactive) return;
				event.preventDefault();
				const [px, py] = localPoint(event);
				this.zoomBy(Math.exp(-event.deltaY / 400), px, py);
			},
			{ passive: false }
		);
	}

	/**
	 * A drag turns a globe and slides a rectangle. Both keep the place under
	 * the pointer roughly under it, which is what makes the gesture feel like
	 * moving the map rather than moving a camera.
	 */
	private drag(dx: number, dy: number): void {
		const viewport = this.viewport();
		if (this.projection.azimuthal) {
			const perRadian = viewport.scale;
			const degrees = (v: number) => (v / perRadian) * (180 / Math.PI);
			const centerLon = (this.projectionOptions.centerLon ?? 0) - degrees(dx);
			const centerLat = Math.max(
				-90,
				Math.min(90, (this.projectionOptions.centerLat ?? 0) + degrees(dy))
			);
			this.projectionOptions = { ...this.projectionOptions, centerLon, centerLat };
			this.projection = createProjection(this.projectionId, this.projectionOptions);
		} else {
			this.view = {
				...this.view,
				centerX: this.view.centerX - dx / viewport.scale,
				centerY: this.view.centerY + dy / viewport.scale
			};
		}
		this.renderMoving();
		this.emit('viewchange', this.viewState);
	}

	/** Zoom about a point, so what is under the pointer stays under it. */
	private zoomBy(factor: number, px: number, py: number): void {
		const before = this.viewport();
		const anchor = before.fromScreen(px, py);
		const zoom = Math.min(this.maxZoom, Math.max(1, this.view.zoom * factor));
		if (zoom === this.view.zoom) return;
		this.view = { ...this.view, zoom };
		const after = this.viewport();
		if (!this.projection.azimuthal) {
			const moved = after.fromScreen(px, py);
			this.view = {
				...this.view,
				centerX: this.view.centerX + anchor[0] - moved[0],
				centerY: this.view.centerY + anchor[1] - moved[1]
			};
		}
		void this.loadVisible();
		this.renderMoving();
		this.emit('viewchange', this.viewState);
	}
}
