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
/** Farthest a mitred corner reaches from the line's middle, in half widths,
 *  before it is bevelled instead: SVG's default. */
const MITER_LIMIT = 4;

/**
 * Fat-line shader: same alpha logic as {@link makeTrailMaterial}, but draws
 * each segment of `makeFatTrailGeometry` as a quad `uLineWidth` pixels wide on
 * screen, cut where it passes behind the camera. Neighbouring quads meet on a
 * mitre, so a see-through line has no overlap or notch where it turns. With
 * `dash`, a dash and a gap in pixels, it also reads how far along the line each
 * point is on screen.
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
			attribute vec3 corner;
			attribute vec3 segPrev;
			attribute vec3 segStart;
			attribute vec3 segEnd;
			attribute vec3 segNext;
			attribute vec2 alphaStart;
			attribute vec2 alphaEnd;
			varying float vAlpha;
			#ifdef DASHED
			attribute float distStart;
			attribute float distEnd;
			varying float vDistW;
			varying float vW;
			#endif
			vec3 toView(vec3 point) {
				return mat3(viewMatrix) * (point + uCenterOffset);
			}
			vec2 toPx(vec3 view) {
				vec4 clip = projectionMatrix * vec4(view, 1.0);
				return clip.xy / clip.w * uResolution * 0.5;
			}
			// The unit direction on screen from one point to another, with the
			// distance in pixels in z.
			vec3 heading(vec2 from, vec2 to) {
				vec2 d = to - from;
				// Scaled before normalising: an end cut just ahead of the camera can
				// sit 1e20 px off screen, and its square overflows a float.
				float span = max(abs(d.x), abs(d.y));
				// Seen end on: any direction will do.
				if (span < 1e-4) return vec3(1.0, 0.0, 0.0);
				vec2 u = d / span;
				return vec3(normalize(u), span * length(u));
			}
			// The screen headings into and out of the middle of three points. Both
			// segments at a turn call this with the same points, so they place
			// their shared corners alike.
			void turnAt(vec3 before, vec3 at, vec3 after, out vec3 din, out vec3 dout) {
				vec2 p = toPx(toView(at));
				din = heading(toPx(toView(before)), p);
				dout = heading(p, toPx(toView(after)));
			}
			// A mitred corner: its offset, and how far along the quad's own
			// segment it moves.
			vec3 mitredAt(vec2 offset, vec2 own) {
				return vec3(offset, dot(offset, own));
			}
			// This corner's offset in pixels from the point where the line turns
			// from din to dout, and in z how far it moves along the quad's own
			// segment, own. The quads either side compute it from the same three
			// points, so they meet exactly. A square end, the fallback, moves
			// nothing along: exactly nothing, since a dash can end right there.
			vec3 cornerAt(vec3 din, vec3 dout, vec2 own, bool joins) {
				float h = uLineWidth * 0.5;
				vec3 square = vec3(vec2(-own.y, own.x) * corner.x * h, 0.0);
				bool bevel = corner.z > 0.5;
				if (!joins || din.z == 0.0 || dout.z == 0.0) return bevel ? vec3(0.0) : square;
				float inner = din.x * dout.y - din.y * dout.x >= 0.0 ? 1.0 : -1.0;
				vec2 bisector = din.xy + dout.xy;
				// The cosine of half the turn.
				float cosHalf = length(bisector) * 0.5;
				float safeCos = max(cosHalf, 1e-6);
				vec2 mitre = vec2(-bisector.y, bisector.x) / (2.0 * safeCos) * (h / safeCos);
				// How far along each segment the inner corner moves. Past half the
				// shorter segment it would cross that segment's other corner, and
				// square ends overlap instead, as with no join.
				float reach = h * sqrt(max(1.0 - cosHalf * cosHalf, 0.0)) / safeCos;
				bool fits = cosHalf > 1e-3 && reach <= 0.5 * min(din.z, dout.z);
				bool mitred = fits && cosHalf * ${MITER_LIMIT.toFixed(1)} >= 1.0;
				if (bevel) {
					// Each segment's square outer corner and the inner corner they
					// share, at the turn's own distance along the line. Flat under a
					// mitre, which covers the turn by itself, and beside a segment
					// shorter than the line is wide, where it could reach into the
					// quad past that segment.
					if (mitred || (!fits && min(din.z, dout.z) < uLineWidth)) return vec3(0.0);
					if (corner.z < 1.5) return vec3(-inner * vec2(-din.y, din.x) * h, 0.0);
					if (corner.z < 2.5) return vec3(-inner * vec2(-dout.y, dout.x) * h, 0.0);
					return vec3(fits ? inner * mitre : vec2(0.0), 0.0);
				}
				if (!fits) return square;
				if (corner.x == inner) return mitredAt(inner * mitre, own);
				return mitred ? mitredAt(-inner * mitre, own) : square;
			}
			void main() {
				vec3 a = toView(segStart);
				vec3 b = toView(segEnd);
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
				bool atEnd = corner.y > 0.5;
				vec3 own = heading(toPx(a), toPx(b));
				// The turn this corner sits on, read in the line's direction: only
				// with all three of its points ahead of the camera, so that both
				// segments at the turn agree on it.
				bool joins = cutA == 0.0 && cutB == 0.0 && -toView(atEnd ? segNext : segPrev).z >= uTrim.x;
				vec3 din = own;
				vec3 dout = own;
				if (joins) {
					if (atEnd) turnAt(segStart, segEnd, segNext, din, dout);
					else turnAt(segPrev, segStart, segEnd, din, dout);
					own = atEnd ? din : dout;
				}
				vec3 offset = cornerAt(din, dout, own.xy, joins);
				vec4 clip = projectionMatrix * vec4(atEnd ? b : a, 1.0);
				gl_Position = vec4((clip.xy / clip.w + offset.xy * 2.0 / uResolution) * clip.w, clip.zw);
				vec2 alphas = atEnd ? mix(alphaEnd, alphaStart, cutB) : mix(alphaStart, alphaEnd, cutA);
				vAlpha = mix(alphas.x, alphas.y, uShowFull);
				#ifdef DASHED
				// Carried times w and divided back out per fragment, which undoes
				// the perspective a varying is interpolated with: the dashes are
				// even on screen however much nearer one end is. A corner a mitre
				// moves along the segment counts on by as much, so dash ends stay
				// square to the line.
				float dist = atEnd ? mix(distEnd, distStart, cutB) : mix(distStart, distEnd, cutA);
				dist += offset.z;
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
