import { Vector3 } from 'three';
import type { PositionedBody } from '$lib/types/objects';
import { bodyQuaternion } from '$lib/math/orientation';
import type { ContextManager } from '$lib/scene/context-manager.svelte';

/**
 * A camera "north" reference. `id === null` is the always-available
 * solar-system option (ecliptic Y, scene frame). For body refs, `id` is the
 * body id and `name` is the display label resolved at choice-build time.
 */
export interface NorthChoice {
	id: string | null;
	name: string | null;
}

const SCENE_UP = new Vector3(0, 1, 0);

/**
 * Unit vector pointing toward the body's IAU north pole, in scene frame.
 * Falls back to scene Y if the body has no orientation data — callers should
 * filter those out via {@link getNorthChoices} before invoking, but we keep
 * the fallback so the renderer survives a stale id.
 */
export function bodyNorthVector(body: PositionedBody, jd: number, out?: Vector3): Vector3 {
	const target = out ?? new Vector3();
	if (!body.orientation) return target.copy(SCENE_UP);
	const q = bodyQuaternion(body.orientation, jd, body.nutPrec);
	return target.copy(SCENE_UP).applyQuaternion(q).normalize();
}

/**
 * Walks focused → ancestors via `parentId`, collecting every body with
 * orientation data, and appends solar-system as the always-present fallback.
 * Stops at the SSB (`naif-0`). Caller hides the selector when length ≤ 1.
 *
 * Planetary barycenters (NAIF id `naif-1`…`naif-9`) carry no rotational
 * frame, so the SPICE convention's dominant planet (`naif-{X}99`) is
 * substituted in their place — e.g. walking up from the Moon
 * (Moon → EMB → SSB) surfaces Earth as the EMB stand-in.
 */
const BARY_PATTERN = /^naif-([1-9])$/;

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
		const baryMatch = cur.data.id.match(BARY_PATTERN);
		if (baryMatch) {
			const planet = ctx.getBody(`naif-${baryMatch[1]}99`);
			if (planet) chosen = planet;
		}
		if (chosen.orientation && !choices.some((c) => c.id === chosen.data.id)) {
			// Insert at index 1 so the result reads outermost → innermost:
			// [Solar System, Sun, …, parent, focused].
			choices.splice(1, 0, { id: chosen.data.id, name: chosen.data.name });
		}

		if (cur.data.parentId === 'naif-0') break;
		cur = ctx.getBody(cur.data.parentId);
	}
	return choices;
}
