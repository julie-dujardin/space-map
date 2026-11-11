import { Color, DoubleSide, ShaderMaterial, Vector2, Vector3 } from 'three';
import { CAMERA_NEAR } from '$lib/scene/setup/camera-near';

// Trails read as the body's halo colour under ACES; scale down so they're a
// darker shade, not a match. Planned trajectories pass their own scale — they
// are what's being read, not furniture.
const TRAIL_DIM = 0.5;

function overlayColor(color: string, scale: number): Color {
	return new Color(color).multiplyScalar(scale);
}

// Shared by every fat trail material so resize() updates them all at once;
// Three.js compares uniforms by reference, not snapshot.
const TRAIL_RESOLUTION = new Vector2(1, 1);

/** Update the screen resolution used by fat trails for screen-space line expansion. */
export function setTrailResolution(width: number, height: number): void {
	TRAIL_RESOLUTION.set(width, height);
}

export function makeTrailMaterial(color: string, brightness = TRAIL_DIM): ShaderMaterial {
	return new ShaderMaterial({
		transparent: true,
		// Transparent line must not write depth, or it culls clouds/point clouds behind it.
		depthWrite: false,
		uniforms: {
			uColor: { value: overlayColor(color, brightness) },
			uCenterOffset: { value: new Vector3() },
			uAlphaMultiplier: { value: 1.0 },
			uAlphaMin: { value: 0.0 },
			uShowFull: { value: 0.0 }
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			uniform vec3 uCenterOffset;
			uniform float uShowFull;
			attribute float trailAlpha;
			attribute float fullAlpha;
			varying float vAlpha;
			void main() {
				vAlpha = mix(trailAlpha, fullAlpha, uShowFull);
				vec3 relPos = position + uCenterOffset;
				gl_Position = projectionMatrix * vec4(mat3(viewMatrix) * relPos, 1.0);
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <logdepthbuf_pars_fragment>
			uniform vec3 uColor;
			uniform float uAlphaMultiplier;
			uniform float uAlphaMin;
			varying float vAlpha;
			void main() {
				gl_FragColor = vec4(uColor, clamp(max(vAlpha * uAlphaMultiplier, uAlphaMin), 0.0, 1.0));
				#include <logdepthbuf_fragment>
			}
		`
	});
}

/** Depth under which a fat line's end counts as behind the camera, where it has
 *  no place on screen to widen the line from. Inside the near plane, so the GPU
 *  still clips what shows. */
const TRIM_DEPTH = CAMERA_NEAR / 2;
/** How far ahead such an end is cut back to, as a share of the camera's
 *  distance from the basis: some ten times the float32 rounding of a vertex
 *  there, and near enough that a line passing the camera runs off the screen. */
const TRIM_SHARE = 1e-6;

/**
 * Fat-line shader: same alpha logic as {@link makeTrailMaterial}, but draws
 * each segment of `makeFatTrailGeometry` as a quad `uLineWidth` pixels wide on
 * screen, cut where it passes behind the camera. With `dash`, a dash and a gap
 * in pixels, it also reads how far along the line each point is on screen.
 */
export function makeFatTrailMaterial(
	color: string,
	lineWidth: number,
	brightness = TRAIL_DIM,
	dash?: readonly [number, number]
): ShaderMaterial {
	return new ShaderMaterial({
		defines: dash ? { DASHED: '' } : {},
		transparent: true,
		// Transparent line must not write depth, or it culls clouds/point clouds behind it.
		depthWrite: false,
		side: DoubleSide,
		uniforms: {
			uColor: { value: overlayColor(color, brightness) },
			uCenterOffset: { value: new Vector3() },
			uAlphaMultiplier: { value: 1.0 },
			uAlphaMin: { value: 0.0 },
			uShowFull: { value: 0.0 },
			uLineWidth: { value: lineWidth },
			uResolution: { value: TRAIL_RESOLUTION },
			uTrim: { value: new Vector2(TRIM_DEPTH, TRIM_SHARE) },
			uDash: { value: new Vector2(dash?.[0] ?? 0, dash?.[1] ?? 0) }
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			uniform vec3 uCenterOffset;
			uniform float uShowFull;
			uniform float uLineWidth;
			uniform vec2 uResolution;
			uniform vec2 uTrim;
			attribute vec2 corner;
			attribute vec3 segStart;
			attribute vec3 segEnd;
			attribute vec2 alphaStart;
			attribute vec2 alphaEnd;
			varying float vAlpha;
			#ifdef DASHED
			attribute float distStart;
			attribute float distEnd;
			varying float vDistW;
			varying float vW;
			#endif
			void main() {
				vec3 a = mat3(viewMatrix) * (segStart + uCenterOffset);
				vec3 b = mat3(viewMatrix) * (segEnd + uCenterOffset);
				float aheadA = -a.z;
				float aheadB = -b.z;
				float front = max(aheadA, aheadB);
				if (front < uTrim.x) {
					// Wholly behind the camera: every corner on one point draws nothing.
					gl_Position = vec4(0.0, 0.0, -2.0, 1.0);
					vAlpha = 0.0;
					#ifdef DASHED
					vDistW = 0.0;
					vW = 1.0;
					#endif
					return;
				}
				// An end behind the camera moves along the segment to the cut depth,
				// never past the other end. Its depth is set, not interpolated, so
				// rounding cannot put it behind the camera again.
				float cut = min(max(uTrim.x, uTrim.y * length(uCenterOffset)), front);
				float cutA = aheadA < uTrim.x ? (cut - aheadA) / (aheadB - aheadA) : 0.0;
				float cutB = aheadB < uTrim.x ? (cut - aheadB) / (aheadA - aheadB) : 0.0;
				if (cutA > 0.0) a = vec3(mix(a.xy, b.xy, cutA), -cut);
				if (cutB > 0.0) b = vec3(mix(b.xy, a.xy, cutB), -cut);
				vec4 clipA = projectionMatrix * vec4(a, 1.0);
				vec4 clipB = projectionMatrix * vec4(b, 1.0);
				vec2 ndcA = clipA.xy / clipA.w;
				vec2 ndcB = clipB.xy / clipB.w;
				vec2 dirPx = (ndcB - ndcA) * uResolution * 0.5;
				// Scaled before normalising: an end cut just ahead of the camera can
				// sit 1e20 px off screen, and its square overflows a float.
				float span = max(abs(dirPx.x), abs(dirPx.y));
				// A segment seen end on: any perpendicular will do.
				vec2 dirN = span < 1e-4 ? vec2(1.0, 0.0) : normalize(dirPx / span);
				vec2 offsetNDC = vec2(-dirN.y, dirN.x) * corner.x * uLineWidth / uResolution;
				bool atEnd = corner.y > 0.5;
				vec4 clip = atEnd ? clipB : clipA;
				vec2 ndc = atEnd ? ndcB : ndcA;
				gl_Position = vec4((ndc + offsetNDC) * clip.w, clip.zw);
				vec2 alphas = atEnd ? mix(alphaEnd, alphaStart, cutB) : mix(alphaStart, alphaEnd, cutA);
				vAlpha = mix(alphas.x, alphas.y, uShowFull);
				#ifdef DASHED
				// Carried times w and divided back out per fragment, which undoes
				// the perspective a varying is interpolated with: the dashes are
				// even on screen however much nearer one end is.
				float dist = atEnd ? mix(distEnd, distStart, cutB) : mix(distStart, distEnd, cutA);
				vDistW = dist * clip.w;
				vW = clip.w;
				#endif
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <logdepthbuf_pars_fragment>
			uniform vec3 uColor;
			uniform float uAlphaMultiplier;
			uniform float uAlphaMin;
			varying float vAlpha;
			#ifdef DASHED
			uniform vec2 uDash;
			varying float vDistW;
			varying float vW;
			#endif
			void main() {
				#ifdef DASHED
				if (mod(vDistW / vW, uDash.x + uDash.y) > uDash.x) discard;
				#endif
				gl_FragColor = vec4(uColor, clamp(max(vAlpha * uAlphaMultiplier, uAlphaMin), 0.0, 1.0));
				#include <logdepthbuf_fragment>
			}
		`
	});
}
