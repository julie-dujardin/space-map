import { resolve } from '$app/paths';
import { page } from '$app/state';
import {
	CATEGORY_SLUG_PREFIX,
	CAT_DEBRIS,
	CAT_SATELLITES,
	CLASS_SLUG_PREFIX,
	COMET_FAMILY_SLUG_PREFIX,
	FEATURE_TYPE_SLUG_PREFIX,
	SMALL_BODY_FLAG_SLUG_PREFIX
} from '$lib/fetch/groups/registry';
import { SAT_ORBIT_ZONES } from '$lib/charts/orbit-zones';
import { isLagrangeClass } from '$lib/math/orbit/lagrange';
import { DEFAULT_TRIP, parseTrip, serializeTripSuffix } from '$lib/travel/trip';
import { EARTH_ID, SUN_ID } from '$lib/constants';
import { formatNavEnd, isBodyId, NAV_UNSET, parseNavEnd } from './nav-end';
import {
	DEFAULT_VIEW,
	DRAWER_TABS,
	SUN_VIEW_ZOOM,
	UrlType,
	type DrawerTab,
	type MapViewState,
	type NavPlace
} from './view';

// The grammar of a trip end lives apart so the route's own guard, which runs
// where `$app/state` does not, can share it.
export { formatNavEnd, isBodyId, NAV_UNSET, parseNavEnd };

/** Tabs that serialize a `&tab=` block; overview is the null default. */
const DEEP_LINK_TABS: readonly string[] = DRAWER_TABS.filter((t) => t !== 'overview');

function parseTab(raw: string | null): Exclude<DrawerTab, 'overview'> | null {
	return raw && DEEP_LINK_TABS.includes(raw) ? (raw as Exclude<DrawerTab, 'overview'>) : null;
}

/** Page 1 is implicit, so only integers > 1 carry meaning. */
function parseMemberPage(raw: string | null): number | null {
	if (!raw) return null;
	const n = Number(raw);
	return Number.isInteger(n) && n > 1 ? n : null;
}

/** Parse a legacy `&ff=`/`&tf=` IAU feature id; null for anything that isn't
 *  one. Superseded by the trip end's own id — see formatNavEnd. */
function parseFeatureId(raw: string | null): number | null {
	if (!raw) return null;
	const n = Number(raw);
	return Number.isInteger(n) && n > 0 ? n : null;
}

/** Parse the `&img=` gallery index; null (viewer closed) for anything invalid. */
function parseImageIndex(raw: string | null): number | null {
	if (!raw) return null;
	const n = Number(raw);
	return Number.isInteger(n) && n >= 0 ? n : null;
}

/** Map URL type segment to backend ID prefix. Inverse of urlTypeFromId. */
export function urlTypeToIdPrefix(urlType: string): string {
	if (urlType === UrlType.SmallBody) return 'spkid';
	if (urlType === UrlType.EarthSatellite) return 'norad_satcat';
	if (urlType === UrlType.Probe) return 'probe';
	if (urlType === UrlType.Extra) return 'extra';
	return 'naif'; // UrlType.Body
}

/** Derive URL type segment from a body ID. Use this for URL generation — it's always consistent with the ID. */
export function urlTypeFromId(id: string): UrlType {
	if (id.startsWith('spkid-')) return UrlType.SmallBody;
	if (id.startsWith('norad_satcat-')) return UrlType.EarthSatellite;
	if (id.startsWith('probe-')) return UrlType.Probe;
	if (id.startsWith('extra-')) return UrlType.Extra;
	return UrlType.Body; // naif-
}

/** Earth-system zoom — mirrors MapPage's minimize-from-sat distance. */
const EARTH_GROUP_ZOOM = 0.005;
/** Wide Earth framing for Sun–Earth L-point pages (~3 M km out; the points sit
 *  ~1.5 M km away). */
const LAGRANGE_GROUP_ZOOM = 0.3;
/** Solar-system framing for small-body (orbit-class) groups. */
const SUN_GROUP_ZOOM = SUN_VIEW_ZOOM;

