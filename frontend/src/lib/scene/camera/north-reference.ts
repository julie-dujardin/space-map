import { Vector3 } from 'three';
import type { PositionedBody } from '$lib/types/objects';
import { bodyQuaternion } from '$lib/math/orientation';
import { EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { isModelBearing } from '$lib/scene/objects/body/model';
import { SSB_ID, dominantPlanetId } from '$lib/constants';
import { isExtrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { BODY_REF, FEATURE_REF, GALACTIC_REF_ID, parentRef, parentSteps } from '$lib/state/north';

/**
 * Camera "north" reference. `id === null` → ecliptic Y; `GALACTIC_REF_ID` →
 * galactic pole; `plane` → the orbital plane of an extrasolar system; else a
 * body id (`name` its label). `probe`/`feature` pick model-up or local vertical
 * instead of the IAU pole. `ref` is how the URL names it (see `$lib/state/north`);
 * null for the planetary system, the default.
 */
export interface NorthChoice {
	id: string | null;
	name: string | null;
	ref: string | null;
	probe?: boolean;
	feature?: boolean;
	plane?: boolean;
}

/** Id prefix of an extrasolar system's plane, before the object it frames. */
export const PLANE_REF_PREFIX = 'plane:';

/** Scene-frame +Y. Shared by the camera-up controller and body-pole math. */
export const SCENE_UP = new Vector3(0, 1, 0);

/**
 * Galactic north pole (IAU 1958 J2000, α=192.85948° δ=27.12825°) in the scene
 * frame, converted the same way as body IAU poles for consistency.
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
 * Unit "north" for a body: IAU pole at `jd` when oriented; local zenith when
 * landed or a focused feature; else a probe's static model-up (base frame
 * only — attitude would tumble the camera on spinners). Falls back to scene Y.
 */
export function bodyNorthVector(
	body: PositionedBody,
	jd: number,
	out?: Vector3,
	landed = false
): Vector3 {
	const target = out ?? new Vector3();
	if (!body.orientation) {
		if (landed && body.orbitCenter && body.position) {
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
 * `focused` and each body up from it to the SSB, with its steps up and the
 * body whose north it gives: a barycentre carries no frame, so its planet
 * does. The choices and the URL's `parent-n` refs both count steps here, so a
 * ref the list offers is one that holds.
 */
function* lineage(
	focused: PositionedBody | undefined,
	ctx: ContextManager
): Generator<{ steps: number; body: PositionedBody; north: PositionedBody }> {
	const seen = new Set<string>();
	let cur = focused;
	for (let steps = 0; cur && !seen.has(cur.data.id); steps++) {
		seen.add(cur.data.id);
		const planetId = dominantPlanetId(cur.data.id);
		const planet = planetId ? ctx.getBody(planetId) : undefined;
		yield { steps, body: cur, north: planet ?? cur };
		if (cur.data.parentId === SSB_ID) return;
		cur = ctx.getBody(cur.data.parentId);
	}
}

/**
 * The orientation-bearing bodies of `focused`'s {@link lineage} and the
 * planetary system of the place: the J2000 ecliptic in the solar system, else
 * the system's orbital plane when it has drawn orbits. The caller hides the
 * selector when length ≤ 1. A focused probe is its own ref; a focused feature
 * (reported via its host, see Scene.svelte) is appended innermost.
 */
export function getNorthChoices(
	focused: PositionedBody | undefined,
	ctx: ContextManager
): NorthChoice[] {
	const choices: NorthChoice[] = [];
	if (focused && isExtrasolarObjectId(focused.data.id)) {
		// The planets' host, or the node whose pair is drawn.
		const host = focused.exoplanet ? ctx.getBody(focused.data.parentId) : focused;
		if (ctx.exoplanets.planeNormal(focused.data.id)) {
			choices.push({
				id: PLANE_REF_PREFIX + focused.data.id,
				name: host?.data.name ?? focused.data.name,
				ref: null,
				plane: true
			});
		}
	} else {
		choices.push({ id: null, name: null, ref: null });
	}
	const firstAncestor = choices.length;
	for (const { steps, body, north } of lineage(focused, ctx)) {
		const probeRef = steps === 0 && !north.orientation && isModelBearing(body);
		if ((north.orientation || probeRef) && !choices.some((c) => c.id === north.data.id)) {
			// Outermost-to-innermost: [system, …, parent, focused].
			choices.splice(firstAncestor, 0, {
				id: north.data.id,
				name: north.data.name,
				ref: steps === 0 ? BODY_REF : parentRef(steps),
				probe: probeRef
			});
		}
	}
	// Innermost: focused surface feature (local vertical).
	const feature = ctx.bodies.focusFeature;
	if (feature?.featureAnchor && focused && feature.featureAnchor.hostId === focused.data.id) {
		choices.push({ id: feature.data.id, name: feature.data.name, ref: FEATURE_REF, feature: true });
	}
	// galactic: always first
	choices.splice(0, 0, { id: GALACTIC_REF_ID, name: null, ref: GALACTIC_REF_ID });
	return choices;
}

/** The choice the planetary system stands for when the URL names none: the
 *  system's, else galactic, as a lone star has no plane. */
export function defaultNorthChoice(choices: readonly NorthChoice[]): NorthChoice {
	return choices.find((c) => c.ref === null) ?? choices[0];
}

/** The choice `ref` names, else the default one: a body's spin, a feature or
 *  a system's plane can land after the URL that names it. */
export function resolveNorthChoice(
	choices: readonly NorthChoice[],
	ref: string | null
): NorthChoice {
	return choices.find((c) => c.ref === ref) ?? defaultNorthChoice(choices);
}

/**
 * Whether `ref` can still name a choice for the view on `focused` once what it
 * needs has loaded: galactic and the body's own north always can, a feature's
 * only while a feature is in the view, an ancestor's while the body has one
 * that many steps up, other than a body nearer: a barycentre stands for its
 * planet, so Earth has no parent of its own.
 */
export function northRefHolds(
	ref: string,
	focused: PositionedBody,
	hasFeature: boolean,
	ctx: ContextManager
): boolean {
	if (ref === GALACTIC_REF_ID || ref === BODY_REF) return true;
	if (ref === FEATURE_REF) return hasFeature;
	const steps = parentSteps(ref);
	if (steps === null) return false;
	const nearer = new Set<string>();
	for (const up of lineage(focused, ctx)) {
		if (up.steps === steps) return !nearer.has(up.north.data.id);
		nearer.add(up.north.data.id);
	}
	return false;
}
