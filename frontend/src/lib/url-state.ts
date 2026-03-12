const { PI, sin, cos, asin, atan2, sqrt } = Math;
const DEG = 180 / PI;
const RAD = PI / 180;

export interface MapViewState {
	bodyName: string;
	date: string;
	latitude: number;
	longitude: number;
	zoom: number;
}

export const DEFAULT_VIEW: MapViewState = {
	bodyName: 'Sun',
	date: 'now',
	latitude: 45,
	longitude: 0,
	zoom: 42.43
};

/** Parse `/<body>@<date>,<lat>,<lon>,<zoom>` → MapViewState, or null for `/` */
export function parseUrl(pathname: string): MapViewState | null {
	const raw = decodeURIComponent(pathname.replace(/^\//, ''));
	if (!raw) return null;

	const atIdx = raw.indexOf('@');
	if (atIdx < 1) return null;

	const bodyName = raw.slice(0, atIdx);
	const parts = raw.slice(atIdx + 1).split(',');
	if (parts.length < 4) return null;

	const [date, latStr, lonStr, zoomStr] = parts;
	const latitude = Number(latStr);
	const longitude = Number(lonStr);
	const zoom = Number(zoomStr);

	if (!isFinite(latitude) || !isFinite(longitude) || !isFinite(zoom)) return null;

	return { bodyName, date, latitude, longitude, zoom };
}

/** Produce `/<body>@<date>,<lat>,<lon>,<zoom>` */
export function serializeUrl(state: MapViewState): string {
	const r = (n: number) => n.toFixed(5);
	return `/${encodeURIComponent(state.bodyName)}@${state.date},${r(state.latitude)},${r(state.longitude)},${r(state.zoom)}`;
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
		if (url !== window.location.pathname) {
			history.replaceState(null, '', url);
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
