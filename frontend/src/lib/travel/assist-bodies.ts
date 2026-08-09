/**
 * Bodies worth swinging past on the way somewhere else.
 *
 * A frontend constant rather than export data: what makes a useful assist body
 * is having enough mass to bend a trajectory and sitting where trips cross, and
 * that is a judgement about this feature rather than a fact about the body. The
 * five here cover every pair the planner offers — Venus for the inner system,
 * Jupiter for everything past it — and each one costs its own search, so the
 * list is deliberately short rather than "every planet".
 *
 * Ids are the planets, not their barycentres: the pass is priced against the
 * planet's own mass and radius, and `toTravelBody` walks up to the barycentre
 * for the heliocentric orbit by itself.
 */

export const ASSIST_BODY_IDS: readonly string[] = [
	'naif-299',
	'naif-399',
	'naif-499',
	'naif-599',
	'naif-699'
];
