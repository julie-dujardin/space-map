import { Vector3 } from 'three';
import type { PositionedBody } from '$lib/types/objects';
import { bodyQuaternion } from '$lib/math/orientation';
import { EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { dominantPlanetId } from '$lib/scene/state/bodies.svelte';
import { isModelBearing } from '$lib/scene/objects/body/model';
import { SSB_ID } from '$lib/constants';

/**
 * A camera "north" reference. `id === null` → solar-system (ecliptic Y);
 * `id === GALACTIC_REF_ID` → galactic pole; else `id` is a body id with `name`
 * its label. `probe` = spacecraft model-up; `feature` = surface feature (local
 * vertical).
 */
export interface NorthChoice {
	id: string | null;
	name: string | null;
	probe?: boolean;
	feature?: boolean;
}

/** Sentinel id for the galactic-north choice. Distinct from any NAIF/SBDB id. */
export const GALACTIC_REF_ID = 'galactic';

/** Scene-frame +Y. Shared by the camera-up controller and body-pole math. */
export const SCENE_UP = new Vector3(0, 1, 0);

/**
 * Galactic north pole in the scene frame. IAU 1958 pole at J2000
 * (α = 192.85948°, δ = 27.12825°), converted the same way as every body's IAU
 * pole (`equatorialToThreeJS`) so the references stay mutually consistent.
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
 * Unit "north" for a body in the scene frame: IAU pole at `jd` when oriented;
 * local zenith for a landed probe or focused surface feature (no orientation —
 * `position` is the seat, `orbitCenter` the host centre); else a flying probe's
 * static model-up (base frame only — attitude would tumble the camera on
 * spinners). Falls back to scene Y on a stale id.
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
			// orbitCenter = host centre, so this resolves to the local zenith.
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
 * Focused → ancestors (via `parentId`, up to the SSB), collecting every
 * orientation-bearing body, plus solar-system as the always-present fallback.
 * Caller hides the selector when length ≤ 1.
 *
 * A focused probe is its own ref (static model-up). A focused surface feature
 * reports its host upward (see Scene.svelte), so `focused` is the host; the
 * feature is pulled from `ctx.bodies` and appended innermost (local vertical).
 *
 * Barycenters (`naif-1`…`naif-9`) carry no frame, so the dominant planet
 * (`naif-{X}99`) stands in — e.g. Moon → EMB surfaces Earth.
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
			// index 1 → outermost-to-innermost: [Solar System, …, parent, focused].
			choices.splice(1, 0, { id: chosen.data.id, name: chosen.data.name, probe: probeRef });
		}

		if (cur.data.parentId === SSB_ID) break;
		cur = ctx.getBody(cur.data.parentId);
	}
	// Innermost: focused surface feature (local vertical).
	const feature = ctx.bodies.focusFeature;
	if (feature?.featureAnchor && focused && feature.featureAnchor.hostId === focused.data.id) {
		choices.push({ id: feature.data.id, name: feature.data.name, feature: true });
	}
	// galactic: always first
	choices.splice(0, 0, { id: GALACTIC_REF_ID, name: null });
	return choices;
}
