/**
 * The map for pages outside spacemap.co, as one script.
 *
 * There are two of them. {@link createMap} puts the Solar System in a
 * container — bodies and spacecraft in three dimensions, over time.
 * {@link createFlatMap} puts one body's surface there instead, drawn flat in a
 * projection of the host's choosing, with layers it can switch and drawings of
 * its own on top. The classes, the host seam and the clock's date helpers are
 * exported for hosts that drive them directly.
 *
 * Distances are kilometres and angles are degrees throughout.
 */

import { configureHost, type CoreMessages, type HostOverrides } from '$lib/host';
import type { Control } from '$lib/scene/controls';
import { SpaceMap, type SpaceMapOptions, type MapEvents } from '$lib/scene/space-map.svelte';
import { atmosphereBootSettled } from '$lib/scene/perf/atmosphere-calibration';
import { defaultSceneSettings } from '$lib/scene/settings.svelte';
import { dateToJD, jdToDate } from '$lib/time/jd';
import { FlatMap, type FlatMapEvents, type FlatMapOptions } from '$lib/flatmap/flat-map';
import { AttributionControl } from './controls/attribution.svelte';
import { FlatAttributionControl } from './controls/flat-attribution';

/** What both maps take: where to put it, where its data comes from, and what
 *  language to read it in. */
interface CommonOptions {
	/** The element to build the map in, or a selector that finds one. */
	container: HTMLElement | string;
	/** Root of the data export; the production CDN when omitted. Page-wide,
	 *  like everything on the host: the last map created sets it, and data
	 *  already fetched keeps the origin it came from. */
	dataUrl?: string;
	/** Root of the image export. Its own origin in production, since the data
	 *  origin does not serve pictures; a mirror that serves both sets this to
	 *  the same place as `dataUrl`. */
	imagesUrl?: string;
	/** BCP-47 tag that picks localized names; English when omitted. */
	locale?: string;
	/** Replaces the English wording the map renders itself, one key at a time. */
	messages?: Partial<CoreMessages>;
}

export interface MapOptions extends CommonOptions, SpaceMapOptions {
	/** Controls to hang on the map, each in the corner it asks for. The credit
	 *  line is always there and is not one of them. */
	controls?: Control<SpaceMap>[];
	/** Listeners attached before the first load, so the boot's `progress`,
	 *  `loading` and `error` events are observable while it runs. Later ones go
	 *  through {@link SpaceMap.on}. */
	events?: { [K in keyof MapEvents]?: MapEvents[K] };
}

export interface FlatMapCreateOptions extends CommonOptions, FlatMapOptions {
	controls?: Control<FlatMap>[];
	/** Listeners attached before the first load, so a slow or failed load is
	 *  observable while it runs. Later ones go through {@link FlatMap.on}. */
	events?: { [K in keyof FlatMapEvents]?: FlatMapEvents[K] };
}

/** Mount a map and resolve once it is worth looking at: the opening body
 *  placed, and the one-off quality benchmark done — that measures the GPU, so
 *  it must not run while the reader is already moving the camera. The small
 *  bodies go on streaming in behind the map this returns.
 *
 *  Rejects when WebGL is unavailable, or when the data fails before there is
 *  anything to look at; a failure past that point arrives as an `error` event. */
export async function createMap(options: MapOptions): Promise<SpaceMap> {
	const { container, dataUrl, imagesUrl, locale, messages, controls, events, ...rest } = options;
	const element = resolveContainer(container);
	applyHost({ dataUrl, imagesUrl, locale, messages });

	const map = new SpaceMap(rest);
	map.mount(element);
	if (map.webglError) {
		map.unmount();
		throw new Error('spacemap: WebGL is not available');
	}
	for (const [event, listener] of Object.entries(events ?? {})) {
		map.on(event as keyof MapEvents, listener as MapEvents[keyof MapEvents]);
	}
	map.attribution = new AttributionControl();
	map.addControl(map.attribution);
	for (const control of controls ?? []) map.addControl(control);
	await map.open();
	map.applyInitialView();
	await atmosphereBootSettled();
	return map;
}

