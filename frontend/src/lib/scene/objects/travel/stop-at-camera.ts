import type { Vector3 } from 'three';

/** How far sample `i` is ahead of the camera. */
function depthAt(positions: Float32Array, i: number, eye: Vector3, ahead: Vector3): number {
	return (
		(positions[i * 3] - eye.x) * ahead.x +
		(positions[i * 3 + 1] - eye.y) * ahead.y +
		(positions[i * 3 + 2] - eye.z) * ahead.z
	);
}

/** Put samples `from` to `to` on one point of the segment between `kept` and `gone`,
 *  `clearance` ahead of the camera. */
function collapse(
	positions: Float32Array,
	kept: number,
	gone: number,
	from: number,
	to: number,
	eye: Vector3,
	ahead: Vector3,
	clearance: number
): void {
	const keptDepth = depthAt(positions, kept, eye, ahead);
	const goneDepth = depthAt(positions, gone, eye, ahead);
	const share = Math.max(0, (keptDepth - clearance) / (keptDepth - goneDepth));
	const kx = positions[kept * 3];
	const ky = positions[kept * 3 + 1];
	const kz = positions[kept * 3 + 2];
	const x = kx + (positions[gone * 3] - kx) * share;
	const y = ky + (positions[gone * 3 + 1] - ky) * share;
	const z = kz + (positions[gone * 3 + 2] - kz) * share;
	for (let i = from; i < to; i++) {
		positions[i * 3] = x;
		positions[i * 3 + 1] = y;
		positions[i * 3 + 2] = z;
	}
}

/**
 * Stop a line at the camera plane where it runs on behind it to its end. A fat line
 * takes its width on screen, and a vertex behind the camera has no place there, so a
 * long segment across that plane opens out into a wedge. A crossing does this when
 * the camera is on or near it. The stretches left behind collapse to one point. This
 * runs for every line on every frame, so it allocates nothing.
 */
export function stopAtCamera(
	positions: Float32Array,
	count: number,
	eye: Vector3,
	ahead: Vector3,
	clearance: number
): void {
	if (depthAt(positions, 0, eye, ahead) > 0 && depthAt(positions, count - 1, eye, ahead) > 0) {
		return;
	}
	let first = 0;
	while (first < count && depthAt(positions, first, eye, ahead) <= 0) first++;
	if (first === count) return;
	let last = count - 1;
	while (depthAt(positions, last, eye, ahead) <= 0) last--;
	if (first > 0) collapse(positions, first, first - 1, 0, first, eye, ahead, clearance);
	if (last < count - 1) {
		collapse(positions, last, last + 1, last + 1, count, eye, ahead, clearance);
	}
}
