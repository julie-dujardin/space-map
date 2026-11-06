/**
 * Conditions the scene reports while it runs: the clock has left the data, it
 * stopped at a probe's data wall, or a sphere in view wears an artist's
 * impression. A notice holds raw dates and ids, not sentences. The page
 * around the map words them and decides how to show them.
 */

/** A coverage edge the clock has crossed, and where it lies. */
export interface CoverageEdge {
	side: 'before' | 'after';
	jd: number;
}

/** Which groups lack data at the current time. */
export interface OutOfRangeNotice {
	topic: 'out-of-range';
	focusedOutOfRange: boolean;
	/** Zone-level satellite coverage: past the archive, or inside a hole. */
	satellites: { side: 'after'; jd: number } | { side: 'gap' } | null;
	majorBodies: CoverageEdge | { side: 'outside' } | null;
}

/** The clock stopped at the focused probe's trajectory data wall. */
export interface CoveragePauseNotice {
	topic: 'coverage-pause';
	name: string;
	direction: 'forward' | 'backward';
	jd: number;
}

/**
 * A body drawn as a sphere wears an artist's impression, not a picture of it.
 * Sent again when the body it speaks of changes, and dismissed once no such
 * sphere is in view.
 */
export interface ArtistImpressionNotice {
	topic: 'artist-impression';
	/** The body: the focused one when it wears an impression, else the
	 *  nearest that does. */
	id: string;
}

export type Notice = OutOfRangeNotice | CoveragePauseNotice | ArtistImpressionNotice;
export type NoticeTopic = Notice['topic'];

/** Where the scene sends them. One live notice per topic: a repeat replaces
 *  the previous one, and the topic is dismissed when the condition clears. */
export interface NoticeSink {
	notify(notice: Notice): void;
	dismiss(topic: NoticeTopic): void;
}