/** Camera anchor + zoom for /g/<slug>. Small-body groups (orbit class + NEO/
 *  PHA designations) frame heliocentrically; every other category currently
 *  centers on Earth. */
export function groupAnchor(slug: string): { id: string; zoom: number } {
	if (slug.startsWith(CATEGORY_SLUG_PREFIX)) {
		// The two Earth-orbiter collections frame on Earth; the rest of the tree is
		// heliocentric.
		return slug === CAT_SATELLITES || slug === CAT_DEBRIS
			? { id: EARTH_ID, zoom: EARTH_GROUP_ZOOM }
			: { id: SUN_ID, zoom: SUN_GROUP_ZOOM };
	}
	if (slug.startsWith(CLASS_SLUG_PREFIX)) {
		// Sun–Earth L-points frame on Earth but zoomed way out; other earth-orbit
		// classes frame tight on Earth, small-body classes heliocentrically.
		const cls = slug.slice(CLASS_SLUG_PREFIX.length);
		if (isLagrangeClass(cls)) return { id: EARTH_ID, zoom: LAGRANGE_GROUP_ZOOM };
		return cls in SAT_ORBIT_ZONES
			? { id: EARTH_ID, zoom: EARTH_GROUP_ZOOM }
			: { id: SUN_ID, zoom: SUN_GROUP_ZOOM };
	}
	if (slug.startsWith(SMALL_BODY_FLAG_SLUG_PREFIX) || slug.startsWith(COMET_FAMILY_SLUG_PREFIX)) {
		return { id: SUN_ID, zoom: SUN_GROUP_ZOOM };
	}
	// Feature types span every body that carries them — frame the system, not
	// one host.
	if (slug.startsWith(FEATURE_TYPE_SLUG_PREFIX)) {
		return { id: SUN_ID, zoom: SUN_GROUP_ZOOM };
	}
	return { id: EARTH_ID, zoom: EARTH_GROUP_ZOOM };
}

/** The `&fs=`/`&fp=` block saying where a point was picked from, or nothing. */
function placeParams(role: 'f' | 't', place: NavPlace | null): string {
	if (!place?.siteSlug) return '';
	const pad = place.padCode ? `&${role}p=${encodeURIComponent(place.padCode)}` : '';
	return `&${role}s=${encodeURIComponent(place.siteSlug)}${pad}`;
}

/** A parsed point with its collection attached, or null when there is no point
 *  for one to belong to. */
function withSlug(
	place: NavPlace | null | undefined,
	slug: string | null,
	pad: string | null
): NavPlace | null {
	if (!place) return null;
	return slug ? { ...place, siteSlug: slug, padCode: pad } : place;
}

