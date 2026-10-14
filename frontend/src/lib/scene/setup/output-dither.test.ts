/**
 * The dither lands in three's output shader after the sRGB encode. A string
 * replace that finds no anchor fails with no error, so a change in three's
 * shader text shows here.
 */

import { describe, expect, it } from 'vitest';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { installOutputDither } from './output-dither';

describe('installOutputDither', () => {
	it('declares the dither and calls it as the last statement', () => {
		const pass = new OutputPass();
		installOutputDither(pass);
		const src = pass.material.fragmentShader;
		const declared = src.indexOf('vec3 outputDither(');
		const encoded = src.lastIndexOf('sRGBTransferOETF(');
		const called = src.indexOf('gl_FragColor.rgb = outputDither(gl_FragColor.rgb);');
		expect(declared).toBeGreaterThan(src.indexOf('#include <colorspace_pars_fragment>'));
		expect(declared).toBeLessThan(src.indexOf('void main()'));
		expect(called).toBeGreaterThan(encoded);
		expect(src.slice(called).replace(/\s/g, '')).toBe(
			'gl_FragColor.rgb=outputDither(gl_FragColor.rgb);}'
		);
	});
});
