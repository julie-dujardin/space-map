import { Vector3 } from 'three';
import {
	ObjectType,
	type BodyData,
	type FeatureAnchor,
	type PositionedBody
} from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { bodyQuaternion } from '$lib/math/orientation';
import { kmToScene } from '$lib/math/units';
import { bodyFixedUnit, renderedSeatAt } from '$lib/scene/position/rendered-surface';
import type { BodyObjects } from '$lib/scene/types';
import type { Vec3 } from '$lib/scene/animation/math';

const DEG2RAD = Math.PI / 180;

/** Focus-body id for a feature seat. Never serialised (synthetic), so a plain
 *  composite is fine; it just has to be stable and distinct from real ids. */
function featureBodyId(hostId: string, featureId: number): string {
	return `feature:${hostId}:${featureId}`;
}

/**
 * Synthesise the orbitable focus body for a surface feature. Orbital elements
 * are inert — the seat is recomputed each frame by {@link seatFeatureBody}, not
 * propagated. Carries no mesh/halo/trail of its own; the host renders the
 * terrain the camera orbits and its label marks the spot.
 */
export function makeFeatureBody(anchor: FeatureAnchor, name: string | null): PositionedBody {
	const data: BodyData = {
		id: featureBodyId(anchor.hostId, anchor.featureId),
		name,
		objectType: ObjectType.SURFACE_FEATURE,
		parentId: anchor.hostId,
		radiusKm: NaN,
		hasLocalized: false,
		a: 0,
		e: 0,
		i: 0,
		om: 0,
		w: 0,
		ma: 0,
		n: 0,
		epoch: 0,
		validityStart: -Infinity,
		validityEnd: Infinity,
		orbitalSource: OrbitalSource.UNKNOWN
	};
	return { data, position: [0, 0, 0], orbitCenter: [0, 0, 0], featureAnchor: anchor };
}

const _seat = new Vector3();

/**
 * Re-seat the feature body on the host's rendered surface for `jd`. Targets the
 * feature's own placed label — already ray-cast onto the real surface for shape
 * models and lifted onto the terrain for ellipsoid meshes, so the camera centres
 * on exactly what's labelled with no separate surface math. Labels render in the
 * focus-relative frame, so their world position is offset by `focusTruePos`,
 * which cancels back to world here. Until the label attaches it falls back to
 * {@link renderedSeatAt} — the same sampler landed probes and the camera floor
 * use — and to the mean-radius sphere while that data loads. Also refreshes
 * `orbitCenter` so the zenith north reference tracks the host.
 */
export function seatFeatureBody(
	fb: PositionedBody,
	host: PositionedBody,
	hostBo: BodyObjects | undefined,
	jd: number,
	focusTruePos: Vec3
): void {
	const anchor = fb.featureAnchor!;
	const hostPos = host.position;
	if (fb.orbitCenter) {
		fb.orbitCenter[0] = hostPos[0];
		fb.orbitCenter[1] = hostPos[1];
		fb.orbitCenter[2] = hostPos[2];
	}

	const idx = hostBo?.nomenclatureActiveIndex ?? -1;
	const label = idx >= 0 ? (hostBo?.nomenclatureLabels?.[idx] ?? null) : null;
	if (label && label.element.dataset.featureId === String(anchor.featureId)) {
		label.getWorldPosition(_seat);
		fb.position[0] = _seat.x + focusTruePos[0];
		fb.position[1] = _seat.y + focusTruePos[1];
		fb.position[2] = _seat.z + focusTruePos[2];
		return;
	}

	const radiusKm = host.data.radiusKm;
	const latR = anchor.lat * DEG2RAD;
	const lngR = anchor.lon * DEG2RAD;
	if (host.orientation && Number.isFinite(radiusKm) && radiusKm > 0) {
		const seat = renderedSeatAt(hostBo, host.data.id, radiusKm, latR, lngR);
		if (seat) {
			_seat.set(seat.pointKm[0], seat.pointKm[1], seat.pointKm[2]);
		} else {
			const [nx, ny, nz] = bodyFixedUnit(latR, lngR);
			_seat.set(radiusKm * nx, radiusKm * ny, radiusKm * nz);
		}
		_seat.applyQuaternion(bodyQuaternion(host.orientation, jd, host.nutPrec));
	} else {
		const r = Number.isFinite(radiusKm) && radiusKm > 0 ? radiusKm : 0;
		const [nx, ny, nz] = bodyFixedUnit(latR, lngR);
		_seat.set(r * nx, r * ny, r * nz);
	}
	fb.position[0] = hostPos[0] + kmToScene(_seat.x);
	fb.position[1] = hostPos[1] + kmToScene(_seat.y);
	fb.position[2] = hostPos[2] + kmToScene(_seat.z);
}