/** Parse current page state → MapViewState, or null */
export function parseUrl(): MapViewState | null {
	// /nav has no type segment of its own, and both its ends are optional, so it
	// is recognised by its route id rather than by which params happen to be set.
	if (page.route.id?.startsWith('/nav')) {
		const fromParam = page.params.from;
		const toParam = page.params.to;
		const fromRaw = fromParam === NAV_UNSET ? undefined : fromParam;
		const toRaw = toParam === NAV_UNSET ? undefined : toParam;
		const from = fromRaw === undefined ? undefined : parseNavEnd(fromRaw);
		const to = toRaw === undefined ? undefined : parseNavEnd(toRaw);
		if (from === null || to === null) {
			console.warn(`parseUrl: malformed nav ids (from=${fromRaw}, to=${toRaw})`);
			return null;
		}
		// A bare /nav is a blank form, and Earth is where its traffic leaves from;
		// an unset segment means the departure was cleared on purpose.
		const navFrom = fromParam === undefined ? EARTH_ID : (from?.bodyId ?? null);
		return applyAtParam({
			...DEFAULT_VIEW,
			type: UrlType.Nav,
			// The renderer always frames a body; on a trip that's where you're going,
			// and with nowhere to go yet, where you're setting out from.
			id: to?.bodyId ?? navFrom ?? EARTH_ID,
			name: '',
			navFrom,
			navTo: to?.bodyId ?? null,
			// A feature belongs to the end it was picked at; without that end there
			// is nothing for one to belong to. `ff`/`tf` are the superseded spelling,
			// still read so links shared before the ids merged keep their landing site.
			navFromFeature: from
				? (from.featureId ?? parseFeatureId(page.url.searchParams.get('ff')))
				: null,
			navToFeature: to ? (to.featureId ?? parseFeatureId(page.url.searchParams.get('tf'))) : null,
			// Where the point came from rides the query: the coordinates are the
			// end, and this only names them.
			navFromPlace: withSlug(
				from?.place,
				page.url.searchParams.get('fs'),
				page.url.searchParams.get('fp')
			),
			navToPlace: withSlug(
				to?.place,
				page.url.searchParams.get('ts'),
				page.url.searchParams.get('tp')
			),
			trip: parseTrip(page.url.searchParams)
		});
	}

	const type = page.params.type;
	const idStr = page.params.id;
	if (!type || !idStr) {
		console.warn(`parseUrl: missing route params (type=${type}, id=${idStr})`);
		return null;
	}

	// Groups ride the body route shape — [id] holds the slug, not a number.
	if (type === UrlType.Group) {
		const anchor = groupAnchor(idStr);
		const defaults: MapViewState = {
			...DEFAULT_VIEW,
			type: UrlType.Group,
			id: anchor.id,
			zoom: anchor.zoom,
			framed: true, // group anchor zoom is intentional framing, not a default
			name: decodeURIComponent(page.params.name ?? ''),
			groupSlug: idStr,
			imageIndex: parseImageIndex(page.url.searchParams.get('img')),
			gallery: page.url.searchParams.get('gal'),
			featureId: null,
			tab: parseTab(page.url.searchParams.get('tab')),
			memberPage: parseMemberPage(page.url.searchParams.get('mp')),
			quad: null,
			featureType: null,
			ring: null
		};
		return applyAtParam(defaults);
	}

	const numericId = Number(idStr);
	if (!Number.isFinite(numericId)) {
		console.warn(`parseUrl: non-numeric id param: ${idStr}`);
		return null;
	}
	const id = `${urlTypeToIdPrefix(type)}-${numericId}`;
	const name = decodeURIComponent(page.params.name ?? '');

	// Feature route /[type]/[id]/f/[featureId]/[[name]] surfaces featureId; the
	// body route /[type]/[id]/[[name]] does not. Discriminate on its presence.
	const featureIdStr = page.params.featureId;
	if (featureIdStr !== undefined) {
		const numericFeatureId = Number(featureIdStr);
		if (!Number.isFinite(numericFeatureId)) {
			console.warn(`parseUrl: non-numeric featureId param: ${featureIdStr}`);
			return null;
		}
		const defaults: MapViewState = {
			...DEFAULT_VIEW,
			type: UrlType.Feature,
			id,
			name,
			featureId: numericFeatureId,
			imageIndex: parseImageIndex(page.url.searchParams.get('img')),
			gallery: page.url.searchParams.get('gal'),
			tab: parseTab(page.url.searchParams.get('tab'))
		};
		return applyAtParam(defaults);
	}

	const imageIndex = parseImageIndex(page.url.searchParams.get('img'));

	const defaults = {
		...DEFAULT_VIEW,
		type,
		id,
		name,
		imageIndex,
		gallery: page.url.searchParams.get('gal'),
		featureId: null,
		tab: parseTab(page.url.searchParams.get('tab')),
		memberPage: parseMemberPage(page.url.searchParams.get('mp')),
		quad: page.url.searchParams.get('quad'),
		featureType: page.url.searchParams.get('ftype'),
		ring: page.url.searchParams.get('ring')
	};
	return applyAtParam(defaults);
}

