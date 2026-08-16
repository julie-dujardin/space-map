/**
 * Bodies worth swinging past on the way somewhere else.
 *
 * A frontend constant rather than export data: what makes one useful is a
 * judgement about this feature, not a fact about the body. Kept deliberately
 * short — Venus for the inner system, Jupiter for everything past it — since
 * each one costs its own search.
 *
 * Ids are the planets, not their barycentres: the pass is priced against the
 * planet's own mass and radius, and `toTravelBody` finds the barycentre for
 * the heliocentric orbit by itself.
 */

export const ASSIST_BODY_IDS: readonly string[] = [
	'naif-299',
	'naif-399',
	'naif-499',
	'naif-599',
	'naif-699'
];
