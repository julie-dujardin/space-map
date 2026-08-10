/** The colour a hazard is drawn in, in one place so the chip in the panel and
 *  the stretch of arc it refers to cannot say different things about it. */

import type { HazardSeverity } from './hazards';

export const HAZARD_COLORS: Record<HazardSeverity, string> = {
	// Deliberately not grey: a notice is still something the trip does, and a
	// stretch of arc that reads as furniture would be pointless to draw.
	notice: '#8ab4f8',
	caution: '#f2b23e',
	severe: '#ff6b5a'
};
