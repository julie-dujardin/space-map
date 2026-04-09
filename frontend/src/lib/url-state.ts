import { pushState as sveltePushState, replaceState as svelteReplaceState } from '$app/navigation';
import { resolve } from '$app/paths';
import { page } from '$app/state';

/** Map URL type segment to backend ID prefix. Inverse of urlTypeFromId. */
export function urlTypeToIdPrefix(urlType: string): string {
	if (urlType === 'sb') return 'spkid';
	if (urlType === 'sat') return 'norad_satcat';
	return 'naif'; // body, probe
}

/** Derive URL type segment from a prefixed body ID. Use this for URL generation — it's always consistent with the ID. */
export function urlTypeFromId(id: string): string {
	if (id.startsWith('spkid-')) return 'sb';
	if (id.startsWith('norad_satcat-')) return 'sat';
	return 'body'; // naif-
}

const { PI, sin, cos, asin, atan2, sqrt } = Math;
const DEG = 180 / PI;
const RAD = PI / 180;

export interface MapViewState {
	type: string;
	id: string; // prefixed, e.g. "naif-10", "spkid-20134340"
	name: string;
	date: Date;
	isNow: boolean;
	latitude: number;
	longitude: number;
	zoom: number;
}

export const DEFAULT_VIEW: MapViewState = {
	type: 'body',
	id: 'naif-10',
	name: 'Sun',
	date: new Date(),
	isNow: true,
	latitude: 45,
	longitude: 0,
	zoom: 42.43
};

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

	const name = page.params.name ?? '';
	const defaults = { ...DEFAULT_VIEW, type, id, name };

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

	return { type, id, name, date, isNow, latitude, longitude, zoom };
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
		name: state.name || undefined
	});
	return `${path}?at=${at}`;
}

/** Camera-relative-to-target → spherical (degrees, Y-up) */
export function cartesianToSpherical(
	cam: [number, number, number],
	target: [number, number, number]
): { latitude: number; longitude: number; distance: number } {
	const dx = cam[0] - target[0];
	const dy = cam[1] - target[1];
	const dz = cam[2] - target[2];
	const distance = sqrt(dx * dx + dy * dy + dz * dz);
	return {
		latitude: asin(dy / distance) * DEG,
		longitude: atan2(dx, dz) * DEG,
		distance
	};
}

/** Spherical (degrees, Y-up) → world-space camera position */
export function sphericalToCartesian(
	target: [number, number, number],
	lat: number,
	lon: number,
	distance: number
): [number, number, number] {
	const latR = lat * RAD;
	const lonR = lon * RAD;
	return [
		target[0] + distance * cos(latR) * sin(lonR),
		target[1] + distance * sin(latR),
		target[2] + distance * cos(latR) * cos(lonR)
	];
}

let writeTimer: ReturnType<typeof setTimeout> | undefined;
const WRITE_DEBOUNCE_MS = 250;

export function writeUrlState(state: MapViewState): void {
	clearTimeout(writeTimer);
	writeTimer = setTimeout(() => {
		const url = serializeUrl(state);
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- serializeUrl already uses resolve()
		svelteReplaceState(url, { view: state });
	}, WRITE_DEBOUNCE_MS);
}

/** Like writeUrlState but pushes a new history entry (use when switching focus target). */
export function pushUrlState(state: MapViewState): void {
	const url = serializeUrl(state);
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- serializeUrl already uses resolve()
	sveltePushState(url, { view: state });
}
