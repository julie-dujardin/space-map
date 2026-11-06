/**
 * When a sky map must be made again. A map stays good while the camera is near
 * its origin compared with the distance to the nearest dust. The cost follows
 * measured frame time, so a slow device refreshes less often in flight.
 */

import { distanceToBox } from './layout';
import { columnBetween, type NestLevel } from './nest';
import type { Vec3 } from './octahedral';

/** Share of the distance to the nearest structure that the camera may move.
 *  At this share, a stale map errs by 0.07 mag or less for 99% of the stars. */
export const REFRESH_SHARE = 0.01;
/** Column (mag) that makes a structure. */
const STRUCTURE_MAG = 0.02;
/** Distances (pc) tested along each ray. */
const STRUCTURE_FROM_PC = 1;
const STRUCTURE_TO_PC = 40_000;
const STRUCTURE_GROWTH = 1.5;
const STRUCTURE_RAYS = 64;
/** A camera inside dense dust does not refresh at each small move. */
const MIN_STRUCTURE_PC = 5;

/** Rays spread evenly on the sphere. */
function fibonacciRays(count: number): Vec3[] {
	const golden = Math.PI * (3 - Math.sqrt(5));
	return Array.from({ length: count }, (_, i) => {
		const z = 1 - (2 * (i + 0.5)) / count;
		const r = Math.sqrt(1 - z * z);
		return [Math.cos(golden * i) * r, Math.sin(golden * i) * r, z];
	});
}

const RAYS = fibonacciRays(STRUCTURE_RAYS);

/** Distance (pc) from `origin` to the nearest dust, on nest axes. Outside the
 *  box of the data it is at least the distance to the box, so the reach of a
 *  far camera grows with it. */
export function nearestStructure(levels: readonly NestLevel[], origin: Vec3): number {
	let nearest = STRUCTURE_TO_PC;
	for (const ray of RAYS) {
		let sum = 0;
		let from = origin;
		for (let t = STRUCTURE_FROM_PC; t < nearest; t *= STRUCTURE_GROWTH) {
			const to: Vec3 = [origin[0] + ray[0] * t, origin[1] + ray[1] * t, origin[2] + ray[2] * t];
			sum += columnBetween(levels, from, to, 2);
			from = to;
			if (sum >= STRUCTURE_MAG) {
				nearest = t;
				break;
			}
		}
	}
	return Math.max(nearest, distanceToBox(origin), MIN_STRUCTURE_PC);
}

/** Distance (pc) the camera may move from an origin. */
export function refreshReach(structurePc: number): number {
	return REFRESH_SHARE * structurePc;
}

/** Frame time (ms) over which refreshes come less often. */
const SLOW_FRAME_MS = 34;
/** Frame time (ms) under which they come more often. */
const FAST_FRAME_MS = 22;
const FIRST_INTERVAL_MS = 100;
const MAX_INTERVAL_MS = 1600;
/** Share of each new frame in the running mean. */
const FRAME_EASE = 0.2;

/** The least time between two refreshes, from measured frame time. */
export class RefreshPacer {
	private frameMs = 0;
	private lastMs = -Infinity;
	intervalMs = 0;

	/** Note one frame's length, on a frame that follows a refresh. */
	note(frameMs: number): void {
		if (frameMs <= 0) return;
		this.frameMs =
			this.frameMs === 0 ? frameMs : this.frameMs + (frameMs - this.frameMs) * FRAME_EASE;
		if (this.frameMs > SLOW_FRAME_MS) {
			this.intervalMs = Math.min(Math.max(this.intervalMs * 2, FIRST_INTERVAL_MS), MAX_INTERVAL_MS);
		} else if (this.frameMs < FAST_FRAME_MS) {
			this.intervalMs = this.intervalMs > FIRST_INTERVAL_MS ? this.intervalMs / 2 : 0;
		}
	}

	due(nowMs: number): boolean {
		return nowMs - this.lastMs >= this.intervalMs;
	}

	refreshed(nowMs: number): void {
		this.lastMs = nowMs;
	}
}
