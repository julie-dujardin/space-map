import { Mesh } from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import './marker.css';

const RAD = Math.PI / 180;

/** Local-frame unit offset for lat/lon, matching `$lib/math/spherical.ts`:
 *  lat=0/lon=0 on +X, longitude increasing east (-Z). */
function bodyLocalUnitVector(latitude: number, longitude: number): [number, number, number] {
	const latR = latitude * RAD;
	const lonR = longitude * RAD;
	return [Math.cos(latR) * Math.cos(lonR), Math.sin(latR), -Math.cos(latR) * Math.sin(lonR)];
}

/** "You are here" dot as a CSS2DObject parented to the body's mesh, so it
 *  inherits rotation and translation. Fixed pixel size, visible at any zoom. */
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
