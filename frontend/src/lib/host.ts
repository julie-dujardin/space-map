/**
 * What the core (scene, math, fetch) needs from whoever embeds it — the
 * SvelteKit app today, the SDK later. Read lazily through {@link host} so the
 * host can configure it at boot without import-order games; the defaults are
 * what a bare embed gets. Conditions the scene reports back travel the other
 * way, as map events.
 */

/** Scene text the core renders itself; everything else is the host's to format.
 *  Spelled out rather than typed off the app's message bundle, which would
 *  put every message of the app into the SDK's types. */
export interface CoreMessages {
	body_note_no_model: () => string;
	body_note_no_radius: () => string;
	carried_by_scene_label: (inputs: { carrier: string }) => string;
	scene_canvas_label: () => string;
	attribution_orbits: () => string;
	attribution_imagery: () => string;
	credits_see_all: () => string;
	layer_surface: () => string;
	layer_clouds: () => string;
	layer_night: () => string;
	layer_graticule: () => string;
	layer_nomenclature: () => string;
}

export interface Host {
	/** Root of the data export; versioned files hang off it. */
	dataUrl: string;
	/** Root of the image export, on its own origin in production. */
	imagesUrl: string;
	/** BCP-47 tag of the reading language: picks localized names and drives Intl. */
	locale: () => string;
	messages: CoreMessages;
	/** Link target of a body's scene label. */
	bodyHref: (id: string, name: string) => string;
}

/** Overrides, with messages filled in one key at a time. */
export type HostOverrides = Partial<Omit<Host, 'messages'>> & { messages?: Partial<CoreMessages> };

const DEFAULT_HOST: Host = {
	dataUrl: 'https://static.spacemap.co',
	imagesUrl: 'https://images.spacemap.co',
	locale: () => 'en',
	messages: {
		body_note_no_model: () => 'no model available',
		body_note_no_radius: () => 'no size data available',
		carried_by_scene_label: ({ carrier }) => `Carried by ${carrier}`,
		scene_canvas_label: () => 'Interactive 3D map of the Solar System',
		attribution_orbits: () => 'Orbits',
		attribution_imagery: () => 'Imagery',
		credits_see_all: () => 'See full credits',
		layer_surface: () => 'Surface',
		layer_clouds: () => 'Clouds',
		layer_night: () => 'Night lights',
		layer_graticule: () => 'Grid',
		layer_nomenclature: () => 'Named features'
	},
	// A bare embed has no pages to link to, so labels stay put.
	bodyHref: () => ''
};

let current: Host = DEFAULT_HOST;

/** Replace the host: what an override leaves out goes back to its default, so
 *  a second embed on the page does not inherit the first one's settings.
 *  Messages are the one thing filled in key by key — an override names the few
 *  it wants reworded and the rest stay English. */
export function configureHost(overrides: HostOverrides): void {
	const { messages, ...rest } = overrides;
	current = { ...DEFAULT_HOST, ...rest };
	if (messages) current.messages = { ...DEFAULT_HOST.messages, ...messages };
	// A URL root is concatenated with paths that lead with a slash.
	current.dataUrl = current.dataUrl.replace(/\/$/, '');
	current.imagesUrl = current.imagesUrl.replace(/\/$/, '');
}

export function host(): Host {
	return current;
}

/** The host's reading language; the hot path in name picks and formatters. */
export function getLocale(): string {
	return current.locale();
}
