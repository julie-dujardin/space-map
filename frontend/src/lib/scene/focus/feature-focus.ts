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

const DEG2RAD = Math.PI / 180;

/** Focus-body id for a feature seat — synthetic, never serialised, just
 *  needs to be stable and distinct from real ids. */
function featureBodyId(hostId: string, featureId: number): string {
	return `feature:${hostId}:${featureId}`;
}

/** Synthesise the orbitable focus body for a surface feature. Orbital elements
 *  are inert — {@link seatFeatureBody} recomputes the seat each frame, not
 *  propagation. Carries no mesh/halo/trail; the host renders the terrain. */
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

/** Wall-clock glide constant for seat moves from surface data upgrading under
 *  the camera (sphere → terrain → ray-cast label). */
const SEAT_GLIDE_TAU_MS = 120;

/** Squared seat-move (~1 m) under which the glide snaps instead of chasing. */
const SEAT_GLIDE_SNAP_SQ = kmToScene(0.001) ** 2;

interface SeatGlide {
	/** Body-fixed part (scene units). */
	fixed: Vector3;
	/** World-frame addend (mirrors overlay recentre); must not spin with the
	 *  body. Zero off the model path. */
	addend: Vector3;
	t: number;
}

/** Keyed on the synthetic body so a refocus starts fresh and seats instantly. */
const glideState = new WeakMap<PositionedBody, SeatGlide>();

const _fixed = new Vector3();
const _addend = new Vector3();

function glideVec(current: Vector3, target: Vector3, k: number): void {
	if (current.distanceToSquared(target) <= SEAT_GLIDE_SNAP_SQ) current.copy(target);
	else current.lerp(target, k);
}

/** Re-seat the feature body on the host's rendered surface for `jd`, targeting
 *  the feature's placed label so the camera centres on exactly what's labelled.
 *  Rebuilt from the label's local offset plus fresh host position/orientation,
 *  never `getWorldPosition` (its matrices lag a frame). Falls back to
 *  {@link renderedSeatAt}, then the mean-radius sphere, before the label attaches.
 *  Source upgrades glide rather than snap, keeping host motion full-rate. */
export function seatFeatureBody(
	fb: PositionedBody,
	host: PositionedBody,
	hostBo: BodyObjects | undefined,
	jd: number
): void {
	const anchor = fb.featureAnchor!;
	const hostPos = host.position;
	// Keeps zenith-north tracking the host.
	if (fb.orbitCenter) {
		fb.orbitCenter[0] = hostPos[0];
		fb.orbitCenter[1] = hostPos[1];
		fb.orbitCenter[2] = hostPos[2];
	}

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

	const now = performance.now();
	let st = glideState.get(fb);
	if (!st) {
		st = { fixed: _fixed.clone(), addend: _addend.clone(), t: now };
		glideState.set(fb, st);
	} else {
		const k = 1 - Math.exp(-(now - st.t) / SEAT_GLIDE_TAU_MS);
		st.t = now;
		glideVec(st.fixed, _fixed, k);
		glideVec(st.addend, _addend, k);
	}

	_fixed.copy(st.fixed);
	if (host.orientation) {
		_fixed.applyQuaternion(bodyQuaternion(host.orientation, jd, host.nutPrec));
	}
	fb.position[0] = hostPos[0] + _fixed.x + st.addend.x;
	fb.position[1] = hostPos[1] + _fixed.y + st.addend.y;
	fb.position[2] = hostPos[2] + _fixed.z + st.addend.z;
}
