import { page } from '$app/state';
import { urlTypeToIdPrefix } from './format';

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
	const at = `${dateStr},${r(state.latitude)},${r(state.longitude)},${r(state.zoom)}`;
	const slug = state.name ? `/${encodeURIComponent(state.name)}` : '';
	const numericId = state.id.slice(state.id.lastIndexOf('-') + 1);
	return `/${state.type}/${numericId}${slug}?at=${at}`;
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

/** Returns a throttled sync + cancel pair (safe to call every frame) */
export function createUrlSync(intervalMs = 500) {
	let lastUpdate = 0;
	let pending: ReturnType<typeof setTimeout> | undefined;
	function write(state: MapViewState) {
		const url = serializeUrl(state);
		if (url !== window.location.pathname + window.location.search) {
			// Intentional: using history.replaceState directly for high-frequency camera sync

			history.replaceState(history.state, '', url);
		}
		lastUpdate = Date.now();
	}
	return {
		sync(state: MapViewState) {
			clearTimeout(pending);
			const elapsed = Date.now() - lastUpdate;
			if (elapsed >= intervalMs) {
				write(state);
			} else {
				// Trailing update so final state is always written
				pending = setTimeout(() => write(state), intervalMs - elapsed);
			}
		},
		cancel() {
			clearTimeout(pending);
		}
	};
}
