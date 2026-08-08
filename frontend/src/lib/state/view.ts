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
	Extra = 'u', // /u/<id>/<name> — hand-authored extra object addressed by its id
	Nav = 'nav' // /nav/<fromId>/<toId> — trajectory planner between two bodies
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

/** Every detail-drawer tab, in the order the drawer's bar lists them;
 *  'overview' is the null default in URL state. The one list the tab type and
 *  the URL codec both derive from. */
export const DRAWER_TABS = [
	'overview',
	'images',
	'features',
	'structure',
	'rings',
	'members',
	'fragments'
] as const;

export type DrawerTab = (typeof DRAWER_TABS)[number];

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
	/** 0-based index into the active gallery's images; null when the viewer is
	 *  closed. Which gallery that is comes from `gallery`. */
	imageIndex: number | null;
	/** Image gallery opened under the Images tab; null = the shelf index.
	 *  Deep-linked as `&gal=`, and what `imageIndex` counts into. */
	gallery: string | null;
	/** IAU feature id when a surface feature is the active selection; null otherwise. */
	featureId: number | null;
	/** Slug when /g/<slug> is active; filters the group's applies_to category. */
	groupSlug: string | null;
	/** Active drawer tab; null = overview. Deep-linked as `&tab=`. */
	tab: Exclude<DrawerTab, 'overview'> | null;
	/** Pages loaded in a paginated list; null = first. Deep-linked as `&mp=` to
	 *  restore scroll depth. Only meaningful under the members/features tabs. */
	memberPage: number | null;
	/** IAU quadrangle selected on the Surface tab; null = the whole body.
	 *  Deep-linked as `&quad=` so a feature's Quadrangle row can target it. */
	quad: string | null;
	/** IAU feature-type code narrowing the Surface tab's list; null = all. */
	featureType: string | null;
	/** Ring feature the Rings tab is drilled into; null = the whole system.
	 *  Deep-linked as `&ring=`. The chart's clustered rows have no slug of
	 *  their own, so a path ending in one shares as its enclosing feature. */
	ring: string | null;
	/** Ends of the trip on `/nav`; null everywhere else. Both carry their full
	 *  prefixed id, since a trip can join two different id spaces (a probe to a
	 *  small body) and the path has no type segment to disambiguate them.
	 *
	 *  Either is null when that end has not been chosen, the way either box of a
	 *  directions form can be empty: bare `/nav` opens from Earth with nowhere to
	 *  go, and a body's own planner opens with it as the destination. `id`
	 *  mirrors the destination when there is one, so the camera frames where you
	 *  are going. */
	navFrom: string | null;
	navTo: string | null;
	/** IAU feature id when an end is a named place on its body's surface —
	 *  a launch site, a landing site. Deep-linked as `&ff=` / `&tf=`; the body
	 *  stays in the path because that is what the trajectory is priced against.
	 *  A feature is always a surface endpoint, so it carries no mode. */
	navFromFeature: number | null;
	navToFeature: number | null;
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
	gallery: null,
	featureId: null,
	groupSlug: null,
	tab: null,
	memberPage: null,
	quad: null,
	featureType: null,
	ring: null,
	navFrom: null,
	navTo: null,
	navFromFeature: null,
	navToFeature: null
};
