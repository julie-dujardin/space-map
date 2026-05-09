import { Mesh } from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import './user-location.css';

const RAD = Math.PI / 180;

/**
 * Local-frame offset on a body's surface for the given lat/lon, matching
 * the convention in `$lib/math/spherical.ts`: lat=0, lon=0 sits on +X
 * (prime meridian on equator), longitude increases east (-Z direction).
 * Caller multiplies by the body's radius in scene units.
 */
function bodyLocalUnitVector(latitude: number, longitude: number): [number, number, number] {
	const latR = latitude * RAD;
	const lonR = longitude * RAD;
	return [Math.cos(latR) * Math.cos(lonR), Math.sin(latR), -Math.cos(latR) * Math.sin(lonR)];
}

/**
 * Build a Google-Maps-style "you are here" dot as a CSS2DObject parented to
 * a body's mesh. Living under the mesh means it inherits the body's rotation
 * (so the dot stays on the same lat/lon as the planet spins) and translation
 * (so it follows the planet through space). Fixed pixel size, so it stays
 * visible whether the camera is at street level or at solar-system scale.
 */
export function createUserLocationMarker(
	bodyMesh: Mesh,
	radiusScene: number,
	latitude: number,
	longitude: number
): CSS2DObject {
	const el = document.createElement('div');
	el.className = 'user-location-marker';

	const obj = new CSS2DObject(el);
	const [ux, uy, uz] = bodyLocalUnitVector(latitude, longitude);
	obj.position.set(ux * radiusScene, uy * radiusScene, uz * radiusScene);
	bodyMesh.add(obj);
	return obj;
}

export function removeUserLocationMarker(marker: CSS2DObject): void {
	marker.parent?.remove(marker);
	marker.element.remove();
}
