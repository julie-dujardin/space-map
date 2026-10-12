import { ShaderMaterial, type IUniform } from 'three';
import type { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';

/** Scene pixels a texel of the bright target sums on one axis, at most: a
 *  bound for the loop if that target is ever far smaller than the scene. */
const MAX_SPAN = 16;

/**
 * Give the bloom a bright pass that keeps the light of a small source.
 * three's pass thresholds one bilinear read per texel of a target 2 to 5 times
 * coarser than the scene: a source of a few pixels (the Sun from far) is read
 * in full, in part or not at all as it moves, and its glow flickers. This one
 * thresholds each scene pixel, then gives each texel the pixels under it by
 * the area they share.
 */
export function installBloomHighPass(pass: UnrealBloomPass): void {
	pass.materialHighPassFilter.dispose();
	pass.materialHighPassFilter = new ShaderMaterial({
		uniforms: pass.highPassUniforms as Record<string, IUniform>,
		vertexShader: /* glsl */ `
			varying vec2 vUv;
			void main() {
				vUv = uv;
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}
		`,
		fragmentShader: /* glsl */ `
			uniform sampler2D tDiffuse;
			uniform float luminosityThreshold;
			uniform float smoothWidth;
			varying vec2 vUv;
			void main() {
				vec2 size = vec2(textureSize(tDiffuse, 0));
				vec2 span = size * abs(vec2(dFdx(vUv.x), dFdy(vUv.y)));
				vec2 lo = vUv * size - 0.5 * span;
				vec2 hi = lo + span;
				// A sliver of a pixel is rounding, not light.
				ivec2 first = max(ivec2(floor(lo + 0.001)), ivec2(0));
				ivec2 last = min(ivec2(ceil(hi - 0.001)) - 1, ivec2(size) - 1);
				last = min(last, first + ${MAX_SPAN - 1});
				vec3 sum = vec3(0.0);
				for (int y = first.y; y <= last.y; y++) {
					float wy = min(float(y) + 1.0, hi.y) - max(float(y), lo.y);
					for (int x = first.x; x <= last.x; x++) {
						float wx = min(float(x) + 1.0, hi.x) - max(float(x), lo.x);
						vec3 texel = texelFetch(tDiffuse, ivec2(x, y), 0).rgb;
						float taken = smoothstep(
							luminosityThreshold, luminosityThreshold + smoothWidth, luminance(texel));
						sum += texel * (taken * wx * wy);
					}
				}
				gl_FragColor = vec4(sum / (span.x * span.y), 1.0);
			}
		`
	});
}
