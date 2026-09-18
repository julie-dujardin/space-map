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
	cooperative_wheel: () => string;
	cooperative_wheel_mac: () => string;
	cooperative_touch: () => string;
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
	/** How far down the `distribution` ladder this embed may draw surface maps
	 *  (docs/export-format/textures.md). `open` is the maps anyone may serve,
	 *  `non-commercial` adds those whose licence bars commercial reuse, and
	 *  `site-only` adds those cleared for spacemap.co alone. A bare embed gets
	 *  `open`: it cannot accept a licence for the page it sits on. */
	textures: TextureDistribution;
}

/** Who may serve a surface map, widest first. A body whose map this embed may
 *  not draw renders in its fallback colour, as an untextured body does. */
export type TextureDistribution = 'open' | 'non-commercial' | 'site-only';

const TEXTURE_LADDER: readonly TextureDistribution[] = ['open', 'non-commercial', 'site-only'];

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
		layer_nomenclature: () => 'Named features',
		cooperative_wheel: () => 'Use ctrl + scroll to zoom the map',
		cooperative_wheel_mac: () => 'Use ⌘ + scroll to zoom the map',
		cooperative_touch: () => 'Use two fingers to move the map'
	},
	// A bare embed has no pages to link to, so labels stay put.
	bodyHref: () => '',
	textures: 'open'
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

/**
 * Whether this embed may fetch a surface map whose block carries that
 * `distribution`. Absent is the common case and always allowed; a tier this
 * build doesn't know is newer than the build, so it is refused rather than
 * guessed at.
 */
export function textureAllowed(distribution: string | undefined): boolean {
	if (distribution === undefined) return true;
	const rank = TEXTURE_LADDER.indexOf(distribution as TextureDistribution);
	if (rank < 0) return false;
	return rank <= TEXTURE_LADDER.indexOf(current.textures);
}

/**
 * The best map of a body this embed may actually draw.
 *
 * The export ranks them by how good the picture is, best first, and says of
 * each who may serve it. Those are separate judgements, so an embed barred
 * from the best one walks down the list rather than going without: the reader
 * gets the second-best map instead of a flat sphere. Undefined when every
 * candidate is out of reach.
 */
export function pickTexture<T extends { distribution?: string }>(
	candidates: readonly (T | undefined)[]
): T | undefined {
	for (const candidate of candidates) {
		if (candidate && textureAllowed(candidate.distribution)) return candidate;
	}
	return undefined;
}

/** The host's reading language; the hot path in name picks and formatters. */
export function getLocale(): string {
	return current.locale();
}
