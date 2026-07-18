/**
 * Global depth-buffer mode. Reversed-Z (EXT_clip_control + float32 depth)
 * changes the projected-NDC depth range from [-1, 1] to [1 (near) → 0 (far)],
 * and off-frustum points land below 0 instead of above 1 — CPU-side
 * projected-z gates must branch on the active mode.
 */
let reversed = false;

export function setReversedDepth(v: boolean): void {
	reversed = v;
}

export function isReversedDepth(): boolean {
	return reversed;
}

/** Whether a projected NDC z lies within the visible depth range. */
export function ndcZVisible(z: number): boolean {
	return reversed ? z >= 0 && z <= 1 : z >= -1 && z <= 1;
}
