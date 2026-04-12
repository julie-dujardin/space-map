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

/**
 * Rotate a 3-vector by a quaternion [x, y, z, w] (or its inverse).
 * Matches three.js convention so callers can pass `mesh.quaternion.toArray()`.
 */
function applyQuat(
	v: [number, number, number],
	q: [number, number, number, number],
	inverse: boolean
): [number, number, number] {
	const [x, y, z] = v;
	const [qx, qy, qz, qw] = inverse ? [-q[0], -q[1], -q[2], q[3]] : q;
	const ix = qw * x + qy * z - qz * y;
	const iy = qw * y + qz * x - qx * z;
	const iz = qw * z + qx * y - qy * x;
	const iw = -qx * x - qy * y - qz * z;
	return [
		ix * qw + iw * -qx + iy * -qz - iz * -qy,
		iy * qw + iw * -qy + iz * -qx - ix * -qz,
		iz * qw + iw * -qz + ix * -qy - iy * -qx
	];
}

/**
 * Camera-relative-to-target → spherical degrees.
 * When `bodyQuat` is given, lat/lon are body-fixed (lat=0, lon=0 ↔ prime meridian
 * on the equator, lon increases east). When omitted, they're scene-frame (Y-up).
 */
export function cartesianToSpherical(
	cam: [number, number, number],
	target: [number, number, number],
	bodyQuat?: [number, number, number, number]
): { latitude: number; longitude: number; distance: number } {
	let dx = cam[0] - target[0];
	let dy = cam[1] - target[1];
	let dz = cam[2] - target[2];
	const distance = sqrt(dx * dx + dy * dy + dz * dz);
	if (bodyQuat) {
		[dx, dy, dz] = applyQuat([dx, dy, dz], bodyQuat, true);
	}
	return {
		latitude: asin(dy / distance) * DEG,
		longitude: bodyQuat
			? atan2(-dz, dx) * DEG // body frame: +X = prime meridian, -Z = east
			: atan2(dx, dz) * DEG,
		distance
	};
}

/**
 * Spherical degrees → world-space camera position.
 * When `bodyQuat` is given, lat/lon are interpreted as body-fixed.
 */
export function sphericalToCartesian(
	target: [number, number, number],
	lat: number,
	lon: number,
	distance: number,
	bodyQuat?: [number, number, number, number]
): [number, number, number] {
	const latR = lat * RAD;
	const lonR = lon * RAD;
	let ox: number;
	let oy: number;
	let oz: number;
	if (bodyQuat) {
		const local: [number, number, number] = [
			distance * cos(latR) * cos(lonR),
			distance * sin(latR),
			-distance * cos(latR) * sin(lonR)
		];
		[ox, oy, oz] = applyQuat(local, bodyQuat, false);
	} else {
		ox = distance * cos(latR) * sin(lonR);
		oy = distance * sin(latR);
		oz = distance * cos(latR) * cos(lonR);
	}
	return [target[0] + ox, target[1] + oy, target[2] + oz];
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
