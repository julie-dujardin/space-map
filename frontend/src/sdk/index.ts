/**
 * The map for pages outside spacemap.co, as one script. {@link createMap} puts
 * a MapController in a container; the class, the host seam and the clock's
 * date helpers are exported for hosts that drive them directly.
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
import { mountAttribution } from './controls/attribution.svelte';

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
	await atmosphereBootSettled();
	return map;
}

export { configureHost, MapController, defaultSceneSettings, dateToJD, jdToDate };
export type {
	ClockState,
	FeatureSelect,
	FocusChange,
	MapControllerOptions,
	MapEvents
} from '$lib/scene/map-controller.svelte';
export type { CameraView, InitialView } from '$lib/scene/types';
export type { SceneSettings } from '$lib/scene/settings.svelte';
export type {
	CoverageEdge,
	CoveragePauseNotice,
	Notice,
	NoticeTopic,
	OutOfRangeNotice
} from '$lib/scene/notice';
export type { CoreMessages, Host, HostOverrides } from '$lib/host';
export type { PositionedBody } from '$lib/types/objects';
