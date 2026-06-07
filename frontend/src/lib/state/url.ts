import { resolve } from '$app/paths';
import { page } from '$app/state';
import { DEFAULT_VIEW, UrlType, type MapViewState } from './view';

/** Map URL type segment to backend ID prefix. Inverse of urlTypeFromId. */
export function urlTypeToIdPrefix(urlType: string): string {
	if (urlType === UrlType.SmallBody) return 'spkid';
	if (urlType === UrlType.EarthSatellite) return 'norad_satcat';
	if (urlType === UrlType.Probe) return 'probe';
	return 'naif'; // UrlType.Body
}

/** Derive URL type segment from a prefixed body ID. Use this for URL generation — it's always consistent with the ID. */
export function urlTypeFromId(id: string): UrlType {
	if (id.startsWith('spkid-')) return UrlType.SmallBody;
	if (id.startsWith('norad_satcat-')) return UrlType.EarthSatellite;
	if (id.startsWith('probe-')) return UrlType.Probe;
	return UrlType.Body; // naif-
}

/** Camera anchor when landing on /g/<slug> cold. Earth covers Phase-1 groups
 *  (constellations); revisit once other applies_to categories ship. */
const GROUP_DEFAULT_BODY = 'naif-399';
/** Earth-system zoom — mirrors MapPage's minimize-from-sat distance. */
const GROUP_DEFAULT_ZOOM = 0.005;

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
		const defaults: MapViewState = {
			...DEFAULT_VIEW,
			type: UrlType.Group,
			id: GROUP_DEFAULT_BODY,
			zoom: GROUP_DEFAULT_ZOOM,
			name: decodeURIComponent(page.params.name ?? ''),
			groupSlug: idStr,
			imageIndex: null,
			featureId: null
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

	const imgRaw = page.url.searchParams.get('img');
	let imageIndex: number | null = null;
	if (imgRaw) {
		const n = Number(imgRaw);
		if (Number.isInteger(n) && n >= 0) imageIndex = n;
	}

	const defaults = { ...DEFAULT_VIEW, type, id, name, imageIndex, featureId: null };
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

	return { ...defaults, date, isNow, latitude, longitude, zoom };
}

/** Produce the route path for the current MapViewState — `/<type>/<id>/<name>`
 *  for bodies and groups (groups carry a slug in the id slot), or
 *  `/<type>/<id>/f/<featureId>/<name>` for features — plus the shared
 *  `?at=<date>,<lat>,<lon>,<zoom>` query block. */
export function serializeUrl(state: MapViewState): string {
	const r = (n: number) => n.toFixed(5);
	const dateStr = state.isNow ? 'now' : state.date.toISOString();
	const at = `${dateStr},${r(state.latitude)},${r(state.longitude)},${state.zoom.toPrecision(5).replace('e+', 'e')}`;

	if (state.type === UrlType.Group && state.groupSlug !== null) {
		const path = resolve('/[type]/[id]/[[name]]', {
			type: state.type,
			id: state.groupSlug,
			name: state.name ? encodeURIComponent(state.name) : undefined
		});
		return `${path}?at=${at}`;
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
	const img =
		typeof state.imageIndex === 'number' && Number.isInteger(state.imageIndex)
			? `&img=${state.imageIndex}`
			: '';
	return `${path}?at=${at}${img}`;
}
