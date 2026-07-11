// Unicode LRI…PDI (U+2066/U+2069) built at runtime so no bidi control char ends
// up in source — Svelte's compiler warns on literal ones (even `\u` escapes).
const LRI = String.fromCharCode(0x2066);
const PDI = String.fromCharCode(0x2069);

/** Isolate a numeric/math run (e.g. "≥ 5 km", "10 – 20 km") as LTR so its digits,
 *  signs and brackets don't reorder or mirror when embedded in RTL text. */
export function ltrIsolate(s: string): string {
	return `${LRI}${s}${PDI}`;
}
