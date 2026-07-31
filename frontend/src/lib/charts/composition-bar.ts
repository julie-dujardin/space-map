/**
 * The shape the shared composition bar draws. Both the atmosphere and the
 * interior panels are the same chart — a stacked share bar with a hoverable
 * legend — over different vocabularies, so they share the component and each
 * does its own formatting before handing segments over.
 */
export interface CompositionSegment {
	key: string;
	/** Legend text: a formula, an element symbol, or a name. */
	label: string;
	/** Legend value, already formatted — may carry a "<" for an upper limit. */
	value: string;
	/** The whole hover sentence, already formatted. Always used by the bar: a
	 *  coloured block carries no text, so there is nothing to read without it. */
	tooltip: string;
	/** The legend hovers as well, because `label` is an abbreviation the reader
	 *  may not know — a formula, an element symbol. Left false where the label
	 *  already spells the thing out ("rock"), since a hover that only repeats
	 *  its own trigger is a flicker for nothing. */
	labelIsAbbreviated?: boolean;
	/** 0–1, of whatever the bar is a share of. */
	share: number;
	color: string;
	/** Hatched: a non-detection limit rather than a measured abundance. */
	limit?: boolean;
}
