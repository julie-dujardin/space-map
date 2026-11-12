import { Vector3 } from 'three';
import type { FeatureAnchor, PositionedBody } from '$lib/types/objects';
import { bodyQuaternion } from '$lib/math/orientation';
import { kmToScene } from '$lib/math/units';
import type { BodyObjects } from '$lib/scene/types';
import type { Vec3 } from '$lib/scene/animation/math';
import { bodyFixedUnit, renderedSeatAt } from './rendered-surface';

const DEG2RAD = Math.PI / 180;

const _fixed = new Vector3();
const _addend = new Vector3();

/** Where a surface feature stands on its host's drawn ground at `jd`: its
 *  placed label, so the camera centres on exactly what is labelled, else the
 *  rendered surface at its lat/lon, else the mean-radius sphere. Built from
 *  the label's local offset and the host's own place and spin, never
 *  `getWorldPosition` (its matrices lag a frame). */
export function featureSeat(
	anchor: FeatureAnchor,
	host: PositionedBody,
	hostPos: Readonly<Vec3>,
	hostBo: BodyObjects | undefined,
	jd: number
): Vec3 {
	_addend.set(0, 0, 0);
	const idx = hostBo?.nomenclatureActiveIndex ?? -1;
	const label = idx >= 0 ? (hostBo?.nomenclatureLabels?.[idx] ?? null) : null;
	if (label && label.element.dataset.featureId === String(anchor.featureId)) {
		const modelAnchor = hostBo?.nomenclatureAnchor;
		if (modelAnchor) {
			_fixed.copy(label.position);
			_addend.copy(modelAnchor.position);
		} else {
			// Mesh scale carries the label onto the true ellipsoid.
			_fixed.copy(label.position);
			if (hostBo?.mesh) _fixed.multiply(hostBo.mesh.scale);
		}
	} else {
		const radiusKm = host.data.radiusKm;
		const latR = anchor.lat * DEG2RAD;
		const lngR = anchor.lon * DEG2RAD;
		const seat =
			host.orientation && Number.isFinite(radiusKm) && radiusKm > 0
				? renderedSeatAt(hostBo, host.data.id, radiusKm, latR, lngR)
				: null;
		if (seat) {
			_fixed.set(seat.pointKm[0], seat.pointKm[1], seat.pointKm[2]);
		} else {
			const r = Number.isFinite(radiusKm) && radiusKm > 0 ? radiusKm : 0;
			const [nx, ny, nz] = bodyFixedUnit(latR, lngR);
			_fixed.set(r * nx, r * ny, r * nz);
		}
		_fixed.multiplyScalar(kmToScene(1));
	}

	if (host.orientation) {
		_fixed.applyQuaternion(bodyQuaternion(host.orientation, jd, host.nutPrec));
	}
	return [
		hostPos[0] + _fixed.x + _addend.x,
		hostPos[1] + _fixed.y + _addend.y,
		hostPos[2] + _fixed.z + _addend.z
	];
}
