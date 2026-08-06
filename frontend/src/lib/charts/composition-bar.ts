/**
 * What the shared composition bar draws, and where it stops naming things.
 *
 * The atmosphere's gases, the body's materials and a layer's chemistry are one
 * chart over three vocabularies, so each vocabulary maps itself to entries and
 * the bar does the rest — the ranking, the trace bucket and every hover
 * sentence are decided in one place.
 */
export interface CompositionEntry {
	/** Stable identity, for the keyed each and for nothing else. */
	key: string;
	/** Legend text: a formula, an element symbol, or a name. */
	label: string;
	/** The thing spelled out, for the hover and for the trace bucket's list. A
	 *  label equal to it is not an abbreviation, and its legend entry gets no
	 *  hover — one that only repeats its own trigger is a flicker for nothing. */
	name: string;
	/** 0–1, of whatever the bar is a share of. */
	share: number;
	color: string;
	/** Hatched, and read "under": a non-detection limit, not an abundance. */
	limit?: boolean;
	/** The width a source published around the share, added under the hover. */
	range?: [number, number];
}

/** Under this share a substance is an impurity rather than an ingredient. */
export const TRACE_SHARE = 0.01;

/** A legend past this length is a list rather than a glance; the tail folds. */
export const MAX_SEGMENTS = 6;

/** A remainder thinner than this is not worth a segment of its own. */
export const MIN_TRACE = 0.001;

/**
 * Rank a composition and fold its tail into trace. Input order is ignored — a
 * bar always reads most to least.
 *
 * `trace` is the folded total; the bar draws a segment for it only if it clears
 * `MIN_TRACE`, since a sliver a thousandth wide is a legend entry for nothing.
 */
export function foldTrace(entries: CompositionEntry[]): {
	shown: CompositionEntry[];
	folded: CompositionEntry[];
	trace: number;
} {
	const ranked = [...entries].sort((a, b) => b.share - a.share);
	const shown = ranked.filter((entry) => entry.share >= TRACE_SHARE).slice(0, MAX_SEGMENTS);
	const folded = ranked.slice(shown.length);
	// A bucket of one is a substance with its name taken off it. Titan's 0.1%
	// of hydrogen is better read as hydrogen than as "everything else".
	if (folded.length === 1) return { shown: [...shown, ...folded], folded: [], trace: 0 };
	return { shown, folded, trace: folded.reduce((sum, entry) => sum + entry.share, 0) };
}
