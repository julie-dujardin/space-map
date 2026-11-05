/** The `&north=` refs. Each is relative to the subject the path names, so it
 *  repeats nothing the URL holds: galactic north, the north of the body or the
 *  feature in view, or of the body's ancestor `n` steps up (`parent`,
 *  `parent-2`, …). The planetary system's north is the default and has none. */
export const GALACTIC_REF_ID = 'galactic';
export const BODY_REF = 'body';
export const FEATURE_REF = 'feature';
const PARENT_REF = 'parent';
const PARENT_REF_N = /^parent-([2-9]|[1-9]\d+)$/;

/** The ref of the ancestor `steps` up, 1 being the parent. */
export function parentRef(steps: number): string {
	return steps === 1 ? PARENT_REF : `${PARENT_REF}-${steps}`;
}

/** How many steps up the ancestor `ref` names, or null when it names none. */
export function parentSteps(ref: string): number | null {
	if (ref === PARENT_REF) return 1;
	const m = PARENT_REF_N.exec(ref);
	return m ? Number(m[1]) : null;
}

/** The `&north=` ref, or null for anything that names no choice. */
export function parseNorth(raw: string | null): string | null {
	if (raw === null) return null;
	const named = raw === GALACTIC_REF_ID || raw === BODY_REF || raw === FEATURE_REF;
	return named || parentSteps(raw) !== null ? raw : null;
}
