import { Vector3 } from 'three';
import type { PositionedBody } from '$lib/types/objects';
import { bodyQuaternion } from '$lib/math/orientation';
import { kmToScene } from '$lib/math/units';
import type { BodyObjects } from '$lib/scene/types';
import type { Vec3 } from '$lib/scene/animation/math';
import { bodyFixedUnit, renderedSeatAt } from './rendered-surface';
import { setOrbitCenter, setPlaced } from './placement';

const DEG2RAD = Math.PI / 180;

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
	hostPos: Readonly<Vec3>,
	hostBo: BodyObjects | undefined,
	jd: number
): Vec3 | null {
	const anchor = fb.featureAnchor!;
	// Keeps zenith-north tracking the host.
	setOrbitCenter(fb, hostPos);

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
	return setPlaced(
		fb,
		hostPos[0] + _fixed.x + st.addend.x,
		hostPos[1] + _fixed.y + st.addend.y,
		hostPos[2] + _fixed.z + st.addend.z
	);
}
