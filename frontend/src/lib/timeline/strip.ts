/**
 * What the strip along the bottom of the map draws.
 *
 * One shape for every timeline: a trip's legs and a spacecraft's record are
 * different subjects, but both are a run of moments and stretches on the
 * simulation clock, and the widget only needs to know which is which. Labels
 * arrive already localized — the strip picks no words of its own.
 */

import type { TimelineSpan } from './axis';

export interface StripItem extends TimelineSpan {
	/** Stable for as long as the run is, so the list can key on it. */
	id: string;
	label: string;
	/** When it happens, formatted for reading at card size. */
	when: string;
	/** A line under the date: what this one is, in a few words. */
	detail?: string;
	/** A stretch of the run rather than a moment in it. */
	isPhase: boolean;
	/** The colour its stretch of the bar is drawn in. */
	color?: string;
	/** Says why this one is marked out — the strip shows it as a hint on the
	 *  card and dims the mark on the bar. */
	note?: string;
}
