/**
 * The map for pages outside spacemap.co, as one script. {@link createMap} puts
 * a MapController in a container; the class, the host seam and the clock's
 * date helpers are exported for hosts that drive them directly.
 */

import { configureHost, type Host } from '$lib/host';
import { MapController, type MapControllerOptions } from '$lib/scene/map-controller.svelte';
import { defaultSceneSettings } from '$lib/scene/settings.svelte';
import { dateToJD, jdToDate } from '$lib/time/jd';

export interface MapOptions extends MapControllerOptions {
	/** Root of the data export; the production CDN when omitted. Page-wide,
	 *  like everything on the host: the last map created sets it, and data
	 *  already fetched keeps the origin it came from. Images keep their own
	 *  origin, since the production data origin does not serve them; a mirror
	 *  that serves both sets `imagesUrl` through {@link configureHost}. */
	dataUrl?: string;
	/** BCP-47 tag that picks localized names; English when omitted. */
	locale?: string;
}

/** Mount a map in `container` and resolve once its initial body is loaded.
 *  Rejects when WebGL is unavailable or the data does not load. */
export async function createMap(
	container: HTMLElement,
	options: MapOptions = {}
): Promise<MapController> {
	const { dataUrl, locale, ...controller } = options;
	const overrides: Partial<Host> = {};
	if (dataUrl !== undefined) overrides.dataUrl = dataUrl;
	if (locale !== undefined) overrides.locale = () => locale;
	configureHost(overrides);

	const map = new MapController(controller);
	map.mount(container);
	if (map.webglError) {
		map.unmount();
		throw new Error('spacemap: WebGL is not available');
	}
	await map.load();
	return map;
}

export { configureHost, MapController, defaultSceneSettings, dateToJD, jdToDate };
export type {
	FeatureSelect,
	FocusChange,
	MapControllerOptions,
	MapEvents
} from '$lib/scene/map-controller.svelte';
export type { CameraView, InitialView } from '$lib/scene/types';
export type { SceneSettings } from '$lib/scene/settings.svelte';
export type {
	CoreMessages,
	CoverageEdge,
	CoveragePauseNotice,
	Host,
	Notice,
	NoticeTopic,
	OutOfRangeNotice
} from '$lib/host';
export type { PositionedBody } from '$lib/types/objects';
