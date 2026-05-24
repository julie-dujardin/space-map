import { Color, DoubleSide, ShaderMaterial, Vector2, Vector3 } from 'three';

// Trails read directly as the body's halo colour under ACES; scale down so
// they render as a darker shade rather than matching the halo.
function overlayColor(color: string): Color {
	return new Color(color).multiplyScalar(0.5);
}

// Shared between every fat trail material so resize() updates them all in
// one place. Mutating this Vector2 propagates to every material that holds it
// as a uniform value (Three.js compares by reference, not by snapshot).
const TRAIL_RESOLUTION = new Vector2(1, 1);

/** Update the screen resolution used by fat trails for screen-space line expansion. */
export function setTrailResolution(width: number, height: number): void {
	TRAIL_RESOLUTION.set(width, height);
}

export function makeTrailMaterial(color: string): ShaderMaterial {
	return new ShaderMaterial({
		transparent: true,
		uniforms: {
			uColor: { value: overlayColor(color) },
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

/**
 * Fat-line shader: same precision/alpha logic as {@link makeTrailMaterial},
 * but expands each segment to a screen-space quad of width `uLineWidth` pixels.
 *
 * Geometry is indexed triangles built by `makeFatTrailGeometry` in ./geometry:
 * each logical point is duplicated into a (-1, +1) side pair, and `nextPosition`
 * carries the segment's other endpoint so the shader can compute screen-space
 * direction without an extra draw call.
 */
export function makeFatTrailMaterial(color: string, lineWidth: number): ShaderMaterial {
	return new ShaderMaterial({
		transparent: true,
		side: DoubleSide,
		uniforms: {
			uColor: { value: overlayColor(color) },
			uCenterOffset: { value: new Vector3() },
			uAlphaMultiplier: { value: 1.0 },
			uAlphaMin: { value: 0.0 },
			uShowFull: { value: 0.0 },
			uLineWidth: { value: lineWidth },
			uResolution: { value: TRAIL_RESOLUTION }
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			uniform vec3 uCenterOffset;
			uniform float uShowFull;
			uniform float uLineWidth;
			uniform vec2 uResolution;
			attribute vec3 nextPosition;
			attribute float side;
			attribute float trailAlpha;
			attribute float fullAlpha;
			varying float vAlpha;
			void main() {
				vAlpha = mix(trailAlpha, fullAlpha, uShowFull);
				vec3 currRel = position + uCenterOffset;
				vec3 nextRel = nextPosition + uCenterOffset;
				vec4 currClip = projectionMatrix * vec4(mat3(viewMatrix) * currRel, 1.0);
				vec4 nextClip = projectionMatrix * vec4(mat3(viewMatrix) * nextRel, 1.0);
				vec2 currNDC = currClip.xy / currClip.w;
				vec2 nextNDC = nextClip.xy / nextClip.w;
				vec2 dirPx = (nextNDC - currNDC) * uResolution * 0.5;
				// Endpoint vertex (or zero-length segment): pick an arbitrary perpendicular
				// so the side pair doesn't collapse onto each other and vanish.
				if (length(dirPx) < 1e-4) dirPx = vec2(1.0, 0.0);
				vec2 dirN = normalize(dirPx);
				vec2 perp = vec2(-dirN.y, dirN.x) * side * uLineWidth * 0.5;
				vec2 offsetNDC = perp / (uResolution * 0.5);
				gl_Position = vec4((currNDC + offsetNDC) * currClip.w, currClip.zw);
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
