import { EARTH_ID } from '$lib/constants';

/** URL path discriminator. Body types map 1:1 to ID prefix; Feature is a
 *  sub-selection on top of a body and uses a nested route shape
 *  (/<type>/<bodyId>/f/<featureId>/<name>). Group is a top-level aggregation
 *  view (/g/<slug>/<name>) that filters which bodies render but keeps a
 *  default anchor body for camera framing. */
export enum UrlType {
	Body = 'b', // naif-
	SmallBody = 's', // spkid-
	EarthSatellite = 'e', // norad_satcat-
	Probe = 'p', // probe-
	Feature = 'f', // IAU nomenclature feature on a body
	Group = 'g', // /g/<slug>/<name> — constellation / operator / asteroid class / ...
	Extra = 'u' // /u/<id>/<name> — hand-authored extra object addressed by its id
}

/** Type segments valid on the body/group route `/[type]/[id]/[[name]]`; anything
 *  else 404s instead of coercing to a `naif-` body. Feature ('f') is nested. */
export const BODY_ROUTE_TYPES: ReadonlySet<string> = new Set([
	UrlType.Body,
	UrlType.SmallBody,
	UrlType.EarthSatellite,
	UrlType.Probe,
	UrlType.Extra,
	UrlType.Group
]);

/** Type segments valid on the feature route `/[type]/[id]/f/[featureId]/[[name]]`
 *  — body types only; groups have no features. */
export const FEATURE_ROUTE_TYPES: ReadonlySet<string> = new Set([
	UrlType.Body,
	UrlType.SmallBody,
	UrlType.EarthSatellite,
	UrlType.Probe,
	UrlType.Extra
]);

/** Detail-drawer tab; 'overview' is the null default in URL state. */
export type DrawerTab = 'overview' | 'images' | 'members' | 'features' | 'fragments';

/**
 * Shape of the URL-backed app state. One source of truth for what gets shared,
 * bookmarked, restored on reload, and pushed onto the browser history stack.
 */
export interface MapViewState {
	type: string;
	id: string; // prefixed body id, e.g. "naif-10", "spkid-20134340" — the renderer always focuses a body, even in feature/group mode
	name: string; // active object's display name (body in body mode, feature in feature mode, group in group mode)
	date: Date;
	isNow: boolean;
	latitude: number;
	longitude: number;
	zoom: number;
	/** Camera framing (lat/lon/zoom) was explicit — an `?at=` block or group
	 *  anchor. Absent for a bare deep link, which frames by target size/model. */
	framed?: boolean;
	/** 0-based index into the focused object's images; null when the viewer is closed. */
	imageIndex: number | null;
	/** IAU feature id when a surface feature is the active selection; null otherwise. */
	featureId: number | null;
	/** Slug when /g/<slug> is active; filters the group's applies_to category. */
	groupSlug: string | null;
	/** Active drawer tab; null = overview. Deep-linked as `&tab=`. */
	tab: Exclude<DrawerTab, 'overview'> | null;
	/** Pages loaded in a paginated list; null = first. Deep-linked as `&mp=` to
	 *  restore scroll depth. Only meaningful under the members/features tabs. */
	memberPage: number | null;
}

/** Default vantage angle for a body framed with no explicit camera (search, click, group). */
export const DEFAULT_FRAMING_LAT = 45;
export const DEFAULT_FRAMING_LON = 0;
/** Wide heliocentric framing for Sun-anchored group pages. */
export const SUN_VIEW_ZOOM = 42.43;
/** Landing-view tilt above the ecliptic, looking sunward from Earth. */
export const DEFAULT_VIEW_ELEVATION_DEG = 30;

export const DEFAULT_VIEW: MapViewState = {
	type: UrlType.Body,
	id: EARTH_ID,
	// Empty until the body resolves its localized name (replaceFocusName) — a
	// hardcoded "Earth" would flash the wrong language for non-English locales.
	name: '',
	date: new Date(),
	isNow: true,
	// Serialized fallback only — the landing snap places the camera sunward and writes lat/lon back.
	latitude: DEFAULT_FRAMING_LAT,
	longitude: DEFAULT_FRAMING_LON,
	zoom: 15, // ~1.5 AU from Earth
	imageIndex: null,
	featureId: null,
	groupSlug: null,
	tab: null,
	memberPage: null
};
