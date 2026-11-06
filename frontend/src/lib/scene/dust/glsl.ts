/**
 * Numbers as GLSL ES 3.00 literals, for constants in shader text. A literal
 * holds the value's float32 exactly, with the fewest digits that do, so a small
 * value keeps all its digits and never goes to 0.
 */

/** A float literal. It always holds a `.` or an exponent. */
export function glslFloat(x: number): string {
	const f = Math.fround(x);
	if (!Number.isFinite(f)) throw new Error(`glsl: ${x} has no float literal`);
	let text = String(f);
	for (let digits = 1; digits <= 9; digits++) {
		const short = Number(f.toPrecision(digits));
		if (Math.fround(short) === f) {
			text = String(short);
			break;
		}
	}
	return /[.e]/.test(text) ? text : `${text}.0`;
}

export function glslVec3(v: readonly number[]): string {
	return `vec3(${v.map(glslFloat).join(', ')})`;
}