/** Overlay the `?at=<date,lat,lon,zoom>` query block on top of a defaults
 *  object. Extracted so both route branches share the same parsing. */
function applyAtParam(defaults: MapViewState): MapViewState {
	const at = page.url.searchParams.get('at');
	if (!at) return defaults;

	const parts = at.split(',');
	const isNow = !parts[0] || parts[0] === 'now';
	const parsed = isNow ? new Date() : new Date(parts[0]);
	const date = isNaN(parsed.getTime()) ? new Date() : parsed;
	if (parts.length < 4) return { ...defaults, date, isNow };

	const latitude = Number(parts[1]);
	const longitude = Number(parts[2]);
	const zoom = Number(parts[3]);

	if (!isFinite(latitude) || !isFinite(longitude) || !isFinite(zoom))
		return { ...defaults, date, isNow };

	return { ...defaults, date, isNow, latitude, longitude, zoom, framed: true };
}

/** Next view when focusing a body. Mirrors AppState.setFocus's merge so link
 *  hrefs and the committed state stay in lockstep. */
export function applyFocus(
	current: MapViewState,
	focus: {
		type: string;
		id: string;
		name: string;
		tab?: Exclude<DrawerTab, 'overview'>;
		/** Preselect a quadrangle on the Surface tab (feature → host body link). */
		quad?: string;
		/** Preselect a feature type on the Surface tab (ft- page → host body). */
		featureType?: string;
	}
): MapViewState {
	return {
		...current,
		...focus,
		imageIndex: null,
		gallery: null,
		featureId: null,
		groupSlug: null,
		// Land on a requested tab (e.g. a moon→planet link opening the Moons tab);
		// overview otherwise. Falls back to overview client-side if the tab is absent.
		tab: focus.tab ?? null,
		memberPage: null,
		quad: focus.quad ?? null,
		featureType: focus.featureType ?? null,
		ring: null,
		navFrom: null,
		navTo: null,
		navFromFeature: null,
		navToFeature: null,
		trip: DEFAULT_TRIP
	};
}

/** One end of a trip: the body it is priced against, and the place on it when
 *  the endpoint is somewhere on the surface — a named feature, or a point. */
export interface NavEnd {
	id: string;
	featureId?: number | null;
	place?: NavPlace | null;
}

/** Accept a bare id where the feature slot doesn't matter, so callers that only
 *  ever mean a whole body stay readable. */
function navEnd(end: string | NavEnd): NavEnd {
	return typeof end === 'string' ? { id: end } : end;
}

/**
 * One end of the trip on screen, whole.
 *
 * An end is more than the body it is priced against: rebuilt from its id and
 * its feature it silently loses the point a launch pad *is*. Anything that
 * keeps one end while moving the other reads it from here.
 */
export function navEndOf(view: MapViewState, at: 'from' | 'to'): NavEnd | null {
	const id = at === 'from' ? view.navFrom : view.navTo;
	if (id === null) return null;
	return {
		id,
		featureId: at === 'from' ? view.navFromFeature : view.navToFeature,
		place: at === 'from' ? view.navFromPlace : view.navToPlace
	};
}

/**
 * Next view when opening the trip planner.
 *
 * The destination doubles as the framed body: you are looking at where you are
 * going, the same way a focus view frames its subject. Either end may be null —
 * a trip is described one end at a time — and the camera falls back to whichever
 * one is there.
 *
 * The trip's terms ride through untouched. Moving an end is still the same
 * planner with the same craft loaded the same way, and what a change of ends
 * costs the route choice and the hand pick is the panel's to decide — it holds
 * the grid they are measured against.
 */
