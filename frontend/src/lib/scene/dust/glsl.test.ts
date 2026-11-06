import { describe, expect, it } from 'vitest';
import { glslFloat, glslVec3 } from './glsl';

/** A GLSL ES 3.00 float literal, with a leading minus for the unary operator. */
const LITERAL = /^-?(\d+\.\d*|\.\d+|\d+(\.\d*)?e[+-]?\d+)$/;

describe('a GLSL float literal', () => {
	it.each([0, -2.5, 3, 20_000, 1e-10, 9.6e-10 / 16, 1e20, 0.1, Math.PI, -1 / 3])(
		'of %s is valid and holds the float32 exactly',
		(x) => {
			const text = glslFloat(x);
			expect(text).toMatch(LITERAL);
			expect(Math.fround(Number(text))).toBe(Math.fround(x));
		}
	);

	it('keeps integers short and small values whole', () => {
		expect(glslFloat(0)).toBe('0.0');
		expect(glslFloat(3)).toBe('3.0');
		expect(glslFloat(-2.5)).toBe('-2.5');
		expect(glslFloat(1e-10)).toBe('1e-10');
		expect(glslFloat(9.6e-10 / 16)).toBe('6e-11');
	});

	it('refuses a value with no literal', () => {
		expect(() => glslFloat(Infinity)).toThrow();
		expect(() => glslFloat(NaN)).toThrow();
		expect(() => glslFloat(1e39)).toThrow();
	});

	it('makes a vec3 of three of them', () => {
		expect(glslVec3([1, 0.5, -1e-12])).toBe('vec3(1.0, 0.5, -1e-12)');
	});
});
