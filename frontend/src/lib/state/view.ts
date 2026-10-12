import {
	DEFAULT_FOCUS_ID,
	DEFAULT_FRAMING_LAT,
	DEFAULT_FRAMING_LON,
	DEFAULT_ZOOM
} from '$lib/scene/framing';
import { DEFAULT_TRIP, type TripState } from '$lib/travel/trip';

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

/** Map URL type segment to backend ID prefix. Inverse of urlTypeFromId. */
export function urlTypeToIdPrefix(urlType: string): string {
	if (urlType === UrlType.SmallBody) return 'spkid';
	if (urlType === UrlType.EarthSatellite) return 'norad_satcat';
	if (urlType === UrlType.Probe) return 'probe';
	if (urlType === UrlType.Extra) return 'extra';
	return 'naif'; // UrlType.Body
}

/** Derive URL type segment from a body ID. Use this for URL generation — it's
 *  always consistent with the ID. Lives here rather than beside the rest of the
 *  URL codec so route loads and SSR can reach it: `url.ts` pulls in client-only
 *  `$app/state`. */
export function urlTypeFromId(id: string): UrlType {
	if (id.startsWith('spkid-')) return UrlType.SmallBody;
	if (id.startsWith('norad_satcat-')) return UrlType.EarthSatellite;
	if (id.startsWith('probe-')) return UrlType.Probe;
	if (id.startsWith('extra-')) return UrlType.Extra;
	return UrlType.Body; // naif-
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

/** The number of an id as a URL writes it: digits, with a minus for a NAIF
 *  spacecraft code, no padding, no exponent. `Number()` reads `1e2`, `0x10`
 *  and the empty string too, and each would be one more address for the same
 *  page. */
const ID_NUMBER = /^-?(0|[1-9]\d*)$/;

export function isIdNumber(segment: string): boolean {
	return ID_NUMBER.test(segment);
}

/**
 * The object a body route names (`/b/399` is `naif-399`), or null when its
 * segments name none. The one reading of the pair: the route load answers 404
 * on null, and the page takes its view from the same id.
 */
export function objectIdOfRoute(type: string, id: string): string | null {
	if (!FEATURE_ROUTE_TYPES.has(type) || !isIdNumber(id)) return null;
	return `${urlTypeToIdPrefix(type)}-${id}`;
}

/** The IAU feature id a feature route names, or null. */
export function featureIdOfRoute(segment: string): number | null {
	return isIdNumber(segment) && !segment.startsWith('-') ? Number(segment) : null;
}

/** Every detail-drawer tab, in the order the drawer's bar lists them;
 *  'overview' is the null default in URL state. The one list the tab type and
 *  the URL codec both derive from. */
export const DRAWER_TABS = [
	'overview',
	'targets',
	'traverse',
	'images',
	'features',
	'structure',
	'rings',
	'members',
	'fragments',
	'probes'
] as const;

export type DrawerTab = (typeof DRAWER_TABS)[number];

/**
 * Shape of the URL-backed app state. One source of truth for what gets shared,
 * bookmarked, restored on reload, and pushed onto the browser history stack.
 */
export interface MapViewState {
	type: string;
	id: string; // prefixed body id, e.g. "naif-10", "spkid-20134340" — the renderer always focuses a body, even in feature/group mode
	/** Name of the subject (the body, the feature or the group) as the export
	 *  gives it; empty till it is known. Written to the URL and never read from
	 *  it: there it only tells a reader what a link opens. */
	name: string;
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
	/** Slug when /g/<slug> is active; filters the group's applies_to category.
	 *  `id` then holds the group's camera anchor, or the member the camera moved
	 *  to — deep-linked as `&focus=` so the link reopens on that member. */
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
	 *  a launch site, a landing site. Held apart from the body because that is
	 *  what the trajectory is priced against; the two travel as one path segment
	 *  (`naif-301-f-3537`, see formatNavEnd) because together they are one end.
	 *  A feature is always a surface endpoint, so it carries no mode. */
	navFromFeature: number | null;
	navToFeature: number | null;
	/** Where an end stands when it stands on a bare point rather than on
	 *  something named — a launch pad, which no gazetteer lists. Coordinates are
	 *  the whole of it; `siteSlug` only says which collection they were taken
	 *  from, for naming them and for offering the pads beside them. */
	navFromPlace: NavPlace | null;
	navToPlace: NavPlace | null;
	/** What the trip asks for beyond its two ends — how it meets each one, when
	 *  it goes, what flies it, what it carries, which trajectory is being read.
	 *  Its own codec; see `$lib/travel/trip`. DEFAULT_TRIP off `/nav`. */
	trip: TripState;
}

/** A point on a body's surface, as a trip end names one. */
export interface NavPlace {
	latDeg: number;
	lonDeg: number;
	/**
	 * The launch-site collection the point was taken from, and which of its pads
	 * it is, when it was taken from one.
	 *
	 * Provenance rather than identity: the coordinates alone fly the trip, and
	 * these only say which page's pads to name them from and to offer as the
	 * ones next door. Losing them costs the label, nothing else.
	 */
	siteSlug?: string | null;
	padCode?: string | null;
}

export const DEFAULT_VIEW: MapViewState = {
	type: UrlType.Body,
	id: DEFAULT_FOCUS_ID,
	// Empty until the body resolves its localized name (replaceFocusName) — a
	// hardcoded "Earth" would flash the wrong language for non-English locales.
	name: '',
	date: new Date(),
	isNow: true,
	// Serialized fallback only — the landing snap places the camera sunward and writes lat/lon back.
	latitude: DEFAULT_FRAMING_LAT,
	longitude: DEFAULT_FRAMING_LON,
	zoom: DEFAULT_ZOOM,
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
	navToFeature: null,
	navFromPlace: null,
	navToPlace: null,
	trip: DEFAULT_TRIP
};