export function applyNav(
	current: MapViewState,
	from: string | NavEnd | null,
	to: string | NavEnd | null = null
): MapViewState {
	const departure = from === null ? null : navEnd(from);
	const destination = to === null ? null : navEnd(to);
	return {
		...current,
		type: UrlType.Nav,
		id: destination?.id ?? departure?.id ?? current.id,
		name: '',
		navFrom: departure?.id ?? null,
		navTo: destination?.id ?? null,
		navFromFeature: departure?.featureId ?? null,
		navToFeature: destination?.featureId ?? null,
		navFromPlace: departure?.place ?? null,
		navToPlace: destination?.place ?? null,
		imageIndex: null,
		gallery: null,
		featureId: null,
		groupSlug: null,
		tab: null,
		memberPage: null,
		quad: null,
		featureType: null,
		ring: null
	};
}

/** Next view when switching drawer tabs. Depth reached inside a tab (member
 *  page, quadrangle, ring drill, open picture) belongs to the tab being left,
 *  so it clears. The viewer indexes into a shelf that is about to close, so
 *  leaving it open would re-point it at whatever shelf leads instead. */
export function applyTab(current: MapViewState, tab: DrawerTab): MapViewState {
	return {
		...current,
		tab: tab === 'overview' ? null : tab,
		imageIndex: null,
		gallery: null,
		memberPage: null,
		quad: null,
		featureType: null,
		ring: null
	};
}

/** Next view when selecting the Surface tab's quadrangle (null = all of them).
 *  The list underneath is a different set, so paging depth clears. */
export function applyQuad(current: MapViewState, code: string | null): MapViewState {
	return { ...current, quad: code, memberPage: null };
}

/** Next view when opening the image viewer on one image of the active gallery. */
export function applyImage(current: MapViewState, index: number | null): MapViewState {
	return { ...current, imageIndex: index };
}

/** Next view when opening one gallery (null = back to the shelf index). The
 *  viewer indexes into the gallery, so an open one closes. Opening one also
 *  lands on the Images tab, since that's the only place a shelf renders. */
export function applyGallery(current: MapViewState, key: string | null): MapViewState {
	return {
		...current,
		tab: key === null ? current.tab : 'images',
		gallery: key,
		imageIndex: null
	};
}

/** Next view when opening a group. Parks `id` on the group's camera anchor
 *  so the body route resolves to the anchor body. */
export function applyGroup(current: MapViewState, slug: string, name: string): MapViewState {
	const anchor = groupAnchor(slug);
	return {
		...current,
		type: UrlType.Group,
		id: anchor.id,
		zoom: anchor.zoom,
		groupSlug: slug,
		name,
		imageIndex: null,
		gallery: null,
		featureId: null,
		tab: null,
		memberPage: null,
		quad: null,
		featureType: null,
		ring: null,
		navFrom: null,
		navTo: null,
		navFromFeature: null,
		navToFeature: null,
		trip: DEFAULT_TRIP
	};
}

/** Next view when opening a nomenclature feature on its parent body. */
export function applyFeature(
	current: MapViewState,
	focus: { bodyId: string; featureId: number; featureName: string }
): MapViewState {
	return {
		...current,
		type: UrlType.Feature,
		id: focus.bodyId,
		name: focus.featureName,
		featureId: focus.featureId,
		// Opening a feature from a collection page (ft-*) leaves that page —
		// a lingering slug would keep the group route winning over the feature.
		groupSlug: null,
		imageIndex: null,
		gallery: null,
		tab: null,
		memberPage: null,
		quad: null,
		featureType: null,
		ring: null,
		navFrom: null,
		navTo: null,
		navFromFeature: null,
		navToFeature: null,
		trip: DEFAULT_TRIP
	};
}

/** Query-less route path for a body id — used by scene labels as an `<a href>`
 *  so middle/⌘-click opens the body in a new tab. No `?at=` framing: a fresh
 *  open frames by the body's size, same as any unframed load. */
export function bodyHref(id: string, name: string): string {
	const type = urlTypeFromId(id);
	const numericId = id.slice(`${urlTypeToIdPrefix(type)}-`.length);
	return resolve('/[type]/[id]/[[name]]', {
		type,
		id: numericId,
		name: name ? encodeURIComponent(name) : undefined
	});
}

