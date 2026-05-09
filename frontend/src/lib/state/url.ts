import { resolve } from '$app/paths';
import { page } from '$app/state';
import { DEFAULT_VIEW, UrlType, type MapViewState } from './view';

/** Map URL type segment to backend ID prefix. Inverse of urlTypeFromId. */
export function urlTypeToIdPrefix(urlType: string): string {
	if (urlType === UrlType.SmallBody) return 'spkid';
	if (urlType === UrlType.EarthSatellite) return 'norad_satcat';
	return 'naif'; // UrlType.Body
}

/** Derive URL type segment from a prefixed body ID. Use this for URL generation — it's always consistent with the ID. */
export function urlTypeFromId(id: string): UrlType {
	if (id.startsWith('spkid-')) return UrlType.SmallBody;
	if (id.startsWith('norad_satcat-')) return UrlType.EarthSatellite;
	return UrlType.Body; // naif-
}

/** Parse current page state → MapViewState, or null */
export function parseUrl(): MapViewState | null {
	const type = page.params.type;
	const idStr = page.params.id;
	if (!type || !idStr) {
		console.warn(`parseUrl: missing route params (type=${type}, id=${idStr})`);
		return null;
	}

	const numericId = Number(idStr);
	if (!Number.isFinite(numericId)) {
		console.warn(`parseUrl: non-numeric id param: ${idStr}`);
		return null;
	}
	const id = `${urlTypeToIdPrefix(type)}-${numericId}`;

	const name = decodeURIComponent(page.params.name ?? '');

	const imgRaw = page.url.searchParams.get('img');
	let imageIndex: number | null = null;
	if (imgRaw) {
		const n = Number(imgRaw);
		if (Number.isInteger(n) && n >= 0) imageIndex = n;
	}

	const defaults = { ...DEFAULT_VIEW, type, id, name, imageIndex };

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

	return { type, id, name, date, isNow, latitude, longitude, zoom, imageIndex };
}

/** Produce `/<type>/<id>/<name>?at=<date>,<lat>,<lon>,<zoom>` */
export function serializeUrl(state: MapViewState): string {
	const r = (n: number) => n.toFixed(5);
	const dateStr = state.isNow ? 'now' : state.date.toISOString();
	const at = `${dateStr},${r(state.latitude)},${r(state.longitude)},${state.zoom.toPrecision(5).replace('e+', 'e')}`;
	const prefix = state.id.startsWith('norad_satcat-')
		? 'norad_satcat-'
		: state.id.startsWith('spkid-')
			? 'spkid-'
			: 'naif-';
	const numericId = state.id.slice(prefix.length);
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
