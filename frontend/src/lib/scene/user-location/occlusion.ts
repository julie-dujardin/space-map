import { Vector3, type PerspectiveCamera } from 'three';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { BodyObjects } from '$lib/scene/types';
import { EARTH_ID } from '$lib/constants';

const _tmp = new Vector3();

/** Hide the marker on Earth's far hemisphere: tangent-plane test reduces to
 *  `earthToMarker · earthToCamera > R²`. Camera inside Earth keeps it visible. */
export function updateUserLocationOcclusion(
	marker: CSS2DObject | null,
	bodyObjects: Map<string, BodyObjects>,
	camera: PerspectiveCamera
): void {
	if (!marker) return;
	const earth = bodyObjects.get(EARTH_ID);
	if (!earth?.mesh) return;
	// Earth-center → marker, scene-frame.
	_tmp.copy(marker.position).applyQuaternion(earth.mesh.quaternion);
	const ex = _tmp.x;
	const ey = _tmp.y;
	const ez = _tmp.z;
	// Earth-center → camera; mesh.position is Earth's focus-relative pos.
	const ep = earth.mesh.position;
	const cx = camera.position.x - ep.x;
	const cy = camera.position.y - ep.y;
	const cz = camera.position.z - ep.z;
	const r = earth.radiusScene;
	const r2 = r * r;
	const camDist2 = cx * cx + cy * cy + cz * cz;
	marker.visible = camDist2 <= r2 || ex * cx + ey * cy + ez * cz > r2;
}
