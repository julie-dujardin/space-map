/**
 * Placing the camera from outside. The map's own controls orbit whatever is
 * focused; a hold suspends them so host code can put the camera wherever it
 * likes, frame by frame, and hand it back afterwards.
 */

import { AU_KM, AU_SCALE } from '$lib/math/units';
import { resolveAnchor, type Anchor, type OffsetKm } from './anchor';
import type { Vec3 } from '$lib/scene/animation/math';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

/** Where the camera is and what it looks at. */
export interface CameraPose {
	position: Anchor;
	target: Anchor;
	/** Which way is up, on ecliptic J2000 axes. The ecliptic north pole when
	 *  left out; a pose looking straight along it needs one of its own. */
	up?: OffsetKm;
}

/** A suspension of the map's own camera control, for as long as it is held. */
export interface CameraHold {
	/** Put the camera at `pose` from the next frame on. Call it from the map's
	 *  `frame` event to drive a path. */
	set(pose: CameraPose): void;
	/** Give the camera back to the map, orbiting the focused body from
	 *  wherever the hold left it. */
	release(): void;
	readonly held: boolean;
}

/** Scene units back to kilometres on ecliptic J2000 axes. */
export function sceneToEcliptic(v: Vec3): [number, number, number] {
	const k = AU_KM / AU_SCALE;
	return [v[0] * k, -v[2] * k, v[1] * k];
}

/** The pose as scene-frame vectors for the frame being drawn, or null while
 *  either end names a body that is not loaded. */
export function resolvePose(
	pose: CameraPose,
	ctx: ContextManager,
	jd: number
): { position: Vec3; target: Vec3; up: Vec3 } | null {
	const position = resolveAnchor(pose.position, ctx, jd);
	const target = resolveAnchor(pose.target, ctx, jd);
	if (!position || !target) return null;
	// Ecliptic axes to scene axes, without the length scaling a position needs.
	const [ux, uy, uz] = pose.up ?? [0, 0, 1];
	return { position, target, up: [ux, uz, -uy] };
}

/** Distance from the camera to what it is looking at, which is what the
 *  quality and label passes mean by "how far away is this". */
export function poseDistance(position: Vec3, target: Vec3): number {
	return Math.hypot(position[0] - target[0], position[1] - target[1], position[2] - target[2]);
}
