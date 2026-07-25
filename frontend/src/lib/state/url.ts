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
import { EARTH_ID, SUN_ID } from '$lib/constants';
import { DEFAULT_VIEW, SUN_VIEW_ZOOM, UrlType, type DrawerTab, type MapViewState } from './view';

/** Tabs that serialize a `&tab=` block; overview is the null default. */
const DEEP_LINK_TABS: readonly string[] = ['images', 'members', 'features', 'fragments'];

function parseTab(raw: string | null): Exclude<DrawerTab, 'overview'> | null {
	return raw && DEEP_LINK_TABS.includes(raw) ? (raw as Exclude<DrawerTab, 'overview'>) : null;
}

/** Page 1 is implicit, so only integers > 1 carry meaning. */
function parseMemberPage(raw: string | null): number | null {
	if (!raw) return null;
	const n = Number(raw);
	return Number.isInteger(n) && n > 1 ? n : null;
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

/** Parse current page state → MapViewState, or null */
export function parseUrl(): MapViewState | null {
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
			featureId: null,
			tab: parseTab(page.url.searchParams.get('tab')),
			memberPage: parseMemberPage(page.url.searchParams.get('mp'))
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
			imageIndex: null
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
		featureId: null,
		tab: parseTab(page.url.searchParams.get('tab')),
		memberPage: parseMemberPage(page.url.searchParams.get('mp'))
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
	focus: { type: string; id: string; name: string; tab?: Exclude<DrawerTab, 'overview'> }
): MapViewState {
	return {
		...current,
		...focus,
		imageIndex: null,
		featureId: null,
		groupSlug: null,
		// Land on a requested tab (e.g. a moon→planet link opening the Moons tab);
		// overview otherwise. Falls back to overview client-side if the tab is absent.
		tab: focus.tab ?? null,
		memberPage: null
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
		featureId: null,
		tab: null,
		memberPage: null
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
		tab: null,
		memberPage: null
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
	// `mp` is only meaningful under the paginated lists (members / features).
	const tab = state.tab ? `&tab=${state.tab}` : '';
	const paginated = state.tab === 'members' || state.tab === 'features';
	const mp =
		paginated &&
		typeof state.memberPage === 'number' &&
		Number.isInteger(state.memberPage) &&
		state.memberPage > 1
			? `&mp=${state.memberPage}`
			: '';

	if (state.type === UrlType.Group && state.groupSlug !== null) {
		const path = resolve('/[type]/[id]/[[name]]', {
			type: state.type,
			id: state.groupSlug,
			name: state.name ? encodeURIComponent(state.name) : undefined
		});
		return `${path}?at=${at}${img}${tab}${mp}`;
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
		// No `&img=` for features — there's no gallery on a feature yet.
		return `${path}?at=${at}`;
	}

	const path = resolve('/[type]/[id]/[[name]]', {
		type: state.type,
		id: numericId,
		name: state.name ? encodeURIComponent(state.name) : undefined
	});
	return `${path}?at=${at}${img}${tab}${mp}`;
}
