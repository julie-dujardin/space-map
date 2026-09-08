/**
 * The map for pages outside spacemap.co, as one script.
 *
 * There are two of them. {@link createMap} puts the Solar System in a
 * container — bodies and spacecraft in three dimensions, over time.
 * {@link createFlatMap} puts one body's surface there instead, drawn flat in a
 * projection of the host's choosing, with layers it can switch and drawings of
 * its own on top. The classes, the host seam and the clock's date helpers are
 * exported for hosts that drive them directly.
 */

import { configureHost, type CoreMessages, type HostOverrides } from '$lib/host';
import {
	MapController,
	type MapControllerOptions,
	type MapEvents
} from '$lib/scene/map-controller.svelte';
import { atmosphereBootSettled } from '$lib/scene/perf/atmosphere-calibration';
import { defaultSceneSettings } from '$lib/scene/settings.svelte';
import { dateToJD, jdToDate } from '$lib/time/jd';
import { FlatMap, type FlatMapEvents, type FlatMapOptions } from '$lib/flatmap/flat-map';
import { mountAttribution } from './controls/attribution.svelte';
import { mountFlatAttribution } from './controls/flat-attribution';

export interface MapOptions extends MapControllerOptions {
	/** Root of the data export; the production CDN when omitted. Page-wide,
	 *  like everything on the host: the last map created sets it, and data
	 *  already fetched keeps the origin it came from. Images keep their own
	 *  origin, since the production data origin does not serve them; a mirror
	 *  that serves both sets `imagesUrl` through {@link configureHost}. */
	dataUrl?: string;
	/** BCP-47 tag that picks localized names; English when omitted. */
	locale?: string;
	/** Replaces the English wording the map renders itself, one key at a time. */
	messages?: Partial<CoreMessages>;
	/** Listeners attached before the first load, so the boot's `progress`,
	 *  `loading` and `error` events are observable while it runs. Later ones go
	 *  through {@link MapController.on}. */
	events?: { [K in keyof MapEvents]?: MapEvents[K] };
}

/** Mount a map in `container` and resolve once it is worth looking at: the
 *  opening body placed, and the one-off quality benchmark done — that measures
 *  the GPU, so it must not run while the reader is already moving the camera.
 *  The small bodies go on streaming in behind the map this returns.
 *
 *  Rejects when WebGL is unavailable, or when the data fails before there is
 *  anything to look at; a failure past that point arrives as an `error` event. */
export async function createMap(
	container: HTMLElement,
	options: MapOptions = {}
): Promise<MapController> {
	const { dataUrl, locale, messages, events, ...controller } = options;
	const overrides: HostOverrides = {};
	// The trailing slash is trimmed by configureHost, for every host alike.
	if (dataUrl !== undefined) overrides.dataUrl = dataUrl;
	if (locale !== undefined) overrides.locale = () => locale;
	if (messages !== undefined) overrides.messages = messages;
	configureHost(overrides);

	const map = new MapController(controller);
	map.mount(container);
	if (map.webglError) {
		map.unmount();
		throw new Error('spacemap: WebGL is not available');
	}
	for (const [event, listener] of Object.entries(events ?? {})) {
		map.on(event as keyof MapEvents, listener as MapEvents[keyof MapEvents]);
	}
	map.addControl((element) => mountAttribution(map, element));
	await map.open();
	map.applyInitialView();
	await atmosphereBootSettled();
	return map;
}

export interface FlatMapCreateOptions extends FlatMapOptions {
	/** Root of the data export; the production CDN when omitted. Page-wide, as
	 *  on {@link createMap} — the last map created sets it. */
	dataUrl?: string;
	/** BCP-47 tag that picks localized names; English when omitted. */
	locale?: string;
	/** Replaces the English wording the map renders itself, one key at a time. */
	messages?: Partial<CoreMessages>;
	/** Listeners attached before the first load, so a slow or failed load is
	 *  observable while it runs. Later ones go through {@link FlatMap.on}. */
	events?: { [K in keyof FlatMapEvents]?: FlatMapEvents[K] };
}

/** Mount a flat map of one body's surface in `container` and resolve once its
 *  first picture is loaded. Rejects when the body has no map texture or the
 *  data does not load. */
export async function createFlatMap(
	container: HTMLElement,
	options: FlatMapCreateOptions = {}
): Promise<FlatMap> {
	const { dataUrl, locale, messages, events, ...flat } = options;
	const overrides: HostOverrides = {};
	if (dataUrl !== undefined) overrides.dataUrl = dataUrl;
	if (locale !== undefined) overrides.locale = () => locale;
	if (messages !== undefined) overrides.messages = messages;
	configureHost(overrides);

	const map = new FlatMap(flat);
	map.mount(container);
	for (const [event, listener] of Object.entries(events ?? {})) {
		map.on(event as keyof FlatMapEvents, listener as FlatMapEvents[keyof FlatMapEvents]);
	}
	map.addControl((root) => mountFlatAttribution(map, root));
	await map.load();
	return map;
}

export { configureHost, MapController, FlatMap, defaultSceneSettings, dateToJD, jdToDate };
export type {
	ClockState,
	FeatureSelect,
	FocusChange,
	MapControllerOptions,
	MapEvents
} from '$lib/scene/map-controller.svelte';
export type { CameraView, InitialView } from '$lib/scene/types';
export type { Anchor, InertialAnchor, OffsetKm, SurfaceAnchor } from '$lib/scene/extensions/anchor';
export type { Marker, MarkerOptions } from '$lib/scene/extensions/marker';
export type { CameraHold, CameraPose } from '$lib/scene/extensions/camera';
export type { Polyline, PolylineOptions } from '$lib/scene/extensions/polyline';
export type { SceneSettings } from '$lib/scene/settings.svelte';
export type {
	CoverageEdge,
	CoveragePauseNotice,
	Notice,
	NoticeTopic,
	OutOfRangeNotice
} from '$lib/scene/notice';
export type { FlatMapEvents, FlatMapOptions, FlatViewState } from '$lib/flatmap/flat-map';
export type { Extent, Projection, ProjectionId, ProjectionOptions } from '$lib/flatmap/projection';
export { createProjection, PROJECTION_IDS, projectionAspect } from '$lib/flatmap/projection';
export type { Interpolation, LonLat } from '$lib/flatmap/geometry';
export { boxRing, graticule, pathFor, smallCircle } from '$lib/flatmap/geometry';
export { Viewport } from '$lib/flatmap/view';
export type { ViewState } from '$lib/flatmap/view';
export type { Layer, LayerCredit, LayerInfo, VectorLayer } from '$lib/flatmap/layers';
// The flat map's shapes are named apart from the scene's: a host can hold both
// maps on one page, and `Marker` there is an element pinned in three
// dimensions, not a dot on a surface.
export type {
	BoxOptions,
	CircleOptions,
	FlatMarker,
	FlatShape,
	MarkerOptions as FlatMarkerOptions,
	PolygonOptions as FlatPolygonOptions,
	PolylineOptions as FlatPolylineOptions,
	ShapeStyle
} from '$lib/flatmap/overlay';
export type { CoreMessages, Host, HostOverrides } from '$lib/host';
export type { PositionedBody } from '$lib/types/objects';
