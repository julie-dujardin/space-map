/**
 * Global depth-buffer mode. Reversed-Z (EXT_clip_control + float32 depth)
 * changes the projected-NDC depth range from [-1, 1] to [1 (near) → 0 (far)],
 * and off-frustum points land below 0 instead of above 1 — CPU-side
 * projected-z gates must branch on the active mode.
 */
import { ShaderChunk } from 'three';

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

/** log2 of the smallest eye distance (scene units, ~1 mm) the logarithmic
 *  fallback resolves. */
const LOG_DEPTH_FLOOR = -44;

/**
 * Replace three's logarithmic-depth chunks, whose `1.0 + w` rounds away every
 * distance under ~1 km in float32 — a sub-km body then has no depth test at
 * all. Taking log2(w) directly keeps precision relative to distance.
 */
export function installLogDepthChunks(): void {
	ShaderChunk.logdepthbuf_vertex = /* glsl */ `
#ifdef USE_LOGARITHMIC_DEPTH_BUFFER
	vFragDepth = gl_Position.w;
	vIsPerspective = float( isPerspectiveMatrix( projectionMatrix ) );
#endif
`;
	// logDepthBufFC = 2 / log2(far + 1), so depth spans [floor, far] → [0, 1].
	ShaderChunk.logdepthbuf_fragment = /* glsl */ `
#if defined( USE_LOGARITHMIC_DEPTH_BUFFER )
	gl_FragDepth = vIsPerspective == 0.0
		? gl_FragCoord.z
		: max( log2( vFragDepth ) - ${LOG_DEPTH_FLOOR.toFixed(1)}, 0.0 ) / ( 2.0 / logDepthBufFC - ${LOG_DEPTH_FLOOR.toFixed(1)} );
#endif
`;
}

/** GLSL expression for the eye distance behind a logarithmic depth sample. */
export function logDepthToEyeGlsl(depth: string, far: string): string {
	const floor = LOG_DEPTH_FLOOR.toFixed(1);
	return `exp2(${depth} * (log2(${far} + 1.0) - ${floor}) + ${floor})`;
}
