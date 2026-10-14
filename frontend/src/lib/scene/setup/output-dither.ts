import type { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

/** The hash is "hash without sine" (Dave Hoskins). It gives three uniform
 *  samples for each pixel. It uses only float operations, because three
 *  compiles a raw shader as GLSL ES 1.00. */
const DITHER_GLSL = /* glsl */ `
	vec3 outputDither(vec3 color) {
		// ES 1.00 gives gl_FragCoord at medium precision. Copy it before the arithmetic.
		vec3 p3 = gl_FragCoord.xyx;
		p3 = fract(p3 * vec3(0.1031, 0.1030, 0.0973));
		p3 += dot(p3, p3.yxz + 33.33);
		vec3 u = fract((p3.xxy + p3.yzz) * p3.zyx);
		// The difference of two uniform samples has a triangular distribution on (-1, 1).
		vec3 noise = u - u.yzx;
		// The noise goes to 0 in the last step at each end. Thus black stays black and no value clips.
		vec3 amplitude = clamp(min(color, 1.0 - color) * 255.0, 0.0, 1.0);
		return color + noise * amplitude / 255.0;
	}
`;

/**
 * Add dither to the output pass after the sRGB encode. The canvas has 8 bits
 * for each channel, so a smooth dark gradient shows as bands. Triangular noise
 * of one step for each channel changes the bands into a fine grain. The
 * pattern is static, so an idle scene shows no moving grain.
 */
export function installOutputDither(pass: OutputPass): void {
	pass.material.fragmentShader = pass.material.fragmentShader
		.replace(
			'#include <colorspace_pars_fragment>',
			`#include <colorspace_pars_fragment>\n${DITHER_GLSL}`
		)
		.replace(/}\s*$/, 'gl_FragColor.rgb = outputDither(gl_FragColor.rgb);\n}');
}