/** Produce the route path for the current MapViewState — `/<type>/<id>/<name>`
 *  for bodies and groups (groups carry a slug in the id slot), or
 *  `/<type>/<id>/f/<featureId>/<name>` for features — plus the shared
 *  `?at=<date>,<lat>,<lon>,<zoom>` query block. */
export function serializeUrl(state: MapViewState): string {
	const r = (n: number) => n.toFixed(5);
	const dateStr = state.isNow ? 'now' : state.date.toISOString();
	const at = `${dateStr},${r(state.latitude)},${r(state.longitude)},${state.zoom.toPrecision(5).replace('e+', 'e')}`;

	const img =
		typeof state.imageIndex === 'number' && Number.isInteger(state.imageIndex)
			? `&img=${state.imageIndex}`
			: '';
	// `mp` is only meaningful under the paginated lists (members / features),
	// `quad`/`ftype` only under the features tab's surface hero + list, and
	// `ring` only under the rings tab's drill path.
	const tab = state.tab ? `&tab=${state.tab}` : '';
	const surface =
		state.tab === 'features'
			? (state.quad ? `&quad=${encodeURIComponent(state.quad)}` : '') +
				(state.featureType ? `&ftype=${encodeURIComponent(state.featureType)}` : '')
			: '';
	const ring = state.tab === 'rings' && state.ring ? `&ring=${encodeURIComponent(state.ring)}` : '';
	const gal =
		state.tab === 'images' && state.gallery ? `&gal=${encodeURIComponent(state.gallery)}` : '';
	const paginated = state.tab === 'members' || state.tab === 'features';
	const mp =
		paginated &&
		typeof state.memberPage === 'number' &&
		Number.isInteger(state.memberPage) &&
		state.memberPage > 1
			? `&mp=${state.memberPage}`
			: '';

	if (state.type === UrlType.Nav) {
		// The departure slot is always written, as an id or as the unset marker:
		// the ends are positional, so `/nav/<x>` would read as a departure.
		const path = resolve('/nav/[[from]]/[[to]]', {
			from: state.navFrom
				? formatNavEnd(state.navFrom, state.navFromFeature, state.navFromPlace)
				: NAV_UNSET,
			to: state.navTo ? formatNavEnd(state.navTo, state.navToFeature, state.navToPlace) : undefined
		});
		const sites = placeParams('f', state.navFromPlace) + placeParams('t', state.navToPlace);
		// A trip is described by its two ends and the terms it is flown on; the rest
		// of the query block belongs to drawer tabs the planner doesn't have.
		return `${path}?at=${at}${sites}${serializeTripSuffix(state.trip)}`;
	}

	if (state.type === UrlType.Group && state.groupSlug !== null) {
		const path = resolve('/[type]/[id]/[[name]]', {
			type: state.type,
			id: state.groupSlug,
			name: state.name ? encodeURIComponent(state.name) : undefined
		});
		return `${path}?at=${at}${img}${tab}${gal}${surface}${ring}${mp}`;
	}

	const bodyType = urlTypeFromId(state.id);
	const prefix = `${urlTypeToIdPrefix(bodyType)}-`;
	const numericId = state.id.slice(prefix.length);

	if (state.type === UrlType.Feature && state.featureId !== null) {
		const path = resolve('/[type]/[id]/f/[featureId]/[[name]]', {
			type: bodyType,
			id: numericId,
			featureId: String(state.featureId),
			name: state.name ? encodeURIComponent(state.name) : undefined
		});
		// A feature's own pictures are its only shelf; the rest of the query
		// block belongs to lists and drills it doesn't have.
		return `${path}?at=${at}${img}${tab}${gal}`;
	}

	const path = resolve('/[type]/[id]/[[name]]', {
		type: state.type,
		id: numericId,
		name: state.name ? encodeURIComponent(state.name) : undefined
	});
	return `${path}?at=${at}${img}${tab}${gal}${surface}${ring}${mp}`;
}