/** Mount a flat map of one body's surface and resolve once its first picture
 *  is loaded. Rejects when the body has no map texture or the data does not
 *  load. */
export async function createFlatMap(options: FlatMapCreateOptions): Promise<FlatMap> {
	const { container, dataUrl, imagesUrl, locale, messages, controls, events, ...rest } = options;
	const element = resolveContainer(container);
	applyHost({ dataUrl, imagesUrl, locale, messages });

	const map = new FlatMap(rest);
	map.mount(element);
	for (const [event, listener] of Object.entries(events ?? {})) {
		map.on(event as keyof FlatMapEvents, listener as FlatMapEvents[keyof FlatMapEvents]);
	}
	map.attribution = new FlatAttributionControl();
	map.addControl(map.attribution);
	for (const control of controls ?? []) map.addControl(control);
	await map.load();
	return map;
}

function resolveContainer(container: HTMLElement | string): HTMLElement {
	if (typeof container !== 'string') return container;
	const element = document.querySelector(container);
	if (!(element instanceof HTMLElement))
		throw new Error(`spacemap: no element matches ${container}`);
	return element;
}

/** What a map leaves out goes back to its default, so a second map on the page
 *  does not inherit the first one's origins. */
function applyHost(options: Pick<CommonOptions, 'dataUrl' | 'imagesUrl' | 'locale' | 'messages'>) {
	const overrides: HostOverrides = {};
	// The trailing slash is trimmed by configureHost, for every host alike.
	if (options.dataUrl !== undefined) overrides.dataUrl = options.dataUrl;
	if (options.imagesUrl !== undefined) overrides.imagesUrl = options.imagesUrl;
	if (options.locale !== undefined) overrides.locale = () => options.locale as string;
	if (options.messages !== undefined) overrides.messages = options.messages;
	configureHost(overrides);
}

export {
	AttributionControl,
	configureHost,
	dateToJD,
	defaultSceneSettings,
	FlatAttributionControl,
	FlatMap,
	jdToDate,
	SpaceMap
};

// -- the Solar System map -----------------------------------------------------
export type {
	CameraLimits,
	CameraOptions,
	CameraState,
	CameraTarget,
	ClockState,
	FeatureRef,
	FeatureSelect,
	FeatureTarget,
	FocusChange,
	JumpTarget,
	MapEvents,
	MapGesture,
	SpaceMapOptions
} from '$lib/scene/space-map.svelte';
export { GestureHandler } from '$lib/interaction/gesture';
export type { Body, BodyType, OrbitClass } from '$lib/scene/body-view';
export type { SimClock } from '$lib/scene/state/clock.svelte';
export type { Control, ControlPosition } from '$lib/scene/controls';
export type { SceneSettings } from '$lib/scene/settings.svelte';
export type { Anchor, InertialAnchor, OffsetKm, SurfaceAnchor } from '$lib/scene/extensions/anchor';
export type { Marker, MarkerOptions } from '$lib/scene/extensions/marker';
export type { CameraHold, CameraPose } from '$lib/scene/extensions/camera';
export type { Polyline, PolylineOptions } from '$lib/scene/extensions/polyline';
export type {
	CoverageEdge,
	CoveragePauseNotice,
	Notice,
	NoticeTopic,
	OutOfRangeNotice
} from '$lib/scene/notice';

// -- the flat map -------------------------------------------------------------
export type {
	FlatMapEvents,
	FlatMapGesture,
	FlatMapOptions,
	FlatViewState
} from '$lib/flatmap/flat-map';
export type { Extent, Projection, ProjectionId, ProjectionOptions } from '$lib/flatmap/projection';
export { createProjection, PROJECTION_IDS, projectionAspect } from '$lib/flatmap/projection';
export type { Interpolation, LonLat } from '$lib/flatmap/geometry';
export { boxRing, graticule, pathFor, smallCircle } from '$lib/flatmap/geometry';
export { Viewport } from '$lib/flatmap/view';
export type { FlatMapLimits, ViewState } from '$lib/flatmap/view';
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

// -- the host seam ------------------------------------------------------------
export type { CoreMessages, Host, HostOverrides } from '$lib/host';
