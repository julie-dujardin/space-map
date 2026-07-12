import { Vector3 } from 'three';
import type { PositionedBody } from '$lib/types/objects';
import { bodyQuaternion } from '$lib/math/orientation';
import { EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { dominantPlanetId } from '$lib/scene/state/bodies.svelte';
import { isModelBearing } from '$lib/scene/objects/body/model';
import { SSB_ID } from '$lib/constants';

/**
 * A camera "north" reference. `id === null` is the always-available
 * solar-system option (ecliptic Y, scene frame); `id === GALACTIC_REF_ID` is
 * the Milky Way's galactic north pole. For body refs, `id` is the body id and
 * `name` is the display label resolved at choice-build time; `probe` marks a
 * spacecraft ref (model up rather than rotation axis).
 */
export interface NorthChoice {
	id: string | null;
	name: string | null;
	probe?: boolean;
}

/** Sentinel id for the galactic-north choice. Distinct from any NAIF/SBDB id. */
export const GALACTIC_REF_ID = 'galactic';

/** Scene-frame +Y. Shared by the camera-up controller and body-pole math. */
export const SCENE_UP = new Vector3(0, 1, 0);

/**
 * Galactic north pole direction in the Three.js scene frame.
 *
 * Defined by the IAU 1958 galactic coordinate system, refreshed to J2000:
 * α_G = 192.85948°, δ_G = 27.12825° in J2000 equatorial coordinates. The
 * conversion to the scene frame matches `equatorialToThreeJS` in
 * `$lib/math/orientation` (obliquity tilt followed by ecliptic→Three.js
 * axis swap), so the resulting vector is consistent with every body's IAU
 * pole calculation.
 */
const GALACTIC_NORTH_SCENE: Vector3 = (() => {
	const DEG2RAD = Math.PI / 180;
	const raDeg = 192.85948;
	const decDeg = 27.12825;
	const ra = raDeg * DEG2RAD;
	const dec = decDeg * DEG2RAD;
	const cosDec = Math.cos(dec);
	const xEq = cosDec * Math.cos(ra);
	const yEq = cosDec * Math.sin(ra);
	const zEq = Math.sin(dec);
	const obl = EARTH_OBLIQUITY_DEG * DEG2RAD;
	const cosObl = Math.cos(obl);
	const sinObl = Math.sin(obl);
	const xEcl = xEq;
	const yEcl = yEq * cosObl + zEq * sinObl;
	const zEcl = -yEq * sinObl + zEq * cosObl;
	return new Vector3(xEcl, zEcl, -yEcl).normalize();
})();

/** Unit vector pointing to the galactic north pole in scene frame. */
export function galacticNorthVector(out?: Vector3): Vector3 {
	return (out ?? new Vector3()).copy(GALACTIC_NORTH_SCENE);
}

/**
 * Unit vector pointing toward the body's north, in scene frame. For bodies
 * with IAU orientation data that's the pole at `jd`. For a landed probe it's
 * the local zenith (probe position away from the landing body). For a flying
 * probe it's the model's up axis through the bundle's base rotation only —
 * static, no attitude, which would tumble the camera up for spinning probes.
 * Falls back to scene Y so the renderer survives a stale id.
 */
export function bodyNorthVector(
	body: PositionedBody,
	jd: number,
	out?: Vector3,
	landed = false
): Vector3 {
	const target = out ?? new Vector3();
	if (!body.orientation) {
		if (landed && body.orbitCenter) {
			// orbitCenter holds the landing body's position for landed probes.
			target.set(
				body.position[0] - body.orbitCenter[0],
				body.position[1] - body.orbitCenter[1],
				body.position[2] - body.orbitCenter[2]
			);
			if (target.lengthSq() > 1e-20) return target.normalize();
		}
		target.copy(SCENE_UP);
		if (body.modelBaseFrame) target.applyQuaternion(body.modelBaseFrame).normalize();
		return target;
	}
	const q = bodyQuaternion(body.orientation, jd, body.nutPrec);
	return target.copy(SCENE_UP).applyQuaternion(q).normalize();
}

/**
 * Walks focused → ancestors via `parentId`, collecting every body with
 * orientation data, and appends solar-system as the always-present fallback.
 * Stops at the SSB (`naif-0`). Caller hides the selector when length ≤ 1.
 *
 * A focused probe (model-bearing, no IAU frame) is offered as its own ref —
 * `bodyNorthVector` resolves it to the static model up.
 *
 * Planetary barycenters (NAIF id `naif-1`…`naif-9`) carry no rotational
 * frame, so the SPICE convention's dominant planet (`naif-{X}99`) is
 * substituted in their place — e.g. walking up from the Moon
 * (Moon → EMB → SSB) surfaces Earth as the EMB stand-in.
 */
export function getNorthChoices(
	focused: PositionedBody | undefined,
	ctx: ContextManager
): NorthChoice[] {
	const choices: NorthChoice[] = [{ id: null, name: null }];
	const seen = new Set<string>();
	let cur: PositionedBody | undefined = focused;
	while (cur && !seen.has(cur.data.id)) {
		seen.add(cur.data.id);

		let chosen: PositionedBody = cur;
		const planetId = dominantPlanetId(cur.data.id);
		if (planetId) {
			const planet = ctx.getBody(planetId);
			if (planet) chosen = planet;
		}
		const probeRef = cur === focused && !chosen.orientation && isModelBearing(cur);
		if ((chosen.orientation || probeRef) && !choices.some((c) => c.id === chosen.data.id)) {
			// Insert at index 1 so the result reads outermost → innermost:
			// [Solar System, Sun, …, parent, focused].
			choices.splice(1, 0, { id: chosen.data.id, name: chosen.data.name, probe: probeRef });
		}

		if (cur.data.parentId === SSB_ID) break;
		cur = ctx.getBody(cur.data.parentId);
	}
	// galactic north: always first
	choices.splice(0, 0, { id: GALACTIC_REF_ID, name: null });
	return choices;
}
