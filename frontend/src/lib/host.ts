/**
 * What the core (scene, math, fetch) needs from whoever embeds it — the
 * SvelteKit app today, the SDK later. Read lazily through {@link host} so the
 * host can configure it at boot without import-order games; the defaults are
 * what a bare embed gets.
 */

/** Scene text the core renders itself; everything else is the host's to format.
 *  Spelled out rather than typed off the app's message bundle, which would
 *  put every message of the app into the SDK's types. */
export interface CoreMessages {
	body_note_no_model: () => string;
	body_note_no_radius: () => string;
	carried_by_scene_label: (inputs: { carrier: string }) => string;
	scene_canvas_label: () => string;
}

/** A coverage edge the clock has crossed, and where it lies. */
export interface CoverageEdge {
	side: 'before' | 'after';
	jd: number;
}

/** Which groups lack data at the current time. */
export interface OutOfRangeNotice {
	topic: 'out-of-range';
	focusedOutOfRange: boolean;
	/** Zone-level satellite coverage: past the archive, or inside a hole. */
	satellites: { side: 'after'; jd: number } | { side: 'gap' } | null;
	majorBodies: CoverageEdge | { side: 'outside' } | null;
}

/** The clock stopped at the focused probe's trajectory data wall. */
export interface CoveragePauseNotice {
	topic: 'coverage-pause';
	name: string;
	direction: 'forward' | 'backward';
	jd: number;
}

export type Notice = OutOfRangeNotice | CoveragePauseNotice;
export type NoticeTopic = Notice['topic'];

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
	/** Show a sticky notice; one per topic, a repeat replaces the previous. */
	notify: (notice: Notice) => void;
	dismiss: (topic: NoticeTopic) => void;
}

const DEFAULT_HOST: Host = {
	dataUrl: 'https://static.spacemap.co',
	imagesUrl: 'https://images.spacemap.co',
	locale: () => 'en',
	messages: {
		body_note_no_model: () => 'no model available',
		body_note_no_radius: () => 'no size data available',
		carried_by_scene_label: ({ carrier }) => `Carried by ${carrier}`,
		scene_canvas_label: () => 'Interactive 3D map of the Solar System'
	},
	// A bare embed has no pages to link to, so labels stay put.
	bodyHref: () => '',
	notify: () => {},
	dismiss: () => {}
};

let current: Host = DEFAULT_HOST;

/** Replace the host: what an override leaves out goes back to its default,
 *  so a second embed on the page does not inherit the first one's settings. */
export function configureHost(overrides: Partial<Host>): void {
	current = { ...DEFAULT_HOST, ...overrides };
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
